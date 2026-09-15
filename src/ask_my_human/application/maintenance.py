"""In-process loops for request expiry and terminal-row retention."""

from collections.abc import Awaitable, Callable
from datetime import timedelta

from ask_my_human.application.ports import CancellationSignal, Clock, RequestRepository


class RequestMaintenance:
    def __init__(
        self,
        repository: RequestRepository,
        clock: Clock,
        *,
        retention_hours: float = 24,
        expiry_interval_seconds: float = 1,
        purge_interval_seconds: float = 3600,
    ) -> None:
        if retention_hours <= 0:
            raise ValueError("retention hours must be positive")
        if expiry_interval_seconds <= 0 or purge_interval_seconds <= 0:
            raise ValueError("maintenance intervals must be positive")
        self._repository = repository
        self._clock = clock
        self._retention = timedelta(hours=retention_hours)
        self._expiry_interval_seconds = expiry_interval_seconds
        self._purge_interval_seconds = purge_interval_seconds

    async def expire_once(self) -> int:
        return await self._repository.expire_stale(self._clock.now())

    async def purge_once(self) -> int:
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
            await operation()
            if not cancellation.cancelled:
                await self._clock.sleep(interval_seconds)
