import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from support.fakes import (
    FakeCallAutomationGateway,
    FakeCancellationSignal,
    FakeClock,
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
from ask_my_human.domain.models import Principal, RequestState
from ask_my_human.errors import AskMyHumanError, ErrorCode
from ask_my_human.persistence.pool import PostgresPool
from ask_my_human.persistence.repository import PostgresRequestRepository

HASH = "a" * 64


def request(
    *,
    prompt: str = "Deploy?",
    idempotency_key: UUID | None = None,
    phone_number: str = "+15555550101",
) -> AskHumanRequest:
    return AskHumanRequest(
        kind=RequestKind.APPROVAL,
        prompt=prompt,
        idempotencyKey=idempotency_key or uuid4(),
        phoneNumber=phone_number,
    )


def principal(subject_id: str = "subject") -> Principal:
    return Principal(subject_id=subject_id, application_id="application")


def expiry() -> datetime:
    return datetime.now(tz=UTC) + timedelta(seconds=210)


@pytest.mark.asyncio
async def test_concurrent_distinct_requests_admit_only_one_pending(
    repository: PostgresRequestRepository,
) -> None:
    first, second = await asyncio.gather(
        repository.create_or_replay(principal("one"), request(), HASH, expiry()),
        repository.create_or_replay(principal("two"), request(), HASH, expiry()),
    )
    assert {first[0], second[0]} == {"created", "pending_admission_lost"}
    winner = first[1] if first[0] == "created" else second[1]
    loser = second[1] if first[0] == "created" else first[1]
    assert await repository.get(winner.request_id) is not None
    assert await repository.get(loser.request_id) is None


@pytest.mark.asyncio
async def test_matching_key_joins_then_replays_and_changed_payload_conflicts(
    repository: PostgresRequestRepository,
) -> None:
    human_request = request()
    created_admission, created = await repository.create_or_replay(
        principal(), human_request, HASH, expiry()
    )
    joined_admission, joined = await repository.create_or_replay(
        principal(), human_request, HASH, expiry()
    )
    conflict_admission, conflict = await repository.create_or_replay(
        principal(), human_request, "b" * 64, expiry()
    )
    assert created_admission == "created"
    assert joined_admission == "joined_pending"
    assert joined.request_id == created.request_id
    assert conflict_admission == "conflict"
    assert conflict.request_id == created.request_id

    result = AskHumanResult(
        requestId=created.request_id,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.APPROVED,
    )
    assert await repository.complete_if_pending(result) is True
    replay_admission, replay = await repository.create_or_replay(
        principal(), human_request, HASH, expiry()
    )
    assert replay_admission == "replayed"
    assert replay.result == result


@pytest.mark.asyncio
async def test_same_key_with_changed_phone_number_conflicts(
    repository: PostgresRequestRepository,
) -> None:
    human_request = request()
    request_hash = AskHumanService._request_hash(human_request)
    created_admission, created = await repository.create_or_replay(
        principal(), human_request, request_hash, expiry()
    )
    changed = human_request.model_copy(update={"phone_number": "+15555550102"})
    conflict_admission, conflict = await repository.create_or_replay(
        principal(), changed, AskHumanService._request_hash(changed), expiry()
    )
    assert created_admission == "created"
    assert conflict_admission == "conflict"
    assert conflict.request_id == created.request_id


@pytest.mark.asyncio
async def test_call_attachment_and_concurrent_terminal_update_have_one_winner(
    repository: PostgresRequestRepository,
) -> None:
    _, created = await repository.create_or_replay(principal(), request(), HASH, expiry())
    assert await repository.attach_call_id(created.request_id, "call-one") is True
    assert await repository.attach_call_id(created.request_id, "call-two") is False

    approved = AskHumanResult(
        requestId=created.request_id,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.APPROVED,
    )
    rejected = AskHumanResult(
        requestId=created.request_id,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.REJECTED,
    )
    winners = await asyncio.gather(
        repository.complete_if_pending(approved),
        repository.complete_if_pending(rejected),
        repository.complete_error_if_pending(
            created.request_id,
            ErrorCode.DEPENDENCY_FAILURE,
            "The call service could not process the request.",
        ),
    )
    assert sorted(winners) == [False, False, True]
    stored = await repository.get(created.request_id)
    assert stored is not None
    assert stored.call_id == "call-one"
    if stored.state is RequestState.FAILED:
        assert stored.result is None
        assert stored.error_code is ErrorCode.DEPENDENCY_FAILURE
    else:
        assert stored.result in (approved, rejected)
        assert stored.error_code is None


@pytest.mark.asyncio
async def test_persisted_state_is_visible_from_a_new_repository(
    repository: PostgresRequestRepository,
    database_url: str,
) -> None:
    _, created = await repository.create_or_replay(principal(), request(), HASH, expiry())
    restarted_pool = PostgresPool(database_url, min_size=1, max_size=1)
    await restarted_pool.open()
    try:
        restarted = PostgresRequestRepository(restarted_pool.pool)
        reloaded = await restarted.get(created.request_id)
        assert reloaded == created
        assert reloaded is not None
        assert reloaded.request.phone_number == "+15555550101"
    finally:
        await restarted_pool.close()


async def test_recognition_claim_has_one_winner_and_survives_restart(
    repository: PostgresRequestRepository,
    database_url: str,
) -> None:
    _, stored = await repository.create_or_replay(principal(), request(), HASH, expiry())
    assert not await repository.claim_recognition(stored.request_id)
    assert await repository.attach_call_id(stored.request_id, "call-id")
    winners = await asyncio.gather(
        repository.claim_recognition(stored.request_id),
        repository.claim_recognition(stored.request_id),
    )
    assert sorted(winners) == [False, True]
    pool = PostgresPool(database_url, min_size=1, max_size=1)
    await pool.open()
    try:
        assert not await PostgresRequestRepository(pool.pool).claim_recognition(stored.request_id)
    finally:
        await pool.close()


async def test_overdue_success_loses_to_expiry_and_returns_stale_call(
    repository: PostgresRequestRepository,
) -> None:
    _, stored = await repository.create_or_replay(
        principal(), request(), HASH, datetime.now(UTC) - timedelta(seconds=1)
    )
    await repository.attach_call_id(stored.request_id, "stale-call")
    assert await repository.pending_count() == 1
    success, expired = await asyncio.gather(
        repository.complete_if_pending(
            AskHumanResult(
                requestId=stored.request_id,
                status=RequestStatus.RESPONDED,
                outcome=Outcome.APPROVED,
            )
        ),
        repository.expire_stale_calls(datetime.now(UTC)),
    )
    assert not success
    assert [item.call_id for item in expired] == ["stale-call"]
    assert await repository.pending_count() == 0


async def test_wrong_kind_success_is_rejected(repository: PostgresRequestRepository) -> None:
    _, stored = await repository.create_or_replay(principal(), request(), HASH, expiry())
    assert not await repository.complete_if_pending(
        AskHumanResult(
            requestId=stored.request_id,
            status=RequestStatus.RESPONDED,
            outcome=Outcome.ANSWERED,
            answer="not an approval",
        )
    )


async def test_success_respects_service_cutoff_before_database_expiry(
    repository: PostgresRequestRepository,
) -> None:
    _, stored = await repository.create_or_replay(principal(), request(), HASH, expiry())
    result = AskHumanResult(
        requestId=stored.request_id,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.APPROVED,
    )
    assert not await repository.complete_if_pending(
        result,
        before=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert await repository.complete_if_pending(result, before=expiry())


@pytest.mark.asyncio
async def test_dependency_error_replays_from_a_new_service_and_repository(
    repository: PostgresRequestRepository,
    database_url: str,
) -> None:
    class FailingGateway(FakeCallAutomationGateway):
        async def create_call(self, request):  # type: ignore[no-untyped-def]
            self.created.append(request)
            raise RuntimeError("sensitive provider detail")

    gateway = FailingGateway()
    clock = FakeClock(datetime.now(tz=UTC))
    human_request = request()
    service = AskHumanService(repository, gateway, clock, FakeTelemetry())

    with pytest.raises(AskMyHumanError) as first:
        await service.ask(principal(), human_request, FakeCancellationSignal())

    restarted_pool = PostgresPool(database_url, min_size=1, max_size=1)
    await restarted_pool.open()
    try:
        restarted_repository = PostgresRequestRepository(restarted_pool.pool)
        restarted_service = AskHumanService(
            restarted_repository,
            gateway,
            clock,
            FakeTelemetry(),
        )
        with pytest.raises(AskMyHumanError) as replay:
            await restarted_service.ask(principal(), human_request, FakeCancellationSignal())
    finally:
        await restarted_pool.close()

    assert replay.value.code is ErrorCode.DEPENDENCY_FAILURE
    assert replay.value.message == "The call service could not process the request."
    assert replay.value.request_id == first.value.request_id
    assert "sensitive provider detail" not in replay.value.message
    assert len(gateway.created) == 1


@pytest.mark.asyncio
async def test_stale_expiry_releases_admission_and_terminal_purge_uses_completion_time(
    repository: PostgresRequestRepository,
) -> None:
    past = datetime.now(tz=UTC) - timedelta(minutes=1)
    _, stale = await repository.create_or_replay(principal(), request(), HASH, past)
    assert await repository.expire_stale(datetime.now(tz=UTC)) == 1
    expired = await repository.get(stale.request_id)
    assert expired is not None
    assert expired.state is RequestState.EXPIRED
    assert expired.result is not None
    assert expired.result.outcome is Outcome.DEADLINE_EXCEEDED

    admission, current = await repository.create_or_replay(
        principal("next"), request(), HASH, expiry()
    )
    assert admission == "created"
    assert await repository.purge_terminal(datetime.now(tz=UTC) + timedelta(hours=24)) == 1
    assert await repository.get(stale.request_id) is None
    assert await repository.get(current.request_id) is not None
