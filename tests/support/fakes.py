"""Deterministic fakes shared by adapter and application tests."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from ask_my_human.application.ports import (
    Admission,
    AskHumanUseCase,
    CancellationSignal,
    TelemetryOperation,
)
from ask_my_human.contracts import (
    AskHumanRequest,
    AskHumanResult,
    Outcome,
    RequestKind,
    RequestStatus,
)
from ask_my_human.domain.models import CallEvent, HumanRequest, Principal, RequestState


class FakeCancellationSignal:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()

    def cancel(self) -> None:
        self._event.set()


class FakeClock:
    def __init__(self, now: datetime | None = None) -> None:
        self.current = now or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class FakeAskHumanUseCase(AskHumanUseCase):
    def __init__(self, result: AskHumanResult | None = None) -> None:
        self.result = result
        self.requests: list[tuple[Principal, AskHumanRequest, CancellationSignal]] = []
        self.events: list[CallEvent] = []

    async def ask(
        self,
        principal: Principal,
        request: AskHumanRequest,
        cancellation: CancellationSignal,
    ) -> AskHumanResult:
        self.requests.append((principal, request, cancellation))
        if self.result is None:
            return AskHumanResult(
                requestId=request.idempotency_key,
                status=RequestStatus.EXPIRED,
                outcome=Outcome.DEADLINE_EXCEEDED,
            )
        return self.result

    async def handle_call_event(self, event: CallEvent) -> None:
        self.events.append(event)


class FakeRequestRepository:
    def __init__(self) -> None:
        self.requests: dict[UUID, HumanRequest] = {}
        self.admission: Admission = "created"

    async def create_or_replay(
        self,
        principal: Principal,
        request: AskHumanRequest,
        request_hash: str,
        expires_at: datetime,
    ) -> tuple[Admission, HumanRequest]:
        existing = next(
            (
                item
                for item in self.requests.values()
                if item.principal.subject_id == principal.subject_id
                and item.request.idempotency_key == request.idempotency_key
            ),
            None,
        )
        if existing is not None:
            admission: Admission = (
                "conflict"
                if existing.request_hash != request_hash
                else ("joined_pending" if existing.state is RequestState.PENDING else "replayed")
            )
            return admission, existing
        now = expires_at - timedelta(seconds=210)
        item = HumanRequest(
            request_id=request.idempotency_key,
            principal=principal,
            request=request,
            request_hash=request_hash,
            state=RequestState.PENDING,
            created_at=now,
            expires_at=expires_at,
        )
        self.requests[item.request_id] = item
        return self.admission, item

    async def attach_call_id(self, request_id: UUID, call_id: str) -> bool:
        item = self.requests.get(request_id)
        if item is None or item.call_id is not None:
            return False
        self.requests[request_id] = replace(item, call_id=call_id)
        return True

    async def get(self, request_id: UUID) -> HumanRequest | None:
        return self.requests.get(request_id)

    async def complete_if_pending(self, result: AskHumanResult) -> bool:
        item = self.requests.get(result.request_id)
        if item is None or item.state is not RequestState.PENDING:
            return False
        state = (
            RequestState.RESPONDED
            if result.status is RequestStatus.RESPONDED
            else RequestState.EXPIRED
        )
        self.requests[result.request_id] = replace(item, state=state, result=result)
        return True

    async def expire_stale(self, now: datetime) -> int:
        count = 0
        for request_id, item in list(self.requests.items()):
            if item.state is RequestState.PENDING and item.expires_at <= now:
                result = AskHumanResult(
                    requestId=request_id,
                    status=RequestStatus.EXPIRED,
                    outcome=Outcome.DEADLINE_EXCEEDED,
                )
                self.requests[request_id] = replace(item, state=RequestState.EXPIRED, result=result)
                count += 1
        return count

    async def purge_terminal(self, before: datetime) -> int:
        removable = [
            request_id
            for request_id, item in self.requests.items()
            if item.state is not RequestState.PENDING and item.created_at < before
        ]
        for request_id in removable:
            del self.requests[request_id]
        return len(removable)


class FakeCallAutomationGateway:
    def __init__(self) -> None:
        self.created: list[HumanRequest] = []
        self.recognitions: list[tuple[str, HumanRequest]] = []
        self.acknowledged: list[str] = []
        self.hung_up: list[str] = []

    async def create_call(self, request: HumanRequest) -> str:
        self.created.append(request)
        return f"call-{request.request_id}"

    async def start_recognition(self, call_id: str, request: HumanRequest) -> None:
        self.recognitions.append((call_id, request))

    async def acknowledge_and_hang_up(self, call_id: str) -> None:
        self.acknowledged.append(call_id)

    async def hang_up(self, call_id: str) -> None:
        self.hung_up.append(call_id)


class FakeTelemetry:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(
        self,
        *,
        operation: TelemetryOperation,
        request_id: UUID,
        kind: RequestKind | None = None,
        status: RequestStatus | None = None,
        outcome: Outcome | None = None,
        acs_code: int | None = None,
        elapsed_ms: int | None = None,
        replay: bool | None = None,
    ) -> None:
        self.records.append(
            {
                "operation": operation,
                "request_id": request_id,
                "kind": kind,
                "status": status,
                "outcome": outcome,
                "acs_code": acs_code,
                "elapsed_ms": elapsed_ms,
                "replay": replay,
            }
        )
