import asyncio
import json
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import Gauge, InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import get_current_span
from support.fakes import (
    FakeCallAutomationGateway,
    FakeCancellationSignal,
    FakeClock,
    FakeRequestRepository,
    FakeTelemetry,
)

from ask_my_human.application.ports import TelemetryOperation
from ask_my_human.application.service import AskHumanService
from ask_my_human.contracts import (
    AskHumanRequest,
    AskHumanResult,
    Outcome,
    RequestKind,
    RequestStatus,
)
from ask_my_human.domain.models import (
    CallEvent,
    CallEventType,
    HumanRequest,
    Principal,
    RequestState,
)
from ask_my_human.errors import AskMyHumanError, ErrorCode
from ask_my_human.observability import AzureMonitorTelemetry, SpanName


def make_request() -> AskHumanRequest:
    return AskHumanRequest(kind=RequestKind.APPROVAL, prompt="Deploy?", idempotencyKey=uuid4())


def make_service(
    repository: FakeRequestRepository,
    gateway: FakeCallAutomationGateway,
    clock: FakeClock,
) -> AskHumanService:
    return AskHumanService(repository, gateway, clock, FakeTelemetry())


@pytest.mark.asyncio
async def test_stalled_call_creation_is_bounded_by_request_deadline() -> None:
    class StalledGateway(FakeCallAutomationGateway):
        async def create_call(self, request):  # type: ignore[no-untyped-def]
            self.created.append(request)
            await asyncio.Event().wait()
            return "unreachable"

    repository = FakeRequestRepository()
    gateway = StalledGateway()
    service = AskHumanService(
        repository,
        gateway,
        FakeClock(),
        FakeTelemetry(),
        deadline_seconds=0.1,
        work_cutoff_seconds=0.05,
        poll_interval_seconds=0.005,
    )
    result = await asyncio.wait_for(
        service.ask(Principal("subject", "app"), make_request(), FakeCancellationSignal()),
        timeout=0.5,
    )
    assert result.outcome is Outcome.DEADLINE_EXCEEDED
    stored = await repository.get(result.request_id)
    assert stored is not None and stored.result == result
    assert len(gateway.created) == 1


@pytest.mark.asyncio
async def test_creator_starts_one_call_and_fixed_cutoff_expires() -> None:
    repository = FakeRequestRepository()
    gateway = FakeCallAutomationGateway()
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    telemetry = FakeTelemetry()
    result = await AskHumanService(repository, gateway, clock, telemetry).ask(
        Principal("subject", "app"), make_request(), FakeCancellationSignal()
    )
    assert result.status is RequestStatus.EXPIRED
    assert result.outcome is Outcome.DEADLINE_EXCEEDED
    assert len(gateway.created) == 1
    assert gateway.hung_up == [f"call-{result.request_id}"]
    assert gateway.recognitions == []
    assert clock.current == datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=205)
    correlations = [
        record
        for record in telemetry.records
        if record["operation"] is TelemetryOperation.CALL_CREATED
    ]
    assert len(correlations) == 1
    assert correlations[0]["request_id"] == result.request_id
    assert correlations[0]["call_id"] == f"call-{result.request_id}"


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
    gateway = FakeCallAutomationGateway()
    telemetry = FakeTelemetry()
    service = AskHumanService(repository, gateway, clock, telemetry)
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
    assert gateway.created == []
    observations = [
        record
        for record in telemetry.records
        if record["operation"] is TelemetryOperation.JOIN_PENDING
    ]
    assert len(observations) == 1
    assert observations[0]["request_id"] == stored.request_id
    assert observations[0]["replay"] is True
    assert observations[0]["status"] is None


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
    await service.handle_call_event(
        CallEvent(stored.request_id, CallEventType.APPROVED, call_id="call-id")
    )
    await service.handle_call_event(
        CallEvent(stored.request_id, CallEventType.REJECTED, call_id="call-id")
    )
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
        async def create_call(self, request):  # type: ignore[no-untyped-def]
            call_id = await super().create_call(request)
            await service.handle_call_event(
                CallEvent(request.request_id, CallEventType.CONNECTED, call_id=call_id)
            )
            return call_id

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


async def admit_for_callback(
    repository: FakeRequestRepository,
    service: AskHumanService,
    *,
    kind: RequestKind = RequestKind.APPROVAL,
    attach: bool = True,
) -> HumanRequest:
    request = AskHumanRequest(kind=kind, prompt="Question?", idempotencyKey=uuid4())
    _, stored = await repository.create_or_replay(
        Principal("subject", "app"),
        request,
        service._request_hash(request),
        service._clock.now() + service._deadline,
    )
    if attach:
        await repository.attach_call_id(stored.request_id, "call-id")
    return stored


async def test_connected_claim_is_once_only_across_duplicate_callbacks_and_service_restart() -> (
    None
):
    clock = FakeClock()
    repository = FakeRequestRepository(clock)
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, clock)
    stored = await admit_for_callback(repository, service)
    event = CallEvent(stored.request_id, CallEventType.CONNECTED, call_id="call-id")
    await asyncio.gather(service.handle_call_event(event), service.handle_call_event(event))
    await make_service(repository, gateway, clock).handle_call_event(event)
    assert len(gateway.recognitions) == 1
    assert repository.requests[stored.request_id].recognition_started
    assert repository.requests[stored.request_id].state is RequestState.PENDING


@pytest.mark.parametrize(
    "event_type",
    [
        CallEventType.CONNECTED,
        CallEventType.APPROVED,
        CallEventType.DEPENDENCY_FAILED,
        CallEventType.PLAY_COMPLETED,
    ],
)
@pytest.mark.parametrize("call_id", [None, "different-call"])
async def test_uncorrelated_callbacks_cannot_mutate_or_control_call(
    event_type: CallEventType,
    call_id: str | None,
) -> None:
    repository = FakeRequestRepository()
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, FakeClock())
    stored = await admit_for_callback(repository, service)
    await service.handle_call_event(CallEvent(stored.request_id, event_type, call_id=call_id))
    assert repository.requests[stored.request_id].state is RequestState.PENDING
    assert gateway.recognitions == []
    assert gateway.acknowledged == []
    assert gateway.playback_events == []


async def test_connected_before_create_response_attaches_same_id_and_starts_once() -> None:
    repository = FakeRequestRepository()

    class EarlyConnectedGateway(FakeCallAutomationGateway):
        async def create_call(self, request: HumanRequest) -> str:
            call_id = await super().create_call(request)
            await service.handle_call_event(
                CallEvent(request.request_id, CallEventType.CONNECTED, call_id=call_id)
            )
            return call_id

    gateway = EarlyConnectedGateway()
    service = make_service(repository, gateway, FakeClock())
    result = await service.ask(
        Principal("subject", "app"), make_request(), FakeCancellationSignal()
    )
    assert result.outcome is Outcome.DEADLINE_EXCEEDED
    assert len(gateway.created) == len(gateway.recognitions) == 1
    assert repository.requests[result.request_id].call_id == f"call-{result.request_id}"


async def test_mismatched_create_response_after_early_callback_fails_and_cleans_both_calls() -> (
    None
):
    repository = FakeRequestRepository()

    class MismatchingGateway(FakeCallAutomationGateway):
        async def create_call(self, request: HumanRequest) -> str:
            await service.handle_call_event(
                CallEvent(request.request_id, CallEventType.CONNECTED, call_id="early-call")
            )
            return "other-call"

    gateway = MismatchingGateway()
    service = make_service(repository, gateway, FakeClock())
    with pytest.raises(AskMyHumanError) as error:
        await service.ask(Principal("subject", "app"), make_request(), FakeCancellationSignal())
    assert error.value.code is ErrorCode.DEPENDENCY_FAILURE
    assert set(gateway.hung_up) == {"early-call", "other-call"}


@pytest.mark.parametrize(
    ("kind", "event_type", "answer"),
    [
        (RequestKind.APPROVAL, CallEventType.ANSWERED, "Yes"),
        (RequestKind.INPUT, CallEventType.APPROVED, None),
        (RequestKind.INPUT, CallEventType.REJECTED, None),
    ],
)
async def test_wrong_kind_callback_cannot_complete_request(
    kind: RequestKind,
    event_type: CallEventType,
    answer: str | None,
) -> None:
    repository = FakeRequestRepository()
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, FakeClock())
    stored = await admit_for_callback(repository, service, kind=kind)
    await service.handle_call_event(CallEvent(stored.request_id, event_type, answer, "call-id"))
    assert repository.requests[stored.request_id].state is RequestState.PENDING
    assert gateway.acknowledged == []


async def test_technical_callback_is_durable_sanitized_failure_and_updates_telemetry() -> None:
    repository = FakeRequestRepository()
    gateway = FakeCallAutomationGateway()
    telemetry = FakeTelemetry()
    service = AskHumanService(repository, gateway, FakeClock(), telemetry)
    stored = await admit_for_callback(repository, service, attach=False)
    await service.handle_call_event(
        CallEvent(
            stored.request_id,
            CallEventType.DEPENDENCY_FAILED,
            call_id="failed-call",
            acs_code=500,
        )
    )
    current = repository.requests[stored.request_id]
    assert current.state is RequestState.FAILED
    assert current.error_code is ErrorCode.DEPENDENCY_FAILURE
    assert current.error_message == "The call service could not process the request."
    assert gateway.hung_up == ["failed-call"]
    assert telemetry.failures[-1]["acs_code"] == 500
    assert telemetry.pending[-1] is False
    with pytest.raises(AskMyHumanError) as error:
        await service.ask(stored.principal, stored.request, FakeCancellationSignal())
    assert error.value.request_id == stored.request_id


@pytest.mark.parametrize("event_type", [CallEventType.CONNECTED, CallEventType.APPROVED])
async def test_cutoff_rejects_connected_and_success_callbacks(event_type: CallEventType) -> None:
    clock = FakeClock()
    repository = FakeRequestRepository(clock)
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, clock)
    stored = await admit_for_callback(repository, service)
    await clock.sleep(205)
    await service.handle_call_event(CallEvent(stored.request_id, event_type, call_id="call-id"))
    terminal = repository.requests[stored.request_id]
    assert terminal.result is not None and terminal.result.outcome is Outcome.DEADLINE_EXCEEDED
    assert gateway.recognitions == []
    assert gateway.acknowledged == []


async def test_late_claim_response_does_not_start_recognition() -> None:
    clock = FakeClock()

    class LateClaimRepository(FakeRequestRepository):
        async def claim_recognition(self, request_id):  # type: ignore[no-untyped-def]
            claimed = await super().claim_recognition(request_id)
            await clock.sleep(206)
            return claimed

    repository = LateClaimRepository(clock)
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, clock)
    stored = await admit_for_callback(repository, service)
    await service.handle_call_event(
        CallEvent(stored.request_id, CallEventType.CONNECTED, call_id="call-id")
    )
    assert gateway.recognitions == []
    assert repository.requests[stored.request_id].state is RequestState.EXPIRED


async def test_delayed_terminal_write_cannot_succeed_after_work_cutoff() -> None:
    clock = FakeClock()

    class DelayedWriteRepository(FakeRequestRepository):
        async def complete_if_pending(
            self,
            result: AskHumanResult,
            *,
            before: datetime | None = None,
        ) -> bool:
            if result.status is RequestStatus.RESPONDED:
                await clock.sleep(206)
            return await super().complete_if_pending(result, before=before)

    repository = DelayedWriteRepository(clock)
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, clock)
    stored = await admit_for_callback(repository, service)
    await service.handle_call_event(
        CallEvent(stored.request_id, CallEventType.APPROVED, call_id="call-id")
    )
    terminal = repository.requests[stored.request_id]
    assert terminal.result is not None and terminal.result.outcome is Outcome.DEADLINE_EXCEEDED
    assert gateway.acknowledged == []


async def test_recognition_failure_is_not_retried() -> None:
    class FailingRecognition(FakeCallAutomationGateway):
        async def start_recognition(self, call_id: str, request: HumanRequest) -> None:
            await super().start_recognition(call_id, request)
            raise RuntimeError("sensitive provider details")

    repository = FakeRequestRepository()
    gateway = FailingRecognition()
    service = make_service(repository, gateway, FakeClock())
    stored = await admit_for_callback(repository, service)
    event = CallEvent(stored.request_id, CallEventType.CONNECTED, call_id="call-id")
    await service.handle_call_event(event)
    await service.handle_call_event(event)
    assert len(gateway.recognitions) == 1
    assert repository.requests[stored.request_id].state is RequestState.FAILED
    assert gateway.hung_up == ["call-id", "call-id"]


async def test_stalled_recognition_callback_is_bounded_and_expires() -> None:
    class StalledRecognition(FakeCallAutomationGateway):
        async def start_recognition(self, call_id: str, request: HumanRequest) -> None:
            await asyncio.Event().wait()

    repository = FakeRequestRepository()
    gateway = StalledRecognition()
    service = AskHumanService(
        repository,
        gateway,
        FakeClock(),
        FakeTelemetry(),
        deadline_seconds=0.1,
        work_cutoff_seconds=0.02,
    )
    stored = await admit_for_callback(repository, service)
    await asyncio.wait_for(
        service.handle_call_event(
            CallEvent(stored.request_id, CallEventType.CONNECTED, call_id="call-id")
        ),
        0.2,
    )
    assert repository.requests[stored.request_id].state is RequestState.EXPIRED
    assert gateway.hung_up == ["call-id"]


async def test_stalled_admission_returns_sanitized_error_without_accepted_id() -> None:
    class StalledAdmission(FakeRequestRepository):
        async def create_or_replay(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            await asyncio.Event().wait()

    repository = StalledAdmission()
    gateway = FakeCallAutomationGateway()
    service = AskHumanService(
        repository,
        gateway,
        FakeClock(),
        FakeTelemetry(),
        deadline_seconds=0.1,
        work_cutoff_seconds=0.02,
    )
    with pytest.raises(AskMyHumanError) as error:
        await asyncio.wait_for(
            service.ask(
                Principal("subject", "app"),
                make_request(),
                FakeCancellationSignal(),
            ),
            0.2,
        )
    assert error.value.code is ErrorCode.DEPENDENCY_FAILURE
    assert error.value.request_id is None
    assert gateway.created == []


async def test_creator_task_cancellation_persists_expiry_and_cleans_unattached_call() -> None:
    attaching = asyncio.Event()

    class StalledAttachment(FakeRequestRepository):
        async def attach_call_id(self, request_id, call_id):  # type: ignore[no-untyped-def]
            attaching.set()
            await asyncio.Event().wait()
            return False

    repository = StalledAttachment()
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, FakeClock())
    request = make_request()
    work = asyncio.create_task(
        service.ask(
            Principal("subject", "app"),
            request,
            FakeCancellationSignal(),
        )
    )
    await attaching.wait()
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    stored = repository.requests[request.idempotency_key]
    assert stored.result is not None and stored.result.outcome is Outcome.CANCELLED
    assert gateway.hung_up == [f"call-{stored.request_id}"]


@pytest.mark.parametrize("outcome", [Outcome.CANCELLED, Outcome.DEADLINE_EXCEEDED])
async def test_late_connected_event_cleans_call_after_create_was_interrupted(
    outcome: Outcome,
) -> None:
    submitted = asyncio.Event()

    class StalledGateway(FakeCallAutomationGateway):
        async def create_call(self, request: HumanRequest) -> str:
            self.created.append(request)
            submitted.set()
            await asyncio.Event().wait()
            return "unreachable"

    repository = FakeRequestRepository()
    gateway = StalledGateway()
    cancellation = FakeCancellationSignal()
    service = AskHumanService(
        repository,
        gateway,
        FakeClock(),
        FakeTelemetry(),
        deadline_seconds=0.2,
        work_cutoff_seconds=0.1,
    )
    work = asyncio.create_task(
        service.ask(Principal("subject", "app"), make_request(), cancellation)
    )
    await submitted.wait()
    if outcome is Outcome.CANCELLED:
        cancellation.cancel()
    result = await asyncio.wait_for(work, 0.5)
    assert result.outcome is outcome
    assert gateway.hung_up == []
    await service.handle_call_event(
        CallEvent(result.request_id, CallEventType.CONNECTED, call_id="late-call")
    )
    assert gateway.hung_up == ["late-call"]
    assert gateway.recognitions == []
    assert repository.requests[result.request_id].result == result


async def test_losing_expiry_does_not_interrupt_winning_acknowledgement() -> None:
    repository = FakeRequestRepository()
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, FakeClock())
    stored = await admit_for_callback(repository, service)
    result = AskHumanResult(
        requestId=stored.request_id,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.APPROVED,
    )
    await repository.complete_if_pending(result)
    returned = await service._expire(stored, Outcome.CANCELLED, monotonic(), replay=False)
    assert returned == result
    assert gateway.hung_up == []


async def test_playback_after_terminal_reaches_gateway_without_reacknowledging() -> None:
    repository = FakeRequestRepository()
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, FakeClock())
    stored = await admit_for_callback(repository, service)
    await service.handle_call_event(
        CallEvent(stored.request_id, CallEventType.APPROVED, call_id="call-id")
    )
    event = CallEvent(stored.request_id, CallEventType.PLAY_COMPLETED, call_id="call-id")
    await service.handle_call_event(event)
    assert gateway.playback_events == [event]
    assert gateway.acknowledged == ["call-id"]


async def test_real_work_runs_inside_telemetry_spans() -> None:
    telemetry = FakeTelemetry()
    repository = FakeRequestRepository()

    class ObservedGateway(FakeCallAutomationGateway):
        async def create_call(self, request: HumanRequest) -> str:
            assert TelemetryOperation.ASK in telemetry.active_spans
            assert TelemetryOperation.CREATE_CALL in telemetry.active_spans
            call_id = await super().create_call(request)
            await service.handle_call_event(
                CallEvent(request.request_id, CallEventType.CONNECTED, call_id=call_id)
            )
            await service.handle_call_event(
                CallEvent(request.request_id, CallEventType.APPROVED, call_id=call_id)
            )
            return call_id

        async def start_recognition(self, call_id: str, request: HumanRequest) -> None:
            assert TelemetryOperation.CALLBACK in telemetry.active_spans
            assert TelemetryOperation.RECOGNIZE in telemetry.active_spans
            await super().start_recognition(call_id, request)

    service = AskHumanService(repository, ObservedGateway(), FakeClock(), telemetry)
    result = await service.ask(
        Principal("subject", "app"), make_request(), FakeCancellationSignal()
    )
    assert result.outcome is Outcome.APPROVED
    assert telemetry.pending[0] is True and telemetry.pending[-1] is False
    assert {operation for operation, _ in telemetry.spans} == {
        TelemetryOperation.ASK,
        TelemetryOperation.CALLBACK,
        TelemetryOperation.REPOSITORY,
        TelemetryOperation.CREATE_CALL,
        TelemetryOperation.RECOGNIZE,
    }
    assert telemetry.active_spans == []


async def test_late_admission_response_does_not_start_a_call() -> None:
    clock = FakeClock()

    class LateAdmission(FakeRequestRepository):
        async def create_or_replay(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            admission = await super().create_or_replay(*args, **kwargs)
            await clock.sleep(206)
            return admission

    repository = LateAdmission(clock)
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, clock)
    result = await service.ask(
        Principal("subject", "app"), make_request(), FakeCancellationSignal()
    )
    assert result.outcome is Outcome.DEADLINE_EXCEEDED
    assert gateway.created == []


async def test_deadline_with_stalled_cleanup_does_not_gain_another_budget() -> None:
    clock = FakeClock()

    class StalledCleanup(FakeRequestRepository):
        async def complete_if_pending(
            self,
            result: AskHumanResult,
            *,
            before: datetime | None = None,
        ) -> bool:
            await asyncio.Event().wait()
            return False

    class StalledHangup(FakeCallAutomationGateway):
        async def hang_up(self, call_id: str) -> None:
            self.hung_up.append(call_id)
            await asyncio.Event().wait()

    repository = StalledCleanup(clock)
    gateway = StalledHangup()
    service = AskHumanService(
        repository,
        gateway,
        clock,
        FakeTelemetry(),
        deadline_seconds=0.12,
        work_cutoff_seconds=0.06,
        poll_interval_seconds=0.005,
    )
    started = monotonic()
    with pytest.raises(AskMyHumanError) as error:
        await asyncio.wait_for(
            service.ask(
                Principal("subject", "app"),
                make_request(),
                FakeCancellationSignal(),
            ),
            0.3,
        )
    assert monotonic() - started < 0.2
    assert error.value.code is ErrorCode.DEPENDENCY_FAILURE
    assert gateway.hung_up


async def test_cancelled_join_during_repository_poll_does_not_change_shared_state() -> None:
    reading = asyncio.Event()

    class StalledRead(FakeRequestRepository):
        async def get(self, request_id):  # type: ignore[no-untyped-def]
            reading.set()
            await asyncio.Event().wait()

    repository = StalledRead()
    gateway = FakeCallAutomationGateway()
    service = make_service(repository, gateway, FakeClock())
    stored = await admit_for_callback(repository, service)
    work = asyncio.create_task(
        service.ask(stored.principal, stored.request, FakeCancellationSignal())
    )
    await reading.wait()
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    assert repository.requests[stored.request_id].state is RequestState.PENDING
    assert gateway.hung_up == []


async def test_repository_poll_failure_is_sanitized_and_releases_admission() -> None:
    class FailedRead(FakeRequestRepository):
        reads = 0

        async def get(self, request_id):  # type: ignore[no-untyped-def]
            self.reads += 1
            if self.reads == 1:
                raise RuntimeError("sensitive SQL parameter content")
            return await super().get(request_id)

    repository = FailedRead()
    service = make_service(repository, FakeCallAutomationGateway(), FakeClock())
    with pytest.raises(AskMyHumanError) as error:
        await service.ask(Principal("subject", "app"), make_request(), FakeCancellationSignal())
    assert error.value.code is ErrorCode.DEPENDENCY_FAILURE
    assert "SQL" not in str(error.value)
    assert await repository.pending_count() == 0


async def test_composed_telemetry_exports_real_spans_metrics_and_no_sensitive_details() -> None:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    telemetry = AzureMonitorTelemetry(
        tracer=tracer_provider.get_tracer("core-test"),
        meter=meter_provider.get_meter("core-test"),
    )
    observed_pending: list[int | float] = []

    class ObservedGateway(FakeCallAutomationGateway):
        async def create_call(self, request: HumanRequest) -> str:
            assert get_current_span().is_recording()
            metric_data = reader.get_metrics_data()
            assert metric_data is not None
            for resource_metrics in metric_data.resource_metrics:
                for scope_metrics in resource_metrics.scope_metrics:
                    for metric in scope_metrics.metrics:
                        if metric.name == "askhuman_pending":
                            assert isinstance(metric.data, Gauge)
                            observed_pending.extend(
                                point.value for point in metric.data.data_points
                            )
            call_id = await super().create_call(request)
            await service.handle_call_event(
                CallEvent(request.request_id, CallEventType.CONNECTED, call_id=call_id)
            )
            return call_id

        async def start_recognition(self, call_id: str, request: HumanRequest) -> None:
            assert get_current_span().is_recording()
            raise RuntimeError("private-provider-error-SENSITIVE")

    service = AskHumanService(FakeRequestRepository(), ObservedGateway(), FakeClock(), telemetry)
    request = AskHumanRequest(
        kind=RequestKind.APPROVAL, prompt="prompt-SENSITIVE", idempotencyKey=uuid4()
    )
    try:
        with pytest.raises(AskMyHumanError):
            await service.ask(
                Principal("subject-SENSITIVE", "app-SENSITIVE"), request, FakeCancellationSignal()
            )
        spans = exporter.get_finished_spans()
        assert {span.name for span in spans} == {
            name.value
            for name in SpanName
            if name not in {SpanName.JOIN_PENDING, SpanName.CALLBACK_ACCEPTED}
        }
        assert all(span.end_time is not None and span.start_time is not None for span in spans)
        assert observed_pending == [1]
        metric_data = reader.get_metrics_data()
        assert metric_data is not None
        for resource_metrics in metric_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    if metric.name == "askhuman_pending":
                        assert isinstance(metric.data, Gauge)
                        assert [point.value for point in metric.data.data_points] == [0]
        capture = json.dumps([span.to_json() for span in spans]) + str(metric_data)
        assert "askhuman_dependency_failures_total" in capture
        assert "SENSITIVE" not in capture
    finally:
        tracer_provider.shutdown()
        meter_provider.shutdown()
