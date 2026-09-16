"""Authenticated ACS callback HTTP adapter."""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from json import JSONDecodeError
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response

from ask_my_human.application.ports import AskHumanUseCase, Telemetry, TelemetryOperation
from ask_my_human.contracts import ExecutionError
from ask_my_human.domain.models import CallEvent
from ask_my_human.errors import AskMyHumanError, ErrorCode

CallbackTokenValidator = Callable[[str], Awaitable[None]]
CallbackEventParser = Callable[[object], Sequence[CallEvent]]

_ERROR_STATUS = {
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.DEPENDENCY_FAILURE: 502,
    ErrorCode.INTERNAL: 500,
}


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


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator == "" or scheme.lower() != "bearer" or not token.strip():
        raise AskMyHumanError(ErrorCode.UNAUTHENTICATED, "Valid callback token required")
    return token.strip()


def create_callbacks_router(
    *,
    use_case: AskHumanUseCase,
    validate_token: CallbackTokenValidator,
    parse_events: CallbackEventParser,
    telemetry: Telemetry | None = None,
) -> APIRouter:
    """Create an ACS callback router using supplied security and parser functions."""

    router = APIRouter()

    @router.post("/v1/callbacks/acs", status_code=200)
    async def receive_callback(request: Request) -> Response:
        received_at = datetime.now(UTC)
        delivery_id = uuid4()
        try:
            await validate_token(_bearer_token(request))
            payload = await request.json()
            events = parse_events(payload)
            for event in events:
                await use_case.handle_call_event(event)
            if telemetry is not None:
                for event in events:
                    if event.call_id and event.event_id:
                        telemetry.record(
                            operation=TelemetryOperation.CALLBACK_ACCEPTED,
                            request_id=event.request_id,
                            call_id=event.call_id,
                            event_id=event.event_id,
                            delivery_id=delivery_id,
                            received_at=received_at,
                        )
            return Response(status_code=200)
        except (JSONDecodeError, ValidationError, ValueError, TypeError):
            return _error_response(
                AskMyHumanError(ErrorCode.INVALID_REQUEST, "Callback body is invalid")
            )
        except AskMyHumanError as error:
            return _error_response(error)
        except Exception:
            return _error_response(AskMyHumanError(ErrorCode.INTERNAL, "Internal service error"))

    return router
