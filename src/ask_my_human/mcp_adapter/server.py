"""Thin MCP Streamable HTTP adapter for the ask-human use case."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from pydantic import ValidationError
from starlette.applications import Starlette

from ask_my_human.application.ports import AskHumanUseCase
from ask_my_human.contracts import AskHumanRequest, AskHumanResult, ExecutionError
from ask_my_human.domain.models import Principal
from ask_my_human.errors import AskMyHumanError, ErrorCode

logger = logging.getLogger(__name__)


class _CancellationSignal:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()

    def cancel(self) -> None:
        self._event.set()


def _schema(model: type[AskHumanRequest] | type[AskHumanResult]) -> dict[str, Any]:
    schema = model.model_json_schema(by_alias=True)
    if model is AskHumanResult:
        schema["oneOf"] = [
            {
                "properties": {
                    "status": {"const": "responded"},
                    "outcome": {"enum": ["approved", "rejected"]},
                    "answer": {"type": "null"},
                }
            },
            {
                "properties": {
                    "status": {"const": "responded"},
                    "outcome": {"const": "answered"},
                    "answer": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 4000,
                        "pattern": r"\S",
                    },
                },
                "required": ["answer"],
            },
            {
                "properties": {
                    "status": {"const": "expired"},
                    "outcome": {
                        "enum": [
                            "no_answer",
                            "busy",
                            "declined",
                            "disconnected",
                            "cancelled",
                            "deadline_exceeded",
                        ]
                    },
                    "answer": {"type": "null"},
                }
            },
        ]
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


ASK_HUMAN_TOOL = Tool(
    name="ask_human",
    description="Ask the authenticated agent's human for approval or text input by phone.",
    input_schema=_schema(AskHumanRequest),
    output_schema=_schema(AskHumanResult),
)


class AskHumanMcpAdapter:
    def __init__(self, use_case: AskHumanUseCase) -> None:
        self._use_case = use_case

    async def list_tools(
        self,
        context: ServerRequestContext[Any],
        params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        del context, params
        return ListToolsResult(tools=[ASK_HUMAN_TOOL])

    async def call_tool(
        self,
        context: ServerRequestContext[Any],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        del context
        if params.name != ASK_HUMAN_TOOL.name:
            raise MCPError(code=METHOD_NOT_FOUND, message=f"Unknown tool: {params.name}")

        try:
            request = AskHumanRequest.model_validate(params.arguments or {})
        except ValidationError as exception:
            fields = sorted(
                {".".join(str(part) for part in item["loc"]) for item in exception.errors()}
            )
            raise MCPError(
                code=INVALID_PARAMS,
                message="Invalid ask_human arguments",
                data={"fields": fields},
            ) from exception

        try:
            principal = self._authenticated_principal()
            result = await self._dispatch(principal, request)
        except AskMyHumanError as exception:
            return self._error_result(
                ExecutionError(
                    requestId=exception.request_id,
                    code=exception.code,
                    message=exception.message,
                    retryable=exception.retryable,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ask_human failed after dispatch")
            return self._error_result(
                ExecutionError(
                    requestId=request.idempotency_key,
                    code=ErrorCode.INTERNAL,
                    message="The human request could not be completed.",
                    retryable=True,
                )
            )

        structured = result.model_dump(mode="json", by_alias=True)
        return CallToolResult(
            content=[TextContent(type="text", text=f"Human request {result.outcome.value}.")],
            structured_content=structured,
        )

    async def _dispatch(
        self,
        principal: Principal,
        request: AskHumanRequest,
    ) -> AskHumanResult:
        cancellation = _CancellationSignal()
        service_task = asyncio.create_task(self._use_case.ask(principal, request, cancellation))
        try:
            return await asyncio.shield(service_task)
        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            if current_task is None or current_task.cancelling() == 0:
                raise
            cancellation.cancel()
            with anyio.CancelScope(shield=True):
                with suppress(asyncio.CancelledError, Exception):
                    await service_task
            raise

    @staticmethod
    def _authenticated_principal() -> Principal:
        token = get_access_token()
        if token is None or token.subject is None:
            raise AskMyHumanError(
                ErrorCode.UNAUTHENTICATED,
                "An authenticated agent identity is required.",
            )
        return Principal(subject_id=token.subject, application_id=token.client_id)

    @staticmethod
    def _error_result(error: ExecutionError) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text=error.message)],
            structured_content=error.model_dump(mode="json", by_alias=True),
            is_error=True,
        )


def create_mcp_server(use_case: AskHumanUseCase) -> Server[Any]:
    """Create the MCP server that dispatches directly to the application use case."""
    adapter = AskHumanMcpAdapter(use_case)
    return Server(
        "ask-my-human",
        on_list_tools=adapter.list_tools,
        on_call_tool=adapter.call_tool,
    )


def create_streamable_http_app(
    use_case: AskHumanUseCase,
    *,
    transport_security: TransportSecuritySettings | None = None,
    host: str = "127.0.0.1",
) -> Starlette:
    """Create the Streamable HTTP ASGI application mounted at ``/mcp``."""
    return create_mcp_server(use_case).streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=transport_security,
        host=host,
    )
