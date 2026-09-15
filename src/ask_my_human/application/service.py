"""Synchronous request orchestration over the frozen application ports."""

import asyncio
import hashlib
import json
from contextlib import suppress
from datetime import timedelta
from time import monotonic
from uuid import UUID

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
from ask_my_human.domain.models import CallEvent, HumanRequest, Principal, RequestState
from ask_my_human.domain.transitions import result_for_event
from ask_my_human.errors import AskMyHumanError, ErrorCode


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

    async def ask(
        self,
        principal: Principal,
        request: AskHumanRequest,
        cancellation: CancellationSignal,
    ) -> AskHumanResult:
        started = monotonic()
        request_hash = self._request_hash(request)
        admission, stored = await self._repository.create_or_replay(
            principal,
            request,
            request_hash,
            self._clock.now() + self._deadline,
        )

        if admission == "conflict":
            raise AskMyHumanError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "The idempotency key was already used for a different request.",
                request_id=stored.request_id,
            )
        if admission == "pending_admission_lost":
            raise AskMyHumanError(
                ErrorCode.RATE_LIMITED,
                "Another human request is already pending.",
                request_id=stored.request_id,
            )
        if admission == "replayed":
            return self._terminal_value(stored, started, replay=True)

        creator = admission == "created"
        if creator and not cancellation.cancelled:
            await self._start_call(stored, cancellation)
        return await self._wait_for_terminal(stored, cancellation, creator, started)

    async def handle_call_event(self, event: CallEvent) -> None:
        stored = await self._repository.get(event.request_id)
        if stored is None or stored.state is not RequestState.PENDING:
            return
        result = result_for_event(event)
        if not await self._repository.complete_if_pending(result):
            return
        self._record(stored, result, replay=False, started=None)
        if stored.call_id is not None:
            with suppress(Exception):
                await self._gateway.acknowledge_and_hang_up(stored.call_id)

    async def _start_call(self, stored: HumanRequest, cancellation: CancellationSignal) -> None:
        call_id: str | None = None
        try:
            call_id = await self._gateway.create_call(stored)
            if not await self._repository.attach_call_id(stored.request_id, call_id):
                raise RuntimeError("call ID could not be attached to the accepted request")
            current = await self._repository.get(stored.request_id)
            if current is None:
                raise RuntimeError("accepted request disappeared")
            can_start_recognition = (
                not cancellation.cancelled
                and self._clock.now() < stored.created_at + self._work_cutoff
            )
            if can_start_recognition:
                await self._gateway.start_recognition(call_id, current)
        except Exception as exception:
            error = AskMyHumanError(
                ErrorCode.DEPENDENCY_FAILURE,
                "The call service could not process the request.",
                request_id=stored.request_id,
            )
            if await self._repository.complete_error_if_pending(
                stored.request_id, error.code, error.message
            ):
                if call_id is not None:
                    await self._best_effort_hang_up(call_id)
                raise error from exception

    async def _wait_for_terminal(
        self,
        stored: HumanRequest,
        cancellation: CancellationSignal,
        creator: bool,
        started: float,
    ) -> AskHumanResult:
        cutoff = stored.created_at + self._work_cutoff
        while True:
            current = await self._repository.get(stored.request_id)
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
                result = AskHumanResult(
                    requestId=stored.request_id,
                    status=RequestStatus.EXPIRED,
                    outcome=Outcome.CANCELLED,
                )
                await self._repository.complete_if_pending(result)
                await self._best_effort_hang_up(current.call_id)
                return self._terminal_value(
                    await self._require_request(stored.request_id), started, replay=False
                )

            if self._clock.now() >= cutoff:
                await self._repository.complete_if_pending(self._deadline_result(stored))
                await self._best_effort_hang_up(current.call_id)
                return self._terminal_value(
                    await self._require_request(stored.request_id), started, replay=not creator
                )
            await self._clock.sleep(self._poll_interval_seconds)

    async def _require_request(self, request_id: UUID) -> HumanRequest:
        current = await self._repository.get(request_id)
        if current is None:
            raise AskMyHumanError(ErrorCode.INTERNAL, "The accepted request could not be loaded.")
        return current

    async def _best_effort_hang_up(self, call_id: str | None) -> None:
        if call_id is None:
            return
        with suppress(Exception):
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
