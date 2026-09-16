"""Sole application composition root and ASGI lifespan.

This module wires settings, telemetry, Azure credentials and clients, the
PostgreSQL pool, the repository, the synchronous service, maintenance loops,
HTTP routers, and the MCP Streamable HTTP app into one FastAPI application.
Feature modules export routers, clients, and implementations; no other module
constructs a second service, pool, or Azure client.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from datetime import UTC, datetime

import httpx
from azure.communication.callautomation.aio import CallAutomationClient
from azure.identity.aio import DefaultAzureCredential
from fastapi import FastAPI, Request
from mcp.server.transport_security import TransportSecuritySettings

from ask_my_human.api.callbacks import create_callbacks_router
from ask_my_human.api.health import create_readiness_router, liveness_router
from ask_my_human.api.oauth_metadata import create_oauth_metadata_router
from ask_my_human.api.requests import create_requests_router
from ask_my_human.application.maintenance import RequestMaintenance
from ask_my_human.application.service import AskHumanService
from ask_my_human.config import Settings
from ask_my_human.domain.models import CallEvent, Principal
from ask_my_human.mcp_adapter.server import create_mcp_server
from ask_my_human.observability import configure_observability
from ask_my_human.persistence.pool import PostgresPool
from ask_my_human.persistence.repository import PostgresRequestRepository
from ask_my_human.security.acs_callback import AcsCallbackTokenValidator
from ask_my_human.security.agent import parse_container_apps_principal
from ask_my_human.telephony.acs_client import AcsCallAutomationGateway
from ask_my_human.telephony.events import parse_callback_event

CLIENT_PRINCIPAL_HEADER = "x-ms-client-principal"


class _SystemClock:
    """Real wall-clock and sleep implementation for the composed runtime."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class _LoopCancellationSignal:
    """Cancellation signal driven by application shutdown."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()

    def cancel(self) -> None:
        self._event.set()


def _parse_callback_events(payload: object) -> list[CallEvent]:
    if not isinstance(payload, list):
        raise ValueError("callback payload must be a list of CloudEvents")
    events: list[CallEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("callback payload entries must be objects")
        parsed = parse_callback_event(item)
        call_event = parsed.call_event
        if call_event is not None:
            events.append(call_event)
    return events


async def _cancel_maintenance(
    signal: _LoopCancellationSignal, tasks: list[asyncio.Task[None]]
) -> None:
    signal.cancel()
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    telemetry = configure_observability()

    async with AsyncExitStack() as stack:
        credential = DefaultAzureCredential()
        stack.push_async_callback(credential.close)
        http_client = httpx.AsyncClient()
        stack.push_async_callback(http_client.aclose)
        call_automation_client = CallAutomationClient(str(settings.acs_endpoint), credential)
        stack.push_async_callback(call_automation_client.close)
        gateway = AcsCallAutomationGateway.from_settings(call_automation_client, settings)
        callback_validator = AcsCallbackTokenValidator(
            http_client, str(settings.acs_callback_audience)
        )

        pool = PostgresPool(settings.database_url.get_secret_value())
        await pool.open()
        stack.push_async_callback(pool.close)
        repository = PostgresRequestRepository(pool.pool)

        clock = _SystemClock()
        service = AskHumanService(
            repository,
            gateway,
            clock,
            telemetry,
            deadline_seconds=settings.deadline_seconds,
            work_cutoff_seconds=settings.work_cutoff_seconds,
            poll_interval_seconds=settings.poll_interval_milliseconds / 1000,
        )
        maintenance = RequestMaintenance(
            repository, clock, retention_hours=settings.retention_hours
        )
        maintenance_signal = _LoopCancellationSignal()
        maintenance_tasks = [
            asyncio.create_task(maintenance.run_expiry_loop(maintenance_signal)),
            asyncio.create_task(maintenance.run_purge_loop(maintenance_signal)),
        ]
        stack.push_async_callback(_cancel_maintenance, maintenance_signal, maintenance_tasks)

        async def authenticate(request: Request) -> Principal:
            encoded_principal = request.headers.get(CLIENT_PRINCIPAL_HEADER)
            return parse_container_apps_principal(
                encoded_principal, settings.authorized_agent_app_ids
            )

        async def validate_callback_token(token: str) -> None:
            await callback_validator.validate("Bearer " + token)

        app.state.settings = settings
        app.state.pool = pool

        app.include_router(liveness_router)
        app.include_router(create_readiness_router(settings, pool.pool))
        app.include_router(create_oauth_metadata_router(settings))
        app.include_router(create_requests_router(use_case=service, authenticate=authenticate))
        app.include_router(
            create_callbacks_router(
                use_case=service,
                validate_token=validate_callback_token,
                parse_events=_parse_callback_events,
            )
        )

        mcp_server = create_mcp_server(service)
        mcp_app = mcp_server.streamable_http_app(
            streamable_http_path="/mcp",
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=list(settings.mcp_allowed_hosts),
                allowed_origins=[],
            ),
            host="0.0.0.0",  # noqa: S104 - ingress and auth are enforced by Container Apps
        )
        app.mount("/", mcp_app)

        await stack.enter_async_context(mcp_server.session_manager.run())

        yield


app = FastAPI(lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
