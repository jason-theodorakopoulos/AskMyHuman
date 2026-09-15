"""Process liveness and dependency readiness routes."""

from typing import Protocol

from fastapi import APIRouter, Response, status

from ask_my_human.config import Settings


class PoolState(Protocol):
    @property
    def closed(self) -> bool: ...


liveness_router = APIRouter()


@liveness_router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


def create_readiness_router(settings: Settings | None, pool: PoolState) -> APIRouter:
    router = APIRouter()

    @router.get("/health/ready")
    async def readiness(response: Response) -> dict[str, str]:
        try:
            ready = settings is not None and not pool.closed
        except Exception:
            ready = False

        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "unavailable"}
        return {"status": "ready"}

    return router
