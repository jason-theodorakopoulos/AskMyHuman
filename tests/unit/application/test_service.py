import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from support.fakes import (
    FakeCallAutomationGateway,
    FakeCancellationSignal,
    FakeClock,
    FakeRequestRepository,
    FakeTelemetry,
)

from ask_my_human.application.service import AskHumanService
from ask_my_human.contracts import (
    AskHumanRequest,
    AskHumanResult,
    Outcome,
    RequestKind,
    RequestStatus,
)
from ask_my_human.domain.models import CallEvent, CallEventType, Principal
from ask_my_human.errors import AskMyHumanError, ErrorCode


def make_request() -> AskHumanRequest:
    return AskHumanRequest(kind=RequestKind.APPROVAL, prompt="Deploy?", idempotencyKey=uuid4())


def make_service(
    repository: FakeRequestRepository,
    gateway: FakeCallAutomationGateway,
    clock: FakeClock,
) -> AskHumanService:
    return AskHumanService(repository, gateway, clock, FakeTelemetry())


@pytest.mark.asyncio
async def test_creator_starts_one_call_and_fixed_cutoff_expires() -> None:
    repository = FakeRequestRepository()
    gateway = FakeCallAutomationGateway()
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    result = await make_service(repository, gateway, clock).ask(
        Principal("subject", "app"), make_request(), FakeCancellationSignal()
    )
    assert result.status is RequestStatus.EXPIRED
    assert result.outcome is Outcome.DEADLINE_EXCEEDED
    assert len(gateway.created) == 1
    assert gateway.hung_up == [f"call-{result.request_id}"]
    assert clock.current == datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=205)


@pytest.mark.asyncio
async def test_slow_call_creation_does_not_start_recognition_after_cutoff() -> None:
    clock = FakeClock()

    class SlowGateway(FakeCallAutomationGateway):
        async def create_call(self, request):  # type: ignore[no-untyped-def]
            call_id = await super().create_call(request)
            await clock.sleep(205)
            return call_id

    repository = FakeRequestRepository()
    gateway = SlowGateway()
    result = await make_service(repository, gateway, clock).ask(
        Principal("subject", "app"), make_request(), FakeCancellationSignal()
    )
    assert result.outcome is Outcome.DEADLINE_EXCEEDED
    assert gateway.recognitions == []


@pytest.mark.asyncio
async def test_creator_cancellation_expires_and_hangs_up() -> None:
    repository = FakeRequestRepository()
    cancellation = FakeCancellationSignal()

    class CancellingGateway(FakeCallAutomationGateway):
        async def create_call(self, request):  # type: ignore[no-untyped-def]
            call_id = await super().create_call(request)
            cancellation.cancel()
            return call_id

    gateway = CancellingGateway()
    result = await make_service(repository, gateway, FakeClock()).ask(
        Principal("subject", "app"), make_request(), cancellation
    )
    assert result.outcome is Outcome.CANCELLED
    assert gateway.recognitions == []
    assert gateway.hung_up == [f"call-{result.request_id}"]


@pytest.mark.asyncio
async def test_joined_waiter_cancellation_does_not_affect_shared_call() -> None:
    repository = FakeRequestRepository()
    request = make_request()
    principal = Principal("subject", "app")
    clock = FakeClock()
    service = make_service(repository, FakeCallAutomationGateway(), clock)
    await repository.create_or_replay(
        principal,
        request,
        service._request_hash(request),
        clock.now() + service._deadline,
    )
    cancellation = FakeCancellationSignal()
    cancellation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await service.ask(principal, request, cancellation)
    stored = await repository.get(request.idempotency_key)
    assert stored is not None
    assert stored.result is None


@pytest.mark.asyncio
async def test_first_callback_result_wins_and_hangs_up_best_effort() -> None:
    repository = FakeRequestRepository()
    gateway = FakeCallAutomationGateway()
    clock = FakeClock()
    request = make_request()
    principal = Principal("subject", "app")
    service = make_service(repository, gateway, clock)
    _, stored = await repository.create_or_replay(
        principal, request, service._request_hash(request), clock.now() + service._deadline
    )
    await repository.attach_call_id(stored.request_id, "call-id")
    await service.handle_call_event(CallEvent(stored.request_id, CallEventType.APPROVED))
    await service.handle_call_event(CallEvent(stored.request_id, CallEventType.REJECTED))
    terminal = await repository.get(stored.request_id)
    assert terminal is not None and terminal.result is not None
    assert terminal.result.outcome is Outcome.APPROVED
    assert gateway.acknowledged == ["call-id"]


@pytest.mark.asyncio
async def test_dependency_failure_is_stable_and_never_creates_duplicate_call() -> None:
    class FailingGateway(FakeCallAutomationGateway):
        async def create_call(self, request):  # type: ignore[no-untyped-def]
            self.created.append(request)
            raise RuntimeError("provider detail")

    repository = FakeRequestRepository()
    gateway = FailingGateway()
    service = make_service(repository, gateway, FakeClock())
    request = make_request()
    principal = Principal("subject", "app")
    with pytest.raises(AskMyHumanError) as first:
        await service.ask(principal, request, FakeCancellationSignal())
    with pytest.raises(AskMyHumanError) as replay:
        await service.ask(principal, request, FakeCancellationSignal())
    assert first.value.code is ErrorCode.DEPENDENCY_FAILURE
    assert replay.value.code is first.value.code
    assert replay.value.message == first.value.message
    assert replay.value.request_id == first.value.request_id
    assert len(gateway.created) == 1


@pytest.mark.asyncio
async def test_dependency_failure_replays_after_service_replacement() -> None:
    class FailingGateway(FakeCallAutomationGateway):
        async def create_call(self, request):  # type: ignore[no-untyped-def]
            self.created.append(request)
            raise RuntimeError("sensitive provider detail")

    repository = FakeRequestRepository()
    gateway = FailingGateway()
    clock = FakeClock()
    request = make_request()
    principal = Principal("subject", "app")

    with pytest.raises(AskMyHumanError) as first:
        await make_service(repository, gateway, clock).ask(
            principal, request, FakeCancellationSignal()
        )
    with pytest.raises(AskMyHumanError) as replay:
        await make_service(repository, gateway, clock).ask(
            principal, request, FakeCancellationSignal()
        )

    assert replay.value.code is ErrorCode.DEPENDENCY_FAILURE
    assert replay.value.message == "The call service could not process the request."
    assert replay.value.request_id == first.value.request_id
    assert "sensitive provider detail" not in replay.value.message
    assert len(gateway.created) == 1


@pytest.mark.asyncio
async def test_human_result_wins_race_with_late_dependency_failure() -> None:
    repository = FakeRequestRepository()

    class RacingGateway(FakeCallAutomationGateway):
        async def start_recognition(self, call_id, request):  # type: ignore[no-untyped-def]
            await repository.complete_if_pending(
                result=AskHumanResult(
                    requestId=request.request_id,
                    status=RequestStatus.RESPONDED,
                    outcome=Outcome.APPROVED,
                )
            )
            raise RuntimeError("late provider failure")

    service = make_service(repository, RacingGateway(), FakeClock())
    result = await service.ask(
        Principal("subject", "app"), make_request(), FakeCancellationSignal()
    )
    assert result.outcome is Outcome.APPROVED


@pytest.mark.asyncio
async def test_idempotency_conflict_is_rejected() -> None:
    repository = FakeRequestRepository()
    service = make_service(repository, FakeCallAutomationGateway(), FakeClock())
    request = make_request()
    principal = Principal("subject", "app")
    await repository.create_or_replay(principal, request, "different", service._clock.now())
    with pytest.raises(AskMyHumanError) as error:
        await service.ask(principal, request, FakeCancellationSignal())
    assert error.value.code is ErrorCode.IDEMPOTENCY_CONFLICT
