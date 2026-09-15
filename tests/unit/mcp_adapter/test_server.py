import asyncio
import json
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.context import ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolRequestParams

from ask_my_human.application.ports import CancellationSignal
from ask_my_human.contracts import AskHumanRequest, AskHumanResult, Outcome, RequestStatus
from ask_my_human.domain.models import Principal
from ask_my_human.errors import AskMyHumanError, ErrorCode
from ask_my_human.mcp_adapter.server import (
    ASK_HUMAN_TOOL,
    AskHumanMcpAdapter,
    create_streamable_http_app,
)

ROOT = Path(__file__).resolve().parents[3]
REQUEST_ID = UUID("10000000-0000-4000-8000-000000000001")


def arguments() -> dict[str, str]:
    return {
        "kind": "approval",
        "prompt": "Deploy now?",
        "idempotencyKey": str(REQUEST_ID),
    }


def context() -> ServerRequestContext[object]:
    return cast(ServerRequestContext[object], object())


class RecordingUseCase:
    def __init__(self, result: AskHumanResult | None = None) -> None:
        self.result = result or AskHumanResult(
            requestId=REQUEST_ID,
            status=RequestStatus.RESPONDED,
            outcome=Outcome.APPROVED,
        )
        self.calls: list[tuple[Principal, AskHumanRequest, CancellationSignal]] = []
        self.error: Exception | None = None

    async def ask(
        self,
        principal: Principal,
        request: AskHumanRequest,
        cancellation: CancellationSignal,
    ) -> AskHumanResult:
        self.calls.append((principal, request, cancellation))
        if self.error is not None:
            raise self.error
        return self.result

    async def handle_call_event(self, event: object) -> None:
        del event


@pytest.fixture
def authenticated_agent() -> None:
    token = auth_context_var.set(
        AuthenticatedUser(
            AccessToken(
                token="validated-token",
                client_id="agent-application",
                subject="agent-subject",
                scopes=[],
            )
        )
    )
    try:
        yield
    finally:
        auth_context_var.reset(token)


def test_tool_uses_checked_in_request_and_result_schemas() -> None:
    request_schema = json.loads((ROOT / "schemas/ask-human-request.schema.json").read_text())
    result_schema = json.loads((ROOT / "schemas/ask-human-result.schema.json").read_text())

    assert ASK_HUMAN_TOOL.input_schema == request_schema
    assert ASK_HUMAN_TOOL.output_schema == result_schema


def test_app_factory_exposes_only_streamable_http_mcp_route() -> None:
    app = create_streamable_http_app(RecordingUseCase())

    assert [route.path for route in app.routes] == ["/mcp"]


@pytest.mark.asyncio
async def test_success_maps_authenticated_principal_and_returns_structured_result(
    authenticated_agent: None,
) -> None:
    use_case = RecordingUseCase()
    adapter = AskHumanMcpAdapter(use_case)

    response = await adapter.call_tool(
        context(), CallToolRequestParams(name="ask_human", arguments=arguments())
    )

    assert response.is_error is False
    assert response.structured_content == {
        "requestId": str(REQUEST_ID),
        "status": "responded",
        "outcome": "approved",
        "answer": None,
    }
    assert len(use_case.calls) == 1
    principal, request, _ = use_case.calls[0]
    assert principal == Principal(subject_id="agent-subject", application_id="agent-application")
    assert request.idempotency_key == REQUEST_ID


@pytest.mark.asyncio
async def test_deadline_result_remains_a_success(authenticated_agent: None) -> None:
    use_case = RecordingUseCase(
        AskHumanResult(
            requestId=REQUEST_ID,
            status=RequestStatus.EXPIRED,
            outcome=Outcome.DEADLINE_EXCEEDED,
        )
    )

    response = await AskHumanMcpAdapter(use_case).call_tool(
        context(), CallToolRequestParams(name="ask_human", arguments=arguments())
    )

    assert response.is_error is False
    assert response.structured_content["outcome"] == "deadline_exceeded"


@pytest.mark.asyncio
async def test_invalid_arguments_are_protocol_error_without_dispatch(
    authenticated_agent: None,
) -> None:
    use_case = RecordingUseCase()
    invalid = arguments() | {"unexpected": "value"}

    with pytest.raises(MCPError) as raised:
        await AskHumanMcpAdapter(use_case).call_tool(
            context(), CallToolRequestParams(name="ask_human", arguments=invalid)
        )

    assert raised.value.code == INVALID_PARAMS
    assert use_case.calls == []


@pytest.mark.asyncio
async def test_application_error_is_structured_and_marked_as_error(
    authenticated_agent: None,
) -> None:
    use_case = RecordingUseCase()
    use_case.error = AskMyHumanError(
        ErrorCode.RATE_LIMITED,
        "Another human request is already pending.",
        request_id=REQUEST_ID,
    )

    response = await AskHumanMcpAdapter(use_case).call_tool(
        context(), CallToolRequestParams(name="ask_human", arguments=arguments())
    )

    assert response.is_error is True
    assert response.structured_content == {
        "requestId": str(REQUEST_ID),
        "code": "rate_limited",
        "message": "Another human request is already pending.",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_unexpected_failure_is_sanitized(authenticated_agent: None) -> None:
    use_case = RecordingUseCase()
    use_case.error = RuntimeError("database password leaked")

    response = await AskHumanMcpAdapter(use_case).call_tool(
        context(), CallToolRequestParams(name="ask_human", arguments=arguments())
    )

    assert response.is_error is True
    assert response.structured_content["code"] == "internal"
    assert response.structured_content["message"] == "The human request could not be completed."
    assert "password" not in response.content[0].text


@pytest.mark.asyncio
async def test_transport_cancellation_signals_only_its_dispatch(
    authenticated_agent: None,
) -> None:
    started = asyncio.Event()
    observed = asyncio.Event()

    class WaitingUseCase(RecordingUseCase):
        async def ask(
            self,
            principal: Principal,
            request: AskHumanRequest,
            cancellation: CancellationSignal,
        ) -> AskHumanResult:
            self.calls.append((principal, request, cancellation))
            started.set()
            await cancellation.wait()
            observed.set()
            raise asyncio.CancelledError

    use_case = WaitingUseCase()
    adapter = AskHumanMcpAdapter(use_case)
    dispatch = asyncio.create_task(
        adapter.call_tool(
            context(),
            CallToolRequestParams(
                name="ask_human", arguments=arguments() | {"idempotencyKey": str(uuid4())}
            ),
        )
    )
    await started.wait()

    dispatch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await dispatch

    assert observed.is_set()
    assert len(use_case.calls) == 1
