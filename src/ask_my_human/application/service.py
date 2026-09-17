"""Synchronous request orchestration over the frozen application ports."""

import asyncio
import hashlib
import json
from collections.abc import Awaitable
from contextlib import suppress
from datetime import datetime, timedelta
from time import monotonic
from typing import TypeVar
from uuid import UUID, uuid4

from ask_my_human.application.ports import (
    CallAutomationGateway,
    CancellationSignal,
    Clock,
    RequestRepository,
    Telemetry,
    TelemetryOperation,
)
from ask_my_human.contracts import (
    AskHumanRequest,
    AskHumanResult,
    Outcome,
    RequestStatus,
)
from ask_my_human.domain.models import (
    CallEvent,
    CallEventType,
    HumanRequest,
    Principal,
    RequestState,
)
from ask_my_human.domain.transitions import complete
from ask_my_human.errors import AskMyHumanError, ErrorCode

DependencyValue = TypeVar("DependencyValue")


class AskHumanService:
    def __init__(
        self,
        repository: RequestRepository,
        gateway: CallAutomationGateway,
        clock: Clock,
        telemetry: Telemetry,
        *,
        deadline_seconds: float = 210,
        work_cutoff_seconds: float = 205,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        if not 0 < work_cutoff_seconds < deadline_seconds:
            raise ValueError("work cutoff must be positive and earlier than the deadline")
        if poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        self._repository = repository
        self._gateway = gateway
        self._clock = clock
        self._telemetry = telemetry
        self._deadline = timedelta(seconds=deadline_seconds)
        self._work_cutoff = timedelta(seconds=work_cutoff_seconds)
        self._poll_interval_seconds = poll_interval_seconds
        self._cleanup_seconds = min(5.0, deadline_seconds - work_cutoff_seconds)
        self._active: dict[UUID, tuple[float, CancellationSignal]] = {}
        self._call_ids: dict[UUID, str] = {}

    async def ask(
        self,
        principal: Principal,
        request: AskHumanRequest,
        cancellation: CancellationSignal,
    ) -> AskHumanResult:
        started = monotonic()
        with self._telemetry.span(TelemetryOperation.ASK, request_id=uuid4(), kind=request.kind):
            try:
                async with asyncio.timeout(self._deadline.total_seconds()):
                    return await self._ask(principal, request, cancellation, started)
            except TimeoutError:
                raise self._dependency_error() from None

    async def _ask(
        self,
        principal: Principal,
        request: AskHumanRequest,
        cancellation: CancellationSignal,
        started: float,
    ) -> AskHumanResult:
        request_hash = self._request_hash(request)
        admission_work = asyncio.create_task(
            self._dependency(
                TelemetryOperation.REPOSITORY,
                self._repository.create_or_replay(
                    principal,
                    request,
                    request_hash,
                    self._clock.now() + self._deadline,
                ),
                uuid4(),
            )
        )
        admission_cancelled = asyncio.create_task(cancellation.wait())
        try:
            admission_done, _ = await asyncio.wait(
                {admission_work, admission_cancelled},
                timeout=self._work_cutoff.total_seconds(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if admission_work not in admission_done:
                if cancellation.cancelled:
                    raise asyncio.CancelledError
                self._telemetry.dependency_failed(
                    TelemetryOperation.REPOSITORY, error_code=ErrorCode.DEPENDENCY_FAILURE
                )
                raise self._dependency_error()
            admission, stored = await admission_work
        except asyncio.CancelledError:
            raise
        except Exception:
            raise self._dependency_error() from None
        finally:
            admission_work.cancel()
            admission_cancelled.cancel()
            await asyncio.gather(admission_work, admission_cancelled, return_exceptions=True)

        if admission in {"created", "joined_pending"}:
            self._telemetry.set_pending(True)

        if admission == "joined_pending":
            with self._telemetry.span(
                TelemetryOperation.ASK,
                request_id=stored.request_id,
                pending_join=True,
            ):
                pass

        if admission == "conflict":
            raise AskMyHumanError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "The idempotency key was already used for a different request.",
                request_id=stored.request_id,
            )
        if admission == "pending_admission_lost":
            await self._sync_pending()
            raise AskMyHumanError(
                ErrorCode.RATE_LIMITED,
                "Another human request is already pending.",
                request_id=stored.request_id,
            )
        if admission == "replayed":
            await self._sync_pending()
            return self._terminal_value(stored, started, replay=True)

        creator = admission == "created"
        if creator:
            self._active[stored.request_id] = (
                started + self._work_cutoff.total_seconds(),
                cancellation,
            )
        work = asyncio.create_task(self._run_request(stored, cancellation, creator, started))
        cancelled = asyncio.create_task(cancellation.wait())
        remaining = min(
            self._remaining(stored),
            max(0.0, started + self._work_cutoff.total_seconds() - monotonic()),
        )
        try:
            done, _ = await asyncio.wait(
                {work, cancelled}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if work in done:
                return await work
            work.cancel()
            with suppress(asyncio.CancelledError):
                await work
            if cancellation.cancelled and not creator:
                raise asyncio.CancelledError
            outcome = Outcome.CANCELLED if cancellation.cancelled else Outcome.DEADLINE_EXCEEDED
            return await self._expire(stored, outcome, started, replay=not creator)
        except asyncio.CancelledError:
            work.cancel()
            with suppress(asyncio.CancelledError):
                await work
            if creator:
                with suppress(Exception):
                    await asyncio.shield(
                        self._expire(stored, Outcome.CANCELLED, started, replay=False)
                    )
            raise
        except AskMyHumanError:
            raise
        except Exception:
            if creator:
                with suppress(Exception):
                    await self._fail(stored, TelemetryOperation.REPOSITORY, report=False)
            raise self._dependency_error(stored.request_id) from None
        finally:
            if creator:
                self._active.pop(stored.request_id, None)
                self._call_ids.pop(stored.request_id, None)
            cancelled.cancel()
            with suppress(asyncio.CancelledError):
                await cancelled

    async def _run_request(
        self,
        stored: HumanRequest,
        cancellation: CancellationSignal,
        creator: bool,
        started: float,
    ) -> AskHumanResult:
        if creator and not cancellation.cancelled and self._remaining(stored) > 0:
            current = await self._require_request(stored.request_id)
            if (
                current.state is RequestState.PENDING
                and not cancellation.cancelled
                and self._remaining(current) > 0
            ):
                await self._start_call(current, cancellation)
        return await self._wait_for_terminal(stored, cancellation, creator, started)

    def _cutoff(self, stored: HumanRequest) -> datetime:
        return stored.expires_at - (self._deadline - self._work_cutoff)

    def _remaining(self, stored: HumanRequest) -> float:
        remaining = (self._cutoff(stored) - self._clock.now()).total_seconds()
        active = self._active.get(stored.request_id)
        if active is not None:
            remaining = min(remaining, active[0] - monotonic())
        return max(0.0, remaining)

    async def _expire(
        self, stored: HumanRequest, outcome: Outcome, started: float, *, replay: bool
    ) -> AskHumanResult:
        current = stored
        budget = min(
            self._cleanup_seconds,
            max(0.0, started + self._deadline.total_seconds() - monotonic()),
        )
        try:
            async with asyncio.timeout(budget):
                try:
                    async with asyncio.timeout(budget * 0.75):
                        await self._dependency(
                            TelemetryOperation.REPOSITORY,
                            self._repository.complete_if_pending(
                                AskHumanResult(
                                    requestId=stored.request_id,
                                    status=RequestStatus.EXPIRED,
                                    outcome=outcome,
                                )
                            ),
                            stored.request_id,
                        )
                        current = await self._require_request(stored.request_id)
                        await self._sync_pending()
                finally:
                    if current.state is not RequestState.RESPONDED:
                        await self._best_effort_hang_up(
                            current.call_id or self._call_ids.get(stored.request_id)
                        )
                return self._terminal_value(current, started, replay=replay)
        except Exception:
            raise self._dependency_error(stored.request_id) from None

    async def handle_call_event(self, event: CallEvent) -> None:
        with self._telemetry.span(
            TelemetryOperation.CALLBACK,
            request_id=event.request_id,
            call_id=event.call_id,
            event_id=event.event_id,
        ):
            try:
                async with asyncio.timeout(self._cleanup_seconds):
                    stored = await self._dependency(
                        TelemetryOperation.REPOSITORY,
                        self._repository.get(event.request_id),
                        event.request_id,
                    )
            except Exception:
                raise self._dependency_error(event.request_id) from None
            if stored is None or event.call_id is None:
                return
            if stored.call_id is not None and stored.call_id != event.call_id:
                return
            if event.event_type in {CallEventType.PLAY_COMPLETED, CallEventType.PLAY_FAILED}:
                if stored.call_id == event.call_id:
                    async with asyncio.timeout(self._cleanup_seconds):
                        await self._gateway.handle_playback_event(event)
                return
            if stored.state is not RequestState.PENDING:
                await self._cleanup_late_connection(stored, event)
                return
            try:
                if self._remaining(stored) <= 0:
                    expiry_result = await self._expire(
                        stored, Outcome.DEADLINE_EXCEEDED, monotonic(), replay=False
                    )
                    if stored.call_id is None and expiry_result.status is RequestStatus.EXPIRED:
                        await self._best_effort_hang_up(event.call_id)
                    return
                async with asyncio.timeout(self._remaining(stored)):
                    if stored.call_id is None:
                        if not await self._dependency(
                            TelemetryOperation.REPOSITORY,
                            self._repository.attach_call_id(stored.request_id, event.call_id),
                            stored.request_id,
                        ):
                            return
                        stored = await self._require_request(stored.request_id)
                    if stored.call_id != event.call_id:
                        return
                    if stored.state is not RequestState.PENDING:
                        await self._cleanup_late_connection(stored, event)
                        return
                    if event.event_type is CallEventType.CONNECTED:
                        await self._recognize(stored)
                        return
                    if event.event_type is CallEventType.DEPENDENCY_FAILED:
                        await self._fail(stored, TelemetryOperation.CALLBACK, event.acs_code)
                        return
                    result = complete(stored, event)
                    if result is None:
                        return
                    if self._remaining(stored) <= 0:
                        raise TimeoutError
                    won = await self._dependency(
                        TelemetryOperation.REPOSITORY,
                        self._repository.complete_if_pending(
                            result,
                            before=self._cutoff(stored),
                        ),
                        stored.request_id,
                    )
                await self._sync_pending()
                if not won:
                    if self._remaining(stored) <= 0:
                        await self._expire(
                            stored,
                            Outcome.DEADLINE_EXCEEDED,
                            monotonic(),
                            replay=False,
                        )
                    return
                self._record(stored, result, replay=False, started=None, acs_code=event.acs_code)
                if result.status is RequestStatus.RESPONDED:
                    try:
                        async with asyncio.timeout(self._cleanup_seconds):
                            await self._gateway.acknowledge_and_hang_up(
                                event.call_id,
                                request_id=stored.request_id,
                            )
                    except Exception:
                        await self._best_effort_hang_up(event.call_id)
                else:
                    await self._best_effort_hang_up(event.call_id)
            except TimeoutError:
                await self._expire(stored, Outcome.DEADLINE_EXCEEDED, monotonic(), replay=False)
            except Exception:
                await self._fail(stored, TelemetryOperation.CALLBACK, event.acs_code)

    async def _cleanup_late_connection(self, stored: HumanRequest, event: CallEvent) -> None:
        if event.event_type is CallEventType.CONNECTED and stored.state in {
            RequestState.EXPIRED,
            RequestState.FAILED,
        }:
            await self._best_effort_hang_up(event.call_id)

    async def _recognize(self, stored: HumanRequest) -> None:
        active = self._active.get(stored.request_id)
        if self._remaining(stored) <= 0 or (active is not None and active[1].cancelled):
            return
        if not await self._dependency(
            TelemetryOperation.REPOSITORY,
            self._repository.claim_recognition(stored.request_id),
            stored.request_id,
        ):
            return
        current = await self._require_request(stored.request_id)
        if current.state is not RequestState.PENDING:
            return
        if self._remaining(current) <= 0:
            raise TimeoutError
        if active is not None and active[1].cancelled:
            return
        if current.call_id is not None:
            try:
                await self._dependency(
                    TelemetryOperation.RECOGNIZE,
                    self._gateway.start_recognition(current.call_id, current),
                    current.request_id,
                )
            except Exception:
                await self._fail(current, TelemetryOperation.RECOGNIZE, report=False)

    async def _start_call(self, stored: HumanRequest, cancellation: CancellationSignal) -> None:
        call_id: str | None = None
        try:
            call_id = await self._dependency(
                TelemetryOperation.CREATE_CALL,
                self._gateway.create_call(stored),
                stored.request_id,
            )
            with self._telemetry.span(
                TelemetryOperation.CREATE_CALL,
                request_id=stored.request_id,
                call_id=call_id,
            ):
                pass
            self._call_ids[stored.request_id] = call_id
            attached = await self._dependency(
                TelemetryOperation.REPOSITORY,
                self._repository.attach_call_id(stored.request_id, call_id),
                stored.request_id,
            )
            current = await self._require_request(stored.request_id)
            if not attached:
                if current.state is RequestState.PENDING:
                    await self._fail(current, TelemetryOperation.CREATE_CALL)
                if current.call_id != call_id or current.state is not RequestState.RESPONDED:
                    await self._best_effort_hang_up(call_id)
        except Exception:
            await self._fail(stored, TelemetryOperation.CREATE_CALL, report=False)

    @staticmethod
    def _dependency_error(request_id: UUID | None = None) -> AskMyHumanError:
        return AskMyHumanError(
            ErrorCode.DEPENDENCY_FAILURE,
            "The call service could not process the request.",
            request_id=request_id,
        )

    async def _fail(
        self,
        stored: HumanRequest,
        operation: TelemetryOperation,
        acs_code: int | None = None,
        *,
        report: bool = True,
    ) -> None:
        if report:
            self._telemetry.dependency_failed(
                operation,
                acs_code=acs_code,
                error_code=ErrorCode.DEPENDENCY_FAILURE,
            )
        error = self._dependency_error(stored.request_id)
        try:
            async with asyncio.timeout(self._cleanup_seconds):
                won = await self._dependency(
                    TelemetryOperation.REPOSITORY,
                    self._repository.complete_error_if_pending(
                        stored.request_id,
                        error.code,
                        error.message,
                    ),
                    stored.request_id,
                )
                await self._sync_pending()
                if won:
                    current = await self._require_request(stored.request_id)
                    await self._best_effort_hang_up(
                        current.call_id or self._call_ids.get(stored.request_id)
                    )
        except Exception:
            await self._best_effort_hang_up(stored.call_id or self._call_ids.get(stored.request_id))
            raise error from None

    async def _dependency(
        self,
        operation: TelemetryOperation,
        work: Awaitable[DependencyValue],
        request_id: UUID,
    ) -> DependencyValue:
        with self._telemetry.span(operation, request_id=request_id):
            try:
                return await work
            except Exception:
                self._telemetry.dependency_failed(
                    operation,
                    error_code=ErrorCode.DEPENDENCY_FAILURE,
                )
                raise

    async def _sync_pending(self) -> None:
        with suppress(Exception):
            async with asyncio.timeout(min(1.0, self._cleanup_seconds / 4)):
                count = await self._dependency(
                    TelemetryOperation.REPOSITORY,
                    self._repository.pending_count(),
                    uuid4(),
                )
                self._telemetry.set_pending(count > 0)

    async def _wait_for_terminal(
        self,
        stored: HumanRequest,
        cancellation: CancellationSignal,
        creator: bool,
        started: float,
    ) -> AskHumanResult:
        cutoff = self._cutoff(stored)
        while True:
            current = await self._require_request(stored.request_id)
            if current is None:
                raise AskMyHumanError(
                    ErrorCode.INTERNAL,
                    "The accepted request could not be loaded.",
                    request_id=stored.request_id,
                )
            if current.state is not RequestState.PENDING:
                return self._terminal_value(current, started, replay=not creator)

            if cancellation.cancelled:
                if not creator:
                    raise asyncio.CancelledError
                return await self._expire(stored, Outcome.CANCELLED, started, replay=False)

            if self._clock.now() >= cutoff or self._remaining(stored) <= 0:
                return await self._expire(
                    stored, Outcome.DEADLINE_EXCEEDED, started, replay=not creator
                )
            await self._clock.sleep(self._poll_interval_seconds)

    async def _require_request(self, request_id: UUID) -> HumanRequest:
        current = await self._dependency(
            TelemetryOperation.REPOSITORY,
            self._repository.get(request_id),
            request_id,
        )
        if current is None:
            raise AskMyHumanError(ErrorCode.INTERNAL, "The accepted request could not be loaded.")
        return current

    async def _best_effort_hang_up(self, call_id: str | None) -> None:
        if call_id is None:
            return
        with suppress(Exception):
            async with asyncio.timeout(self._cleanup_seconds / 4):
                await self._gateway.hang_up(call_id)

    def _terminal_value(
        self, stored: HumanRequest, started: float, *, replay: bool
    ) -> AskHumanResult:
        if stored.error_code is not None and stored.error_message is not None:
            raise AskMyHumanError(
                stored.error_code,
                stored.error_message,
                request_id=stored.request_id,
            )
        if stored.result is None:
            raise AskMyHumanError(
                ErrorCode.INTERNAL,
                "The terminal request has no result.",
                request_id=stored.request_id,
            )
        self._record(stored, stored.result, replay=replay, started=started)
        return stored.result

    def _record(
        self,
        stored: HumanRequest,
        result: AskHumanResult,
        *,
        replay: bool,
        started: float | None,
        acs_code: int | None = None,
    ) -> None:
        operation = TelemetryOperation.ASK if started is not None else TelemetryOperation.CALLBACK
        self._telemetry.record(
            operation=operation,
            request_id=stored.request_id,
            kind=stored.request.kind,
            status=result.status,
            outcome=result.outcome,
            elapsed_ms=None if started is None else int((monotonic() - started) * 1000),
            replay=replay,
            acs_code=acs_code,
        )

    @staticmethod
    def _request_hash(request: AskHumanRequest) -> str:
        normalized = json.dumps(
            request.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def _deadline_result(stored: HumanRequest) -> AskHumanResult:
        return AskHumanResult(
            requestId=stored.request_id,
            status=RequestStatus.EXPIRED,
            outcome=Outcome.DEADLINE_EXCEEDED,
        )
