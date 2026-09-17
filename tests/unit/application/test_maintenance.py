import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from support.fakes import (
    FakeCallAutomationGateway,
    FakeCancellationSignal,
    FakeClock,
    FakeRequestRepository,
    FakeTelemetry,
)

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
        phoneNumber="+15555550101",
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


async def test_expiry_cleans_up_restart_calls_and_reconciles_pending() -> None:
    repository = FakeRequestRepository()
    clock = FakeClock()
    await add_request(repository, clock)
    stored = next(iter(repository.requests.values()))
    await repository.attach_call_id(stored.request_id, "stale-call")
    telemetry = FakeTelemetry()
    gateway = FakeCallAutomationGateway()
    maintenance = RequestMaintenance(repository, clock, gateway=gateway, telemetry=telemetry)
    assert await maintenance.expire_once() == 1
    assert gateway.hung_up == ["stale-call"]
    assert telemetry.pending == [True, False]
    assert await maintenance.expire_once() == 0
    assert gateway.hung_up == ["stale-call"]


async def test_expiry_loop_recovers_from_transient_failure() -> None:
    cancellation = FakeCancellationSignal()

    class RecoveringRepository(FakeRequestRepository):
        attempts = 0

        async def expire_stale_calls(self, now):  # type: ignore[no-untyped-def]
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("private connection detail")
            cancellation.cancel()
            return await super().expire_stale_calls(now)

    repository = RecoveringRepository()
    telemetry = FakeTelemetry()
    maintenance = RequestMaintenance(repository, FakeClock(), telemetry=telemetry)
    await maintenance.run_expiry_loop(cancellation)
    assert repository.attempts == 2
    assert len(telemetry.failures) == 1


async def test_expiry_loop_propagates_task_cancellation() -> None:
    started = asyncio.Event()

    class StalledRepository(FakeRequestRepository):
        async def expire_stale_calls(self, now):  # type: ignore[no-untyped-def]
            started.set()
            await asyncio.Event().wait()
            return []

    maintenance = RequestMaintenance(StalledRepository(), FakeClock())
    work = asyncio.create_task(maintenance.run_expiry_loop(FakeCancellationSignal()))
    await started.wait()
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work


async def test_stalled_restart_hangup_is_bounded() -> None:
    class StalledGateway(FakeCallAutomationGateway):
        async def hang_up(self, call_id: str) -> None:
            await asyncio.Event().wait()

    repository = FakeRequestRepository()
    clock = FakeClock()
    await add_request(repository, clock)
    stored = next(iter(repository.requests.values()))
    await repository.attach_call_id(stored.request_id, "stale-call")
    telemetry = FakeTelemetry()
    maintenance = RequestMaintenance(
        repository,
        clock,
        gateway=StalledGateway(),
        telemetry=telemetry,
        cleanup_timeout_seconds=0.01,
    )
    assert await asyncio.wait_for(maintenance.expire_once(), 0.2) == 1
    assert telemetry.pending[-1] is False
    assert len(telemetry.failures) == 1


async def test_post_expiry_gauge_failure_cannot_skip_call_cleanup() -> None:
    class FailingGaugeRepository(FakeRequestRepository):
        counts = 0

        async def pending_count(self) -> int:
            self.counts += 1
            if self.counts == 2:
                raise OSError("database unavailable")
            return await super().pending_count()

    repository = FailingGaugeRepository()
    clock = FakeClock()
    await add_request(repository, clock)
    stored = next(iter(repository.requests.values()))
    await repository.attach_call_id(stored.request_id, "stale-call")
    gateway = FakeCallAutomationGateway()
    telemetry = FakeTelemetry()
    maintenance = RequestMaintenance(repository, clock, gateway=gateway, telemetry=telemetry)
    assert await maintenance.expire_once() == 1
    assert gateway.hung_up == ["stale-call"]
    assert len(telemetry.failures) == 1
    assert await maintenance.expire_once() == 0
    assert telemetry.pending[-1] is False
