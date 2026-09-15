from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from support.fakes import (
    FakeCallAutomationGateway,
    FakeCancellationSignal,
    FakeRequestRepository,
    FakeTelemetry,
)

from ask_my_human.application.ports import (
    CallAutomationGateway,
    CancellationSignal,
    RequestRepository,
    Telemetry,
    TelemetryOperation,
)
from ask_my_human.contracts import (
    AskHumanRequest,
    AskHumanResult,
    Outcome,
    RequestKind,
    RequestStatus,
)
from ask_my_human.domain.models import Principal, RequestState
from ask_my_human.errors import ErrorCode


def request() -> AskHumanRequest:
    return AskHumanRequest(kind=RequestKind.APPROVAL, prompt="Deploy?", idempotencyKey=uuid4())


def principal() -> Principal:
    return Principal(subject_id="subject", application_id="application")


def test_fakes_satisfy_frozen_protocols() -> None:
    repository: RequestRepository = FakeRequestRepository()
    gateway: CallAutomationGateway = FakeCallAutomationGateway()
    cancellation: CancellationSignal = FakeCancellationSignal()
    telemetry: Telemetry = FakeTelemetry()
    assert repository is not None
    assert gateway is not None
    assert cancellation is not None
    assert telemetry is not None


@pytest.mark.asyncio
async def test_cancellation_signals_are_independent() -> None:
    creator = FakeCancellationSignal()
    joiner = FakeCancellationSignal()
    creator.cancel()
    await creator.wait()
    assert creator.cancelled is True
    assert joiner.cancelled is False


@pytest.mark.asyncio
async def test_repository_supports_join_conflict_replay_and_first_terminal_wins() -> None:
    repository = FakeRequestRepository()
    human_request = request()
    expires_at = datetime.now(tz=UTC) + timedelta(seconds=210)

    admission, created = await repository.create_or_replay(
        principal(), human_request, "original", expires_at
    )
    assert admission == "created"

    joined, _ = await repository.create_or_replay(
        principal(), human_request, "original", expires_at
    )
    conflict, _ = await repository.create_or_replay(
        principal(), human_request, "changed", expires_at
    )
    assert joined == "joined_pending"
    assert conflict == "conflict"

    result = AskHumanResult(
        requestId=created.request_id,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.APPROVED,
    )
    assert await repository.complete_if_pending(result) is True
    assert await repository.complete_if_pending(result) is False

    replayed, terminal = await repository.create_or_replay(
        principal(), human_request, "original", expires_at
    )
    assert replayed == "replayed"
    assert terminal.state is RequestState.RESPONDED


@pytest.mark.asyncio
async def test_repository_error_completion_is_terminal_and_replayable() -> None:
    repository = FakeRequestRepository()
    human_request = request()
    _, created = await repository.create_or_replay(
        principal(), human_request, "original", datetime.now(tz=UTC) + timedelta(seconds=210)
    )

    assert await repository.complete_error_if_pending(
        created.request_id,
        ErrorCode.DEPENDENCY_FAILURE,
        "The call service could not process the request.",
    )
    result = AskHumanResult(
        requestId=created.request_id,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.APPROVED,
    )
    assert await repository.complete_if_pending(result) is False

    admission, terminal = await repository.create_or_replay(
        principal(), human_request, "original", datetime.now(tz=UTC) + timedelta(seconds=210)
    )
    assert admission == "replayed"
    assert terminal.state is RequestState.FAILED
    assert terminal.result is None
    assert terminal.error_code is ErrorCode.DEPENDENCY_FAILURE
    assert terminal.error_message == "The call service could not process the request."


@pytest.mark.asyncio
async def test_gateway_records_call_actions() -> None:
    repository = FakeRequestRepository()
    _, created = await repository.create_or_replay(
        principal(), request(), "hash", datetime.now(tz=UTC) + timedelta(seconds=210)
    )
    gateway = FakeCallAutomationGateway()
    call_id = await gateway.create_call(created)
    await gateway.start_recognition(call_id, created)
    await gateway.acknowledge_and_hang_up(call_id)
    await gateway.hang_up(call_id)
    assert gateway.created == [created]
    assert gateway.recognitions == [(call_id, created)]
    assert gateway.acknowledged == [call_id]
    assert gateway.hung_up == [call_id]


def test_telemetry_records_only_typed_contract_fields() -> None:
    telemetry = FakeTelemetry()
    request_id = uuid4()
    telemetry.record(
        operation=TelemetryOperation.ASK,
        request_id=request_id,
        kind=RequestKind.APPROVAL,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.APPROVED,
        elapsed_ms=10,
        replay=False,
    )
    assert telemetry.records == [
        {
            "operation": TelemetryOperation.ASK,
            "request_id": request_id,
            "kind": RequestKind.APPROVAL,
            "status": RequestStatus.RESPONDED,
            "outcome": Outcome.APPROVED,
            "acs_code": None,
            "elapsed_ms": 10,
            "replay": False,
        }
    ]
