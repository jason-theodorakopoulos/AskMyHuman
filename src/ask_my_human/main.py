"""Sole ASGI composition root for the AskMyHuman service."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from azure.communication.callautomation.aio import CallAutomationClient
from azure.identity.aio import DefaultAzureCredential
from fastapi import FastAPI, Request
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from ask_my_human.api.callbacks import create_callbacks_router
from ask_my_human.api.health import create_readiness_router, liveness_router
from ask_my_human.api.oauth_metadata import create_oauth_metadata_router
from ask_my_human.api.requests import create_requests_router
from ask_my_human.application.maintenance import RequestMaintenance
from ask_my_human.application.ports import (
    AskHumanUseCase,
    CallAutomationGateway,
    CancellationSignal,
    RequestRepository,
    Telemetry,
)
from ask_my_human.application.service import AskHumanService
from ask_my_human.config import Settings
from ask_my_human.contracts import AskHumanRequest, AskHumanResult
from ask_my_human.domain.models import CallEvent, Principal
from ask_my_human.errors import AskMyHumanError, ErrorCode
from ask_my_human.mcp_adapter.server import create_streamable_http_app
from ask_my_human.observability import AzureMonitorTelemetry, configure_observability
from ask_my_human.persistence.pool import PostgresPool
from ask_my_human.persistence.repository import PostgresRequestRepository
from ask_my_human.security.acs_callback import AcsCallbackTokenValidator
from ask_my_human.security.agent import parse_container_apps_principal
from ask_my_human.telephony.acs_client import AcsCallAutomationGateway
from ask_my_human.telephony.events import parse_callback_event

logger = logging.getLogger(__name__)

CLIENT_PRINCIPAL_HEADER = "x-ms-client-principal"
CONNECTION_STRING_VARIABLE = "APPLICATIONINSIGHTS_CONNECTION_STRING"

CallbackTokenValidator = Callable[[str], Awaitable[None]]


class SystemClock:
    """Production clock backed by wall time and the running event loop."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass(frozen=True, slots=True)
class Runtime:
    """External resources owned by exactly one application lifespan."""

    pool: PostgresPool
    repository: RequestRepository
    gateway: CallAutomationGateway
    telemetry: Telemetry
    validate_callback_token: CallbackTokenValidator
    close: Callable[[], Awaitable[None]]


RuntimeFactory = Callable[[Settings], Awaitable[Runtime]]


class _LifespanCancellation:
    """Cancellation signal that shutdown sets for the maintenance loops."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()

    def cancel(self) -> None:
        self._event.set()


class _UseCaseSlot:
    """Late-bound use case so routers can be built before startup."""

    def __init__(self) -> None:
        self._delegate: AskHumanUseCase | None = None

    def bind(self, delegate: AskHumanUseCase) -> None:
        self._delegate = delegate

    def unbind(self) -> None:
        self._delegate = None

    def _require(self) -> AskHumanUseCase:
        if self._delegate is None:
            raise AskMyHumanError(
                ErrorCode.DEPENDENCY_FAILURE,
                "The service is not ready to accept requests.",
            )
        return self._delegate

    async def ask(
        self,
        principal: Principal,
        request: AskHumanRequest,
        cancellation: CancellationSignal,
    ) -> AskHumanResult:
        return await self._require().ask(principal, request, cancellation)

    async def handle_call_event(self, event: CallEvent) -> None:
        await self._require().handle_call_event(event)


class _CallbackValidatorSlot:
    """Late-bound ACS callback token validator owned by the lifespan."""

    def __init__(self) -> None:
        self._validate: CallbackTokenValidator | None = None

    def bind(self, validate: CallbackTokenValidator) -> None:
        self._validate = validate

    def unbind(self) -> None:
        self._validate = None

    async def validate(self, token: str) -> None:
        if self._validate is None:
            raise AskMyHumanError(
                ErrorCode.DEPENDENCY_FAILURE,
                "Callback validation is unavailable.",
            )
        await self._validate(token)


class _PoolSlot:
    """Readiness view over the pool that only exists while the lifespan runs."""

    def __init__(self) -> None:
        self._pool: PostgresPool | None = None

    def bind(self, pool: PostgresPool) -> None:
        self._pool = pool

    def unbind(self) -> None:
        self._pool = None

    @property
    def closed(self) -> bool:
        return self._pool is None or bool(self._pool.pool.closed)


class _ClientPrincipalAuthContextMiddleware:
    """Expose the ingress-validated principal to the MCP auth context."""

    def __init__(self, app: ASGIApp, authorized_application_ids: Sequence[str]) -> None:
        self._app = app
        self._authorized_application_ids = tuple(authorized_application_ids)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        principal = self._principal(scope) if scope["type"] == "http" else None
        if principal is None:
            await self._app(scope, receive, send)
            return

        user = AuthenticatedUser(
            AccessToken(
                token="",
                client_id=principal.application_id,
                scopes=[],
                subject=principal.subject_id,
            )
        )
        reset_token = auth_context_var.set(user)
        try:
            await self._app(scope, receive, send)
        finally:
            auth_context_var.reset(reset_token)

    def _principal(self, scope: Scope) -> Principal | None:
        encoded: str | None = None
        for name, value in scope.get("headers", ()):
            if name.decode("latin-1").lower() == CLIENT_PRINCIPAL_HEADER:
                encoded = value.decode("latin-1")
                break
        try:
            return parse_container_apps_principal(encoded, self._authorized_application_ids)
        except AskMyHumanError:
            return None


def parse_callback_events(payload: object) -> Sequence[CallEvent]:
    """Map one ACS CloudEvent batch onto terminal domain events."""
    items = payload if isinstance(payload, list) else [payload]
    events: list[CallEvent] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("callback payload must contain CloudEvent objects")
        event = parse_callback_event(item).call_event
        if event is not None:
            events.append(event)
    return events


def load_settings() -> Settings:
    """Read every setting from the environment through the sole settings boundary."""
    return Settings()  # type: ignore[call-arg]


def _configure_telemetry() -> Telemetry:
    connection_string = os.getenv(CONNECTION_STRING_VARIABLE)
    if not connection_string:
        # Local runs stay in-process instead of exporting to Azure Monitor.
        return AzureMonitorTelemetry()
    return configure_observability(connection_string=connection_string)


async def create_azure_runtime(settings: Settings) -> Runtime:
    """Build every Azure-backed dependency exactly once per process."""
    telemetry = _configure_telemetry()
    credential = DefaultAzureCredential()
    call_client = CallAutomationClient(str(settings.acs_endpoint), credential)
    http_client = httpx.AsyncClient()
    pool = PostgresPool(settings.database_url.get_secret_value())
    validator = AcsCallbackTokenValidator(http_client, str(settings.acs_callback_audience))

    async def close() -> None:
        await http_client.aclose()
        await call_client.close()
        await credential.close()

    async def validate_callback_token(token: str) -> None:
        await validator.validate("Bearer " + token)

    return Runtime(
        pool=pool,
        repository=PostgresRequestRepository(pool.pool),
        gateway=AcsCallAutomationGateway.from_settings(call_client, settings),
        telemetry=telemetry,
        validate_callback_token=validate_callback_token,
        close=close,
    )


def _transport_security(allowed_hosts: Sequence[str]) -> TransportSecuritySettings:
    """Accept each configured host with or without an explicit port."""
    hosts = [pattern for host in allowed_hosts for pattern in (host, f"{host}:*")]
    origins = [f"{scheme}://{pattern}" for pattern in hosts for scheme in ("https", "http")]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


async def _stop_tasks(
    cancellation: _LifespanCancellation, tasks: Sequence[asyncio.Task[None]]
) -> None:
    cancellation.cancel()
    for task in tasks:
        task.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            logger.error("A maintenance loop failed during shutdown.", exc_info=result)


def create_app(
    settings: Settings | None = None,
    *,
    runtime_factory: RuntimeFactory = create_azure_runtime,
) -> FastAPI:
    """Compose HTTP routes, the MCP transport, and lifespan-owned dependencies."""
    resolved = settings if settings is not None else load_settings()
    use_case = _UseCaseSlot()
    callback_validator = _CallbackValidatorSlot()
    pool_slot = _PoolSlot()

    mcp_app = create_streamable_http_app(
        use_case,
        transport_security=_transport_security(resolved.mcp_allowed_hosts),
        host=resolved.mcp_allowed_hosts[0],
    )

    async def authenticate(request: Request) -> Principal:
        return parse_container_apps_principal(
            request.headers.get(CLIENT_PRINCIPAL_HEADER),
            resolved.authorized_agent_app_ids,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        cancellation = _LifespanCancellation()
        async with AsyncExitStack() as stack:
            runtime = await runtime_factory(resolved)
            stack.push_async_callback(runtime.close)
            callback_validator.bind(runtime.validate_callback_token)
            stack.callback(callback_validator.unbind)

            await runtime.pool.open()
            stack.push_async_callback(runtime.pool.close)
            pool_slot.bind(runtime.pool)
            stack.callback(pool_slot.unbind)

            clock = SystemClock()
            service = AskHumanService(
                runtime.repository,
                runtime.gateway,
                clock,
                runtime.telemetry,
                deadline_seconds=resolved.deadline_seconds,
                work_cutoff_seconds=resolved.work_cutoff_seconds,
                poll_interval_seconds=resolved.poll_interval_milliseconds / 1000,
            )
            maintenance = RequestMaintenance(
                runtime.repository,
                clock,
                retention_hours=resolved.retention_hours,
            )
            tasks = [
                asyncio.create_task(maintenance.run_expiry_loop(cancellation)),
                asyncio.create_task(maintenance.run_purge_loop(cancellation)),
            ]
            stack.push_async_callback(_stop_tasks, cancellation, tasks)

            await stack.enter_async_context(mcp_app.router.lifespan_context(mcp_app))

            use_case.bind(service)
            stack.callback(use_case.unbind)
            yield

    application = FastAPI(title="Ask My Human", lifespan=lifespan)
    application.include_router(create_requests_router(use_case=use_case, authenticate=authenticate))
    application.include_router(
        create_callbacks_router(
            use_case=use_case,
            validate_token=callback_validator.validate,
            parse_events=parse_callback_events,
        )
    )
    application.include_router(liveness_router)
    application.include_router(create_readiness_router(resolved, pool_slot))
    application.include_router(create_oauth_metadata_router(resolved))
    # Mount last so the MCP transport never shadows the HTTP or metadata routes.
    application.mount(
        "/",
        _ClientPrincipalAuthContextMiddleware(mcp_app, resolved.authorized_agent_app_ids),
    )
    return application


def __getattr__(name: str) -> Any:
    """Build the ASGI application lazily so importing the module needs no settings."""
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    application = create_app()
    globals()["app"] = application
    return application
