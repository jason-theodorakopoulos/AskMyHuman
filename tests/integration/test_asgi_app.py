"""Composition tests for the single ASGI application."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import AnyHttpUrl, SecretStr
from support.fakes import FakeAskHumanUseCase, FakeRequestRepository

from ask_my_human.application.maintenance import RequestMaintenance
from ask_my_human.config import Settings
from ask_my_human.contracts import AskHumanResult, Outcome, RequestStatus
from ask_my_human.domain.models import CallEvent, CallEventType
from ask_my_human.main import ApplicationComponents, create_app, parse_callback_events
from ask_my_human.security.agent import REQUIRED_ROLE

HOST = "askmyhuman.example.com"
REQUEST_ID = UUID("20000000-0000-4000-8000-000000000001")
AGENT_APP_ID = "11111111-1111-4111-8111-111111111111"
CALLBACK_TOKEN = "callback-token"


class CountingRepository(FakeRequestRepository):
    """Repository double that records maintenance loop activity."""

    def __init__(self) -> None:
        super().__init__()
        self.expiry_runs = 0
        self.purge_runs = 0
        self.expired = asyncio.Event()
        self.purged = asyncio.Event()

    async def expire_stale(self, now: datetime) -> int:
        self.expiry_runs += 1
        self.expired.set()
        return await super().expire_stale(now)

    async def purge_terminal(self, before: datetime) -> int:
        self.purge_runs += 1
        self.purged.set()
        return await super().purge_terminal(before)


class SpyPool:
    """Pool double that records lifecycle order without a database."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    async def open(self) -> None:
        self.events.append("open")
        self._closed = False

    async def close(self) -> None:
        self.events.append("close")
        self._closed = True


class SleepingClock:
    """Clock that yields to the event loop so maintenance loops stay cooperative."""

    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)
        await asyncio.sleep(0)


def settings() -> Settings:
    return Settings(
        database_url=SecretStr("postgresql://localhost:5432/askmyhuman"),
        acs_endpoint=AnyHttpUrl("https://example.communication.azure.com"),
        acs_source_phone_number=SecretStr("+15555550100"),
        my_mobile_number=SecretStr("+15555550101"),
        azure_ai_endpoint=AnyHttpUrl("https://example.cognitiveservices.azure.com"),
        acs_callback_audience=AnyHttpUrl(f"https://{HOST}"),
        entra_tenant_id="tenant",
        entra_client_id="client",
        authorized_agent_app_ids=(AGENT_APP_ID,),
        mcp_allowed_hosts=(HOST,),
    )


def principal_header() -> str:
    payload = {
        "auth_typ": "aad",
        "claims": [
            {"typ": "appid", "val": AGENT_APP_ID},
            {"typ": "oid", "val": "agent-object-id"},
            {"typ": "roles", "val": REQUIRED_ROLE},
        ],
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


class Composition:
    def __init__(self) -> None:
        self.use_case = FakeAskHumanUseCase(
            AskHumanResult(
                requestId=REQUEST_ID,
                status=RequestStatus.RESPONDED,
                outcome=Outcome.APPROVED,
            )
        )
        self.pool = SpyPool()
        self.repository = CountingRepository()
        self.clock = SleepingClock()
        self.validated_tokens: list[str] = []
        self.closed: list[str] = []

    async def validate_token(self, token: str) -> None:
        self.validated_tokens.append(token)

    def components(
        self,
        closers: tuple[Callable[[], Awaitable[None]], ...] | None = None,
    ) -> ApplicationComponents:
        async def close_acs() -> None:
            self.closed.append("acs")

        async def close_http() -> None:
            self.closed.append("http")

        return ApplicationComponents(
            settings=settings(),
            pool=self.pool,
            pool_state=self.pool,
            use_case=self.use_case,
            maintenance=RequestMaintenance(
                self.repository,
                self.clock,
                expiry_interval_seconds=0.01,
                purge_interval_seconds=0.01,
            ),
            validate_callback_token=self.validate_token,
            closers=closers if closers is not None else (close_acs, close_http),
        )

    def app(self) -> FastAPI:
        return create_app(self.components())


@pytest.fixture
def composition() -> Composition:
    return Composition()


@asynccontextmanager
async def running_client(composition: Composition) -> AsyncIterator[AsyncClient]:
    """Serve the composed application with its lifespan inside the calling task."""
    app = composition.app()
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url=f"https://{HOST}") as http_client,
        app.router.lifespan_context(app),
    ):
        yield http_client


def callback_payload(request_id: UUID) -> list[dict[str, object]]:
    return [
        {
            "specversion": "1.0",
            "id": "event-1",
            "source": "calling",
            "type": "Microsoft.Communication.RecognizeCompleted",
            "data": {
                "operationContext": str(request_id),
                "callConnectionId": "call-1",
                "choiceResult": {"label": "approve"},
            },
        }
    ]


@pytest.mark.asyncio
async def test_lifespan_opens_pool_before_readiness_and_closes_in_reverse(
    composition: Composition,
) -> None:
    app = composition.app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=f"https://{HOST}"
    ) as http_client:
        before = await http_client.get("/health/ready")
        assert before.status_code == 503

        async with app.router.lifespan_context(app):
            during = await http_client.get("/health/ready")
            assert during.status_code == 200
            assert during.json() == {"status": "ready"}
            assert composition.pool.events == ["open"]

    assert composition.pool.events == ["open", "close"]
    assert composition.closed == ["acs", "http"]


@pytest.mark.asyncio
async def test_liveness_and_oauth_metadata_are_served(composition: Composition) -> None:
    async with running_client(composition) as client:
        live = await client.get("/health/live")
        metadata = await client.get("/.well-known/oauth-protected-resource")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert metadata.status_code == 200
    body = metadata.json()
    assert body["resource"] == "api://client"
    assert body["authorization_servers"] == ["https://login.microsoftonline.com/tenant/v2.0"]


@pytest.mark.asyncio
async def test_request_route_uses_the_composed_use_case(composition: Composition) -> None:
    async with running_client(composition) as client:
        response = await client.post(
            "/v1/requests",
            headers={"x-ms-client-principal": principal_header()},
            json={"kind": "approval", "prompt": "Deploy now?", "idempotencyKey": str(uuid4())},
        )

    assert response.status_code == 200
    assert response.json()["outcome"] == "approved"
    principal, _, _ = composition.use_case.requests[0]
    assert principal.application_id == AGENT_APP_ID


@pytest.mark.asyncio
async def test_request_route_rejects_unauthenticated_callers(composition: Composition) -> None:
    async with running_client(composition) as client:
        response = await client.post(
            "/v1/requests",
            json={"kind": "approval", "prompt": "Deploy now?", "idempotencyKey": str(uuid4())},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_callback_route_validates_tokens_and_dispatches_events(
    composition: Composition,
) -> None:
    request_id = uuid4()
    async with running_client(composition) as client:
        response = await client.post(
            "/v1/callbacks/acs",
            headers={"Authorization": " ".join(("Bearer", CALLBACK_TOKEN))},
            json=callback_payload(request_id),
        )

    assert response.status_code == 200
    assert composition.validated_tokens == [CALLBACK_TOKEN]
    assert composition.use_case.events == [
        CallEvent(request_id=request_id, event_type=CallEventType.APPROVED, answer=None)
    ]


@pytest.mark.asyncio
async def test_mcp_transport_is_mounted_without_shadowing_http_routes(
    composition: Composition,
) -> None:
    async with running_client(composition) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            },
        )

    assert response.status_code == 200
    assert "mcp-session-id" in response.headers


@pytest.mark.asyncio
async def test_maintenance_loops_run_and_stop_with_the_lifespan(
    composition: Composition,
) -> None:
    app = composition.app()
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(composition.repository.expired.wait(), timeout=5)
        await asyncio.wait_for(composition.repository.purged.wait(), timeout=5)

    stopped = (composition.repository.expiry_runs, composition.repository.purge_runs)
    await asyncio.sleep(0.05)
    assert (composition.repository.expiry_runs, composition.repository.purge_runs) == stopped


def test_callback_payload_parsing_skips_non_terminal_events() -> None:
    connected = [
        {
            "specversion": "1.0",
            "id": "event-2",
            "source": "calling",
            "type": "Microsoft.Communication.CallConnected",
            "data": {"operationContext": str(REQUEST_ID), "callConnectionId": "call-1"},
        }
    ]

    assert parse_callback_events(connected) == []

    with pytest.raises(ValueError):
        parse_callback_events({"not": "a list"})


@pytest.mark.asyncio
async def test_failing_client_close_still_closes_every_client(composition: Composition) -> None:
    async def failing_close() -> None:
        composition.closed.append("acs")
        raise RuntimeError("client shutdown failed")

    async def close_http() -> None:
        composition.closed.append("http")

    app = create_app(composition.components(closers=(failing_close, close_http)))

    with pytest.raises(ExceptionGroup):
        async with app.router.lifespan_context(app):
            pass

    assert composition.closed == ["acs", "http"]
    assert composition.pool.events == ["open", "close"]
