"""Deterministic fakes shared by adapter and application tests."""

from datetime import datetime, timedelta, timezone

from ask_my_human.application.ports import AskHumanUseCase
from ask_my_human.contracts import AskHumanRequest, AskHumanResult, Outcome, RequestStatus
from ask_my_human.domain.models import CallEvent, Principal


class FakeClock:
    def __init__(self, now: datetime | None = None) -> None:
        self.current = now or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class FakeAskHumanUseCase(AskHumanUseCase):
    def __init__(self, result: AskHumanResult | None = None) -> None:
        self.result = result
        self.requests: list[tuple[Principal, AskHumanRequest]] = []
        self.events: list[CallEvent] = []

    async def ask(self, principal: Principal, request: AskHumanRequest) -> AskHumanResult:
        self.requests.append((principal, request))
        if self.result is None:
            self.result = AskHumanResult(
                requestId=request.idempotency_key,
                status=RequestStatus.EXPIRED,
                outcome=Outcome.DEADLINE_EXCEEDED,
            )
        return self.result

    async def handle_call_event(self, event: CallEvent) -> None:
        self.events.append(event)
