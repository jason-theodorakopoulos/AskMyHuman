"""In-process loops for request expiry and terminal-row retention."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import nullcontext, suppress
from datetime import timedelta
from uuid import uuid4

from ask_my_human.application.ports import (
    CallAutomationGateway,
    CancellationSignal,
    Clock,
    RequestRepository,
    Telemetry,
    TelemetryOperation,
)
from ask_my_human.errors import ErrorCode


class RequestMaintenance:
    def __init__(
        self,
        repository: RequestRepository,
        clock: Clock,
        *,
        gateway: CallAutomationGateway | None = None,
        telemetry: Telemetry | None = None,
        retention_hours: float = 24,
        expiry_interval_seconds: float = 1,
        purge_interval_seconds: float = 3600,
        operation_timeout_seconds: float = 5,
        cleanup_timeout_seconds: float = 1,
    ) -> None:
        if retention_hours <= 0:
            raise ValueError("retention hours must be positive")
        if expiry_interval_seconds <= 0 or purge_interval_seconds <= 0:
            raise ValueError("maintenance intervals must be positive")
        if operation_timeout_seconds <= 0 or cleanup_timeout_seconds <= 0:
            raise ValueError("maintenance timeouts must be positive")
        self._repository = repository
        self._clock = clock
        self._retention = timedelta(hours=retention_hours)
        self._expiry_interval_seconds = expiry_interval_seconds
        self._purge_interval_seconds = purge_interval_seconds
        self._gateway = gateway
        self._telemetry = telemetry
        self._operation_timeout = operation_timeout_seconds
        self._cleanup_timeout = cleanup_timeout_seconds

    async def expire_once(self) -> int:
        async with asyncio.timeout(self._operation_timeout):
            span = (
                self._telemetry.span(TelemetryOperation.REPOSITORY, request_id=uuid4())
                if self._telemetry is not None
                else nullcontext()
            )
            with span:
                if self._telemetry is not None:
                    self._telemetry.set_pending(await self._repository.pending_count() > 0)
                expired = await self._repository.expire_stale_calls(self._clock.now())
        if self._gateway is not None:
            for request in expired:
                if request.call_id is not None:
                    try:
                        async with asyncio.timeout(self._cleanup_timeout):
                            await self._gateway.hang_up(request.call_id)
                    except Exception:
                        if self._telemetry is not None:
                            self._telemetry.dependency_failed(
                                TelemetryOperation.CALLBACK,
                                error_code=ErrorCode.DEPENDENCY_FAILURE,
                            )
        if self._telemetry is not None:
            try:
                async with asyncio.timeout(self._operation_timeout):
                    self._telemetry.set_pending(await self._repository.pending_count() > 0)
            except Exception:
                self._telemetry.dependency_failed(
                    TelemetryOperation.REPOSITORY,
                    error_code=ErrorCode.DEPENDENCY_FAILURE,
                )
        return len(expired)

    async def purge_once(self) -> int:
        async with asyncio.timeout(self._operation_timeout):
            return await self._repository.purge_terminal(self._clock.now() - self._retention)

    async def run_expiry_loop(self, cancellation: CancellationSignal) -> None:
        await self._run(cancellation, self.expire_once, self._expiry_interval_seconds)

    async def run_purge_loop(self, cancellation: CancellationSignal) -> None:
        await self._run(cancellation, self.purge_once, self._purge_interval_seconds)

    async def _run(
        self,
        cancellation: CancellationSignal,
        operation: Callable[[], Awaitable[int]],
        interval_seconds: float,
    ) -> None:
        while not cancellation.cancelled:
            work = asyncio.ensure_future(operation())
            stopped = asyncio.create_task(cancellation.wait())
            try:
                done, _ = await asyncio.wait({work, stopped}, return_when=asyncio.FIRST_COMPLETED)
                if stopped in done:
                    return
                await work
            except Exception:
                if self._telemetry is not None:
                    self._telemetry.dependency_failed(
                        TelemetryOperation.REPOSITORY,
                        error_code=ErrorCode.DEPENDENCY_FAILURE,
                    )
            finally:
                work.cancel()
                stopped.cancel()
                await asyncio.gather(work, stopped, return_exceptions=True)
            if not cancellation.cancelled:
                delay = asyncio.create_task(self._clock.sleep(interval_seconds))
                stopped = asyncio.create_task(cancellation.wait())
                try:
                    await asyncio.wait({delay, stopped}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    delay.cancel()
                    stopped.cancel()
                    with suppress(asyncio.CancelledError):
                        await delay
                    with suppress(asyncio.CancelledError):
                        await stopped
