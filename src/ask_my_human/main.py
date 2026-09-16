"""Sole ASGI composition root: settings, adapters, routes, and lifespan ownership."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from azure.communication.callautomation.aio import CallAutomationClient
from azure.identity.aio import DefaultAzureCredential
from fastapi import FastAPI, Request
from mcp.server.transport_security import TransportSecuritySettings

from ask_my_human.api.callbacks import create_callbacks_router
from ask_my_human.api.health import PoolState, create_readiness_router, liveness_router
from ask_my_human.api.oauth_metadata import create_oauth_metadata_router
from ask_my_human.api.requests import create_requests_router
from ask_my_human.application.maintenance import RequestMaintenance
from ask_my_human.application.ports import AskHumanUseCase
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

PRINCIPAL_HEADER = "x-ms-client-principal"

_cached_app: FastAPI | None = None

if TYPE_CHECKING:
    # Declared for readers and type checkers; built on first access by __getattr__.
    app: FastAPI


class PoolLifecycle(Protocol):
    """Pool surface the composition root opens and closes."""

    async def open(self) -> None: ...

    async def close(self) -> None: ...


class SystemClock:
    """Wall-clock and sleep implementation for the deployed process."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class ShutdownSignal:
    """Cancellation signal that maintenance loops observe during shutdown."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()

    def cancel(self) -> None:
        self._event.set()


@dataclass(slots=True)
class ApplicationComponents:
    """Everything the ASGI application needs, built once per process."""

    settings: Settings
    pool: PoolLifecycle
    pool_state: PoolState
    use_case: AskHumanUseCase
    maintenance: RequestMaintenance
    validate_callback_token: Callable[[str], Awaitable[None]]
    # Client cleanups in shutdown order; the pool closes before them.
    closers: tuple[Callable[[], Awaitable[None]], ...] = field(default_factory=tuple)


def parse_callback_events(payload: object) -> Sequence[CallEvent]:
    """Map an ACS CloudEvent batch onto the domain events the service handles."""
    if not isinstance(payload, list):
        raise ValueError("callback payload must be a CloudEvent array")
    events: list[CallEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("callback payload must contain CloudEvent objects")
        call_event = parse_callback_event(item).call_event
        if call_event is not None:
            events.append(call_event)
    return events


def load_settings() -> Settings:
    """Read every setting from the process environment exactly once."""
    return Settings()  # type: ignore[call-arg]


def build_components(settings: Settings) -> ApplicationComponents:
    """Construct the deployed adapters without performing any network calls."""
    telemetry = configure_observability()
    clock = SystemClock()

    credential = DefaultAzureCredential()
    acs_client = CallAutomationClient(str(settings.acs_endpoint), credential)
    gateway = AcsCallAutomationGateway.from_settings(acs_client, settings)

    pool = PostgresPool(settings.database_url.get_secret_value())
    repository = PostgresRequestRepository(pool.pool)

    service = AskHumanService(
        repository,
        gateway,
        clock,
        telemetry,
        deadline_seconds=settings.deadline_seconds,
        work_cutoff_seconds=settings.work_cutoff_seconds,
        poll_interval_seconds=settings.poll_interval_milliseconds / 1000,
    )
    # The expiry and purge cadences stay at the RequestMaintenance defaults of one second
    # and one hour; only the retention window is operator-configurable.
    maintenance = RequestMaintenance(
        repository,
        clock,
        retention_hours=settings.retention_hours,
    )

    http_client = httpx.AsyncClient()
    validator = AcsCallbackTokenValidator(http_client, str(settings.acs_callback_audience))

    async def validate_callback_token(token: str) -> None:
        # The router forwards the bare token; the validator owns scheme parsing.
        await validator.validate(" ".join(("Bearer", token)))

    return ApplicationComponents(
        settings=settings,
        pool=pool,
        pool_state=pool.pool,
        use_case=service,
        maintenance=maintenance,
        validate_callback_token=validate_callback_token,
        closers=(acs_client.close, credential.close, http_client.aclose),
    )


def create_app(components: ApplicationComponents | None = None) -> FastAPI:
    """Compose one FastAPI application that also serves the MCP transport."""
    resolved = components if components is not None else build_components(load_settings())
    settings = resolved.settings

    mcp_server = create_mcp_server(resolved.use_case)
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(settings.mcp_allowed_hosts),
            allowed_origins=[f"https://{host}" for host in settings.mcp_allowed_hosts],
        ),
    )

    async def authenticate(request: Request) -> Principal:
        return parse_container_apps_principal(
            request.headers.get(PRINCIPAL_HEADER),
            settings.authorized_agent_app_ids,
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        shutdown = ShutdownSignal()
        async with AsyncExitStack() as stack:
            # Register client cleanup before opening the pool so a failed open leaks nothing.
            stack.push_async_callback(_close_all, resolved.closers)
            await resolved.pool.open()
            stack.push_async_callback(resolved.pool.close)
            await stack.enter_async_context(mcp_server.session_manager.run())

            maintenance_tasks = [
                asyncio.create_task(resolved.maintenance.run_expiry_loop(shutdown)),
                asyncio.create_task(resolved.maintenance.run_purge_loop(shutdown)),
            ]
            stack.push_async_callback(_stop_tasks, shutdown, maintenance_tasks)
            yield

    app = FastAPI(
        title="Ask My Human",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.include_router(liveness_router)
    app.include_router(create_readiness_router(settings, resolved.pool_state))
    app.include_router(create_oauth_metadata_router(settings))
    app.include_router(
        create_requests_router(use_case=resolved.use_case, authenticate=authenticate)
    )
    app.include_router(
        create_callbacks_router(
            use_case=resolved.use_case,
            validate_token=resolved.validate_callback_token,
            parse_events=parse_callback_events,
        )
    )
    # Mount last so the catch-all MCP transport never shadows an HTTP route.
    app.mount("/", mcp_app)
    return app


async def _close_all(closers: Sequence[Callable[[], Awaitable[None]]]) -> None:
    failures: list[Exception] = []
    for close in closers:
        try:
            await close()
        except Exception as failure:  # Close every remaining client before reporting.
            failures.append(failure)
    if failures:
        raise ExceptionGroup("client shutdown failed", failures)


async def _stop_tasks(shutdown: ShutdownSignal, tasks: Sequence[asyncio.Task[None]]) -> None:
    shutdown.cancel()
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


def __getattr__(name: str) -> Any:
    # Build the deployed application lazily and once, so importing needs no environment
    # and repeated access never creates a second set of clients.
    global _cached_app
    if name == "app":
        if _cached_app is None:
            _cached_app = create_app()
        return _cached_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
