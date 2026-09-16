"""Sole application composition root and lifespan.

Owned only by the application integrator. Feature owners export a router,
server, client, pool, or implementation and do not edit this module.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

import httpx
from azure.communication.callautomation.aio import CallAutomationClient
from azure.identity.aio import DefaultAzureCredential
from fastapi import FastAPI, Request
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Mount

from ask_my_human.api.callbacks import create_callbacks_router
from ask_my_human.api.health import create_readiness_router, liveness_router
from ask_my_human.api.oauth_metadata import create_oauth_metadata_router
from ask_my_human.api.requests import create_requests_router
from ask_my_human.application.maintenance import RequestMaintenance
from ask_my_human.application.ports import Clock
from ask_my_human.application.service import AskHumanService
from ask_my_human.config import Settings
from ask_my_human.domain.models import CallEvent, Principal
from ask_my_human.errors import AskMyHumanError, ErrorCode
from ask_my_human.mcp_adapter.server import create_mcp_server
from ask_my_human.observability import configure_observability
from ask_my_human.persistence.pool import PostgresPool
from ask_my_human.persistence.repository import PostgresRequestRepository
from ask_my_human.security.acs_callback import AcsCallbackTokenValidator
from ask_my_human.security.agent import parse_container_apps_principal
from ask_my_human.telephony.acs_client import AcsCallAutomationGateway
from ask_my_human.telephony.events import parse_callback_event

CLIENT_PRINCIPAL_HEADER = "x-ms-client-principal"


class SystemClock:
    """Wall-clock time source for production use."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def _parse_callback_events(payload: object) -> list[CallEvent]:
    if not isinstance(payload, list):
        raise ValueError("callback payload must be a list of events")
    events: list[CallEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("each callback event must be an object")
        acs_event = parse_callback_event(item)
        call_event = acs_event.call_event
        if call_event is not None:
            events.append(call_event)
    return events


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Acquire resources, compose routes once, and release resources on shutdown.

    ASGI hosts (Uvicorn in production, ``TestClient`` in tests) enter this
    context exactly once per running application instance, so resources such
    as the connection pool, ACS client, and maintenance tasks are always
    created and torn down in matching pairs. The ``app.state.composed`` guard
    below only protects route/mount registration against being duplicated if
    a caller re-enters the lifespan on the same ``FastAPI`` instance; it is
    not a substitute for creating a fresh app per run.
    """
    settings = Settings.from_env()
    telemetry = configure_observability()

    credential = DefaultAzureCredential()
    call_automation_client = CallAutomationClient(str(settings.acs_endpoint), credential)
    gateway = AcsCallAutomationGateway.from_settings(call_automation_client, settings)

    http_client = httpx.AsyncClient(timeout=5.0)
    token_validator = AcsCallbackTokenValidator(http_client, str(settings.acs_callback_audience))

    pool = PostgresPool(settings.database_url.get_secret_value())
    await pool.open()
    repository = PostgresRequestRepository(pool.pool)

    clock: Clock = SystemClock()
    service = AskHumanService(
        repository,
        gateway,
        clock,
        telemetry,
        deadline_seconds=settings.deadline_seconds,
        work_cutoff_seconds=settings.work_cutoff_seconds,
        poll_interval_seconds=settings.poll_interval_milliseconds / 1000,
    )
    maintenance = RequestMaintenance(repository, clock, retention_hours=settings.retention_hours)

    class _MaintenanceCancellation:
        def __init__(self) -> None:
            self._event = asyncio.Event()

        @property
        def cancelled(self) -> bool:
            return self._event.is_set()

        async def wait(self) -> None:
            await self._event.wait()

        def cancel(self) -> None:
            self._event.set()

    maintenance_cancellation = _MaintenanceCancellation()
    expiry_task = asyncio.create_task(maintenance.run_expiry_loop(maintenance_cancellation))
    purge_task = asyncio.create_task(maintenance.run_purge_loop(maintenance_cancellation))

    async def authenticate(request: Request) -> Principal:
        encoded_principal = request.headers.get(CLIENT_PRINCIPAL_HEADER)
        return parse_container_apps_principal(encoded_principal, settings.authorized_agent_app_ids)

    bearer_prefix = "Bearer"

    async def validate_token(token: str) -> None:
        try:
            await token_validator.validate(f"{bearer_prefix} {token}")
        except AskMyHumanError:
            raise
        except Exception as error:
            raise AskMyHumanError(ErrorCode.UNAUTHENTICATED, "Invalid callback token") from error

    already_composed = getattr(app.state, "composed", False)
    if not already_composed:
        app.include_router(liveness_router)
        app.include_router(create_readiness_router(settings, pool.pool))
        app.include_router(create_oauth_metadata_router(settings))
        app.include_router(create_requests_router(use_case=service, authenticate=authenticate))
        app.include_router(
            create_callbacks_router(
                use_case=service,
                validate_token=validate_token,
                parse_events=_parse_callback_events,
            )
        )

    mcp_server = create_mcp_server(service)
    transport_security = TransportSecuritySettings(
        allowed_hosts=list(settings.mcp_allowed_hosts),
    )
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=transport_security,
    )
    if already_composed:
        app.router.routes = [route for route in app.router.routes if not isinstance(route, Mount)]
    app.mount("/", mcp_app)
    app.state.composed = True

    try:
        async with mcp_server.session_manager.run():
            yield
    finally:
        maintenance_cancellation.cancel()
        for task in (expiry_task, purge_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await call_automation_client.close()
        await credential.close()
        await http_client.aclose()
        await pool.close()


def create_app() -> FastAPI:
    """Compose the sole ASGI application for Ask My Human."""
    return FastAPI(lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)


app = create_app()
