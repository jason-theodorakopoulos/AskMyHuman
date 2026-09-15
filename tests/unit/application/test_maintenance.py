from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from support.fakes import FakeCancellationSignal, FakeClock, FakeRequestRepository

from ask_my_human.application.maintenance import RequestMaintenance
from ask_my_human.contracts import (
    AskHumanRequest,
    AskHumanResult,
    Outcome,
    RequestKind,
    RequestStatus,
)
from ask_my_human.domain.models import Principal


async def add_request(
    repository: FakeRequestRepository,
    clock: FakeClock,
    *,
    terminal: bool = False,
    age: timedelta = timedelta(),
) -> AskHumanResult | None:
    request = AskHumanRequest(
        kind=RequestKind.APPROVAL,
        prompt="Deploy?",
        idempotencyKey=uuid4(),
    )
    _, stored = await repository.create_or_replay(
        Principal("subject", "app"), request, "hash", clock.now()
    )
    repository.requests[stored.request_id] = replace(stored, created_at=clock.now() - age)
    if not terminal:
        return None
    result = AskHumanResult(
        requestId=stored.request_id,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.APPROVED,
    )
    await repository.complete_if_pending(result)
    return result


@pytest.mark.asyncio
async def test_expiry_passes_are_idempotent() -> None:
    repository = FakeRequestRepository()
    clock = FakeClock()
    await add_request(repository, clock)
    maintenance = RequestMaintenance(repository, clock)
    assert await maintenance.expire_once() == 1
    assert await maintenance.expire_once() == 0


@pytest.mark.asyncio
async def test_purge_removes_only_terminal_rows_older_than_retention() -> None:
    repository = FakeRequestRepository()
    clock = FakeClock()
    old_result = await add_request(repository, clock, terminal=True, age=timedelta(hours=25))
    recent_result = await add_request(repository, clock, terminal=True, age=timedelta(hours=23))
    await add_request(repository, clock, age=timedelta(hours=25))
    maintenance = RequestMaintenance(repository, clock)
    assert await maintenance.purge_once() == 1
    assert old_result is not None and old_result.request_id not in repository.requests
    assert recent_result is not None and recent_result.request_id in repository.requests
    assert len(repository.requests) == 2


@pytest.mark.asyncio
async def test_loops_stop_after_cancellation() -> None:
    class CancellingClock(FakeClock):
        async def sleep(self, seconds: float) -> None:
            await super().sleep(seconds)
            cancellation.cancel()

    repository = FakeRequestRepository()
    cancellation = FakeCancellationSignal()
    maintenance = RequestMaintenance(
        repository,
        CancellingClock(),
        expiry_interval_seconds=2,
        purge_interval_seconds=3,
    )
    await maintenance.run_expiry_loop(cancellation)
    assert cancellation.cancelled is True
