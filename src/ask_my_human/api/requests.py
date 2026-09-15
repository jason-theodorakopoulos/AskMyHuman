"""Synchronous HTTP request adapter."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from json import JSONDecodeError

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from ask_my_human.application.ports import AskHumanUseCase
from ask_my_human.contracts import AskHumanRequest, AskHumanResult, ExecutionError
from ask_my_human.domain.models import Principal
from ask_my_human.errors import AskMyHumanError, ErrorCode

AgentAuthenticator = Callable[[Request], Awaitable[Principal]]

_ERROR_STATUS = {
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.DEPENDENCY_FAILURE: 502,
    ErrorCode.INTERNAL: 500,
}
_DISCONNECT_POLL_SECONDS = 0.05


class RequestCancellationSignal:
    """Cancellation signal driven by the client connection state."""

    def __init__(self, request: Request) -> None:
        self._request = request
        self._cancelled = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    async def wait(self) -> None:
        await self._cancelled.wait()

    async def watch(self) -> None:
        while not await self._request.is_disconnected():
            await asyncio.sleep(_DISCONNECT_POLL_SECONDS)
        self._cancelled.set()


def _error_response(error: AskMyHumanError) -> JSONResponse:
    body = ExecutionError(
        requestId=error.request_id,
        code=error.code,
        message=error.message,
        retryable=error.retryable,
    )
    return JSONResponse(
        status_code=_ERROR_STATUS[error.code],
        content=body.model_dump(mode="json", by_alias=True),
    )


def _invalid_request_response() -> JSONResponse:
    return _error_response(AskMyHumanError(ErrorCode.INVALID_REQUEST, "Request body is invalid"))


def create_requests_router(
    *,
    use_case: AskHumanUseCase,
    authenticate: AgentAuthenticator,
) -> APIRouter:
    """Create a request router using composition-root supplied dependencies."""

    router = APIRouter()

    @router.post("/v1/requests", response_model=AskHumanResult)
    async def create_request(request: Request) -> JSONResponse:
        cancellation: RequestCancellationSignal | None = None
        watcher: asyncio.Task[None] | None = None
        try:
            principal = await authenticate(request)
            payload = await request.json()
            ask_request = AskHumanRequest.model_validate(payload)
            cancellation = RequestCancellationSignal(request)
            watcher = asyncio.create_task(cancellation.watch())
            result = await use_case.ask(principal, ask_request, cancellation)
            return JSONResponse(
                status_code=200,
                content=result.model_dump(mode="json", by_alias=True, exclude_none=True),
            )
        except (JSONDecodeError, ValidationError):
            return _invalid_request_response()
        except AskMyHumanError as error:
            return _error_response(error)
        except Exception:
            return _error_response(AskMyHumanError(ErrorCode.INTERNAL, "Internal service error"))
        finally:
            if watcher is not None:
                watcher.cancel()
                with suppress(asyncio.CancelledError):
                    await watcher

    return router
