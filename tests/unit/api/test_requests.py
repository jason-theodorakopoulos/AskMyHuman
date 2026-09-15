import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from support.fakes import FakeAskHumanUseCase

from ask_my_human.api.requests import create_requests_router
from ask_my_human.application.ports import CancellationSignal
from ask_my_human.contracts import AskHumanRequest, AskHumanResult, Outcome, RequestStatus
from ask_my_human.domain.models import Principal
from ask_my_human.errors import AskMyHumanError, ErrorCode

Authenticate = Callable[[Request], Awaitable[Principal]]


async def authenticate(_request: Request) -> Principal:
    return Principal(subject_id="subject", application_id="application")


def app_for(use_case: FakeAskHumanUseCase, auth: Authenticate = authenticate) -> FastAPI:
    app = FastAPI()
    app.include_router(create_requests_router(use_case=use_case, authenticate=auth))
    return app


def request_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "kind": "approval",
        "prompt": "Approve deployment?",
        "idempotencyKey": str(uuid4()),
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_terminal_human_availability_result_returns_200() -> None:
    result = AskHumanResult(
        requestId=uuid4(), status=RequestStatus.EXPIRED, outcome=Outcome.NO_ANSWER
    )
    use_case = FakeAskHumanUseCase(result)

    async with AsyncClient(
        transport=ASGITransport(app=app_for(use_case)), base_url="http://test"
    ) as client:
        response = await client.post("/v1/requests", json=request_body())

    assert response.status_code == 200
    assert response.json() == {
        "requestId": str(result.request_id),
        "status": "expired",
        "outcome": "no_answer",
    }
    assert len(use_case.requests) == 1


@pytest.mark.asyncio
async def test_deployment_settings_are_rejected_before_use_case() -> None:
    use_case = FakeAskHumanUseCase()

    async with AsyncClient(
        transport=ASGITransport(app=app_for(use_case)), base_url="http://test"
    ) as client:
        response = await client.post("/v1/requests", json=request_body(phoneNumber="+15555550100"))

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert response.json()["requestId"] is None
    assert use_case.requests == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (ErrorCode.INVALID_REQUEST, 400),
        (ErrorCode.UNAUTHENTICATED, 401),
        (ErrorCode.FORBIDDEN, 403),
        (ErrorCode.IDEMPOTENCY_CONFLICT, 409),
        (ErrorCode.RATE_LIMITED, 429),
        (ErrorCode.DEPENDENCY_FAILURE, 502),
        (ErrorCode.INTERNAL, 500),
    ],
)
@pytest.mark.asyncio
async def test_application_errors_have_stable_http_mapping(code: ErrorCode, status: int) -> None:
    request_id = uuid4()

    class FailingUseCase(FakeAskHumanUseCase):
        async def ask(
            self,
            principal: Principal,
            request: AskHumanRequest,
            cancellation: CancellationSignal,
        ) -> AskHumanResult:
            self.requests.append((principal, request, cancellation))
            raise AskMyHumanError(code, "safe message", request_id=request_id)

    async with AsyncClient(
        transport=ASGITransport(app=app_for(FailingUseCase())), base_url="http://test"
    ) as client:
        response = await client.post("/v1/requests", json=request_body())

    assert response.status_code == status
    assert response.json() == {
        "requestId": str(request_id),
        "code": code.value,
        "message": "safe message",
        "retryable": code
        in {ErrorCode.RATE_LIMITED, ErrorCode.DEPENDENCY_FAILURE, ErrorCode.INTERNAL},
    }


@pytest.mark.asyncio
async def test_authentication_failure_prevents_use_case_call() -> None:
    use_case = FakeAskHumanUseCase()

    async def reject(_request: Request) -> Principal:
        raise AskMyHumanError(ErrorCode.UNAUTHENTICATED, "Authentication required")

    async with AsyncClient(
        transport=ASGITransport(app=app_for(use_case, reject)), base_url="http://test"
    ) as client:
        response = await client.post("/v1/requests", content=b"not-json")

    assert response.status_code == 401
    assert use_case.requests == []


@pytest.mark.asyncio
async def test_client_disconnect_cancels_service_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = 0

    async def is_disconnected(_request: Request) -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    monkeypatch.setattr(Request, "is_disconnected", is_disconnected)

    class CancellationAwareUseCase(FakeAskHumanUseCase):
        async def ask(
            self,
            principal: Principal,
            request: AskHumanRequest,
            cancellation: CancellationSignal,
        ) -> AskHumanResult:
            self.requests.append((principal, request, cancellation))
            await cancellation.wait()
            return AskHumanResult(
                requestId=request.idempotency_key,
                status=RequestStatus.EXPIRED,
                outcome=Outcome.CANCELLED,
            )

    use_case = CancellationAwareUseCase()
    async with AsyncClient(
        transport=ASGITransport(app=app_for(use_case)), base_url="http://test"
    ) as client:
        response = await client.post("/v1/requests", json=request_body())

    assert response.status_code == 200
    assert response.json()["outcome"] == "cancelled"
    assert use_case.requests[0][2].cancelled is True


@pytest.mark.asyncio
async def test_request_and_response_bodies_are_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive = "SENSITIVE-CONTENT-SENTINEL"
    result = AskHumanResult(
        requestId=uuid4(),
        status=RequestStatus.RESPONDED,
        outcome=Outcome.ANSWERED,
        answer=sensitive,
    )
    caplog.set_level(logging.DEBUG)

    async with AsyncClient(
        transport=ASGITransport(app=app_for(FakeAskHumanUseCase(result))),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/requests", json=request_body(kind="input", prompt=sensitive)
        )

    assert response.status_code == 200
    assert sensitive not in caplog.text
