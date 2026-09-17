"""Composition tests for the single ASGI application."""

import asyncio
import base64
import json
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from pydantic import AnyHttpUrl, SecretStr
from support.fakes import FakeAskHumanUseCase, FakeRequestRepository
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from ask_my_human import main
from ask_my_human.application.maintenance import RequestMaintenance
from ask_my_human.config import Settings
from ask_my_human.contracts import AskHumanResult, Outcome, RequestStatus
from ask_my_human.domain.models import CallEvent, CallEventType, HumanRequest
from ask_my_human.main import ApplicationComponents, create_app, parse_callback_events
from ask_my_human.observability import instrument_app
from ask_my_human.security.agent import REQUIRED_ROLE


def test_component_factory_wires_gateway_and_telemetry_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factories = {}
    for name in (
        "configure_observability",
        "DefaultAzureCredential",
        "CallAutomationClient",
        "AcsCallAutomationGateway",
        "PostgresPool",
        "PostgresRequestRepository",
        "AskHumanService",
        "RequestMaintenance",
        "AcsCallbackTokenValidator",
    ):
        factory = MagicMock()
        factories[name] = factory
        monkeypatch.setattr(main, name, factory)
    http_client = MagicMock()
    monkeypatch.setattr(httpx, "AsyncClient", http_client)
    configured = settings()
    components = main.build_components(configured)
    telemetry = factories["configure_observability"].return_value
    repository = factories["PostgresRequestRepository"].return_value
    gateway = factories["AcsCallAutomationGateway"].from_settings.return_value
    factories["PostgresRequestRepository"].assert_called_once_with(
        factories["PostgresPool"].return_value.pool,
        telemetry=telemetry,
    )
    maintenance_kwargs = factories["RequestMaintenance"].call_args.kwargs
    assert maintenance_kwargs["gateway"] is gateway
    assert maintenance_kwargs["telemetry"] is telemetry
    assert factories["RequestMaintenance"].call_args.args[0] is repository
    factories["AcsCallbackTokenValidator"].assert_called_once_with(
        http_client.return_value,
        configured.acs_callback_audience,
    )
    repository.pending_count.assert_not_called()
    assert components.maintenance is factories["RequestMaintenance"].return_value


HOST = "askmyhuman.example.com"
REQUEST_ID = UUID("20000000-0000-4000-8000-000000000001")
AGENT_APP_ID = "11111111-1111-4111-8111-111111111111"
CALLBACK_TOKEN = "callback-token"


async def test_application_container_migrates_and_serves_health_without_query_logs() -> None:
    build = subprocess.run(
        ["docker", "build", "--tag", "ask-my-human:mvp", "."],
        capture_output=True,
        timeout=600,
        check=False,
    )
    assert build.returncode == 0, "Application image build failed; run the image build gate."
    with (
        Network() as network,
        PostgresContainer("postgres:16-alpine", password="smoke@password%")
        .with_exposed_ports(8000)
        .with_network(network)
        .with_network_aliases("smoke-db") as postgres,
    ):
        environment = {
            "DATABASE_URL": "postgresql://test:smoke%40password%25@127.0.0.1:5432/test",
            "ACS_ENDPOINT": "https://example.communication.azure.com",
            "ACS_SOURCE_PHONE_NUMBER": "+15555550100",
            "AZURE_AI_ENDPOINT": "https://example.cognitiveservices.azure.com",
            "ACS_CALLBACK_URL": "https://example.invalid/v1/callbacks/acs",
            "ACS_CALLBACK_AUDIENCE": "00000000-0000-4000-8000-000000000001",
            "ENTRA_TENANT_ID": "tenant",
            "ENTRA_CLIENT_ID": "client",
            "AUTHORIZED_AGENT_APP_IDS": AGENT_APP_ID,
            "MCP_ALLOWED_HOSTS": "localhost:*,127.0.0.1:*",
            "AZURE_TOKEN_CREDENTIALS": "ManagedIdentityCredential",
        }
        with (
            DockerContainer("ask-my-human:mvp")
            .with_kwargs(network_mode=f"container:{postgres.get_wrapped_container().id}")
            .with_envs(**environment) as container
        ):
            address = postgres.get_container_host_ip()
            port = postgres.get_exposed_port(8000)
            async with httpx.AsyncClient(
                base_url=f"http://{address}:{port}", timeout=2, trust_env=False
            ) as client:
                async with asyncio.timeout(60):
                    while True:
                        wrapped = container.get_wrapped_container()
                        wrapped.reload()
                        if wrapped.status == "exited":
                            stdout, stderr = container.get_logs()
                            pytest.fail((stdout + stderr).decode())
                        try:
                            ready = await client.get("/health/ready")
                            if ready.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(0.25)
                assert (await client.get("/health/live")).status_code == 200
                assert (await client.post("/v1/requests", json={})).status_code == 401
                response = await client.post(
                    "/v1/callbacks/acs?token=SMOKE_QUERY_SENTINEL", json=[]
                )
                assert response.status_code == 401
            exit_code, output = postgres.exec(
                [
                    "psql",
                    "-U",
                    "test",
                    "-d",
                    "test",
                    "-tAc",
                    "SELECT version_num FROM alembic_version",
                ]
            )
            assert exit_code == 0
            assert b"20260917_0003" in output
            stdout, stderr = container.get_logs()
            assert b"SMOKE_QUERY_SENTINEL" not in stdout + stderr
            assert b"smoke%40password" not in stdout + stderr


class CountingRepository(FakeRequestRepository):
    """Repository double that records maintenance loop activity."""

    def __init__(self) -> None:
        super().__init__()
        self.expiry_runs = 0
        self.purge_runs = 0
        self.expired = asyncio.Event()
        self.purged = asyncio.Event()

    async def expire_stale_calls(self, now: datetime) -> Sequence[HumanRequest]:
        self.expiry_runs += 1
        self.expired.set()
        return await super().expire_stale_calls(now)

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
        azure_ai_endpoint=AnyHttpUrl("https://example.cognitiveservices.azure.com"),
        acs_callback_url=AnyHttpUrl(f"https://{HOST}/v1/callbacks/acs"),
        acs_callback_audience="00000000-0000-4000-8000-000000000001",
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


@pytest.mark.asyncio
async def test_composed_app_attaches_content_free_server_spans(
    composition: Composition,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("composition-test")
    monkeypatch.setattr(main, "instrument_app", lambda app: instrument_app(app, tracer=tracer))
    sentinel = "COMPOSED_SENSITIVE_CONTENT"
    try:
        async with running_client(composition) as client:
            response = await client.post(
                f"/v1/requests?token={sentinel}",
                headers={"x-ms-client-principal": principal_header(), "Authorization": sentinel},
                json={
                    "kind": "approval",
                    "prompt": sentinel,
                    "idempotencyKey": str(uuid4()),
                    "phoneNumber": "+15555550999",
                },
            )
        assert response.status_code == 200
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].kind is SpanKind.SERVER
        assert spans[0].name == "askhuman.http"
        assert spans[0].attributes == {
            "http.request.method": "POST",
            "http.response.status_code": 200,
        }
        assert sentinel not in str(spans[0].attributes)
        assert spans[0].events == ()
    finally:
        provider.shutdown()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("loop_name", ["run_expiry_loop", "run_purge_loop"])
async def test_failed_maintenance_fails_readiness_and_drains_before_closing(
    composition: Composition,
    monkeypatch: pytest.MonkeyPatch,
    loop_name: str,
) -> None:
    entered = asyncio.Event()
    drained = asyncio.Event()

    async def fail(cancellation: object) -> None:
        await entered.wait()
        raise RuntimeError("maintenance failed")

    async def wait(cancellation: object) -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            drained.set()

    components = composition.components()
    other_loop = "run_purge_loop" if loop_name == "run_expiry_loop" else "run_expiry_loop"
    monkeypatch.setattr(components.maintenance, loop_name, fail)
    monkeypatch.setattr(components.maintenance, other_loop, wait)
    original_close = composition.pool.close

    async def close() -> None:
        assert drained.is_set()
        await original_close()

    monkeypatch.setattr(composition.pool, "close", close)
    app = create_app(components)
    with pytest.raises(ExceptionGroup):
        async with app.router.lifespan_context(app):
            await entered.wait()
            await asyncio.sleep(0)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=f"https://{HOST}"
            ) as client:
                assert (await client.get("/health/ready")).status_code == 503
                assert (await client.get("/health/live")).status_code == 200
    assert drained.is_set()
    assert composition.closed == ["acs", "http"]


@pytest.mark.asyncio
async def test_cancelled_startup_closes_partially_open_pool(
    composition: Composition,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = asyncio.Event()

    async def open_pool() -> None:
        composition.pool.events.append("partial-open")
        opened.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(composition.pool, "open", open_pool)
    app = composition.app()

    async def start() -> None:
        async with app.router.lifespan_context(app):
            pytest.fail("startup must not finish")

    startup = asyncio.create_task(start())
    await opened.wait()
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    assert composition.pool.events == ["partial-open", "close"]
    assert composition.closed == ["acs", "http"]
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
            json={
                "kind": "approval",
                "prompt": "Deploy now?",
                "idempotencyKey": str(uuid4()),
                "phoneNumber": "+15555550101",
            },
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
            json={
                "kind": "approval",
                "prompt": "Deploy now?",
                "idempotencyKey": str(uuid4()),
                "phoneNumber": "+15555550101",
            },
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
        CallEvent(
            request_id=request_id,
            event_type=CallEventType.APPROVED,
            answer=None,
            call_id="call-1",
            event_id="event-1",
        )
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
                "x-ms-client-principal": principal_header(),
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
@pytest.mark.parametrize("identity", ["authorized", "missing", "roleless", "disallowed"])
async def test_mounted_mcp_enforces_the_http_authorization_boundary(
    composition: Composition, identity: str
) -> None:
    header = principal_header()
    payload = json.loads(base64.b64decode(header))
    if identity == "roleless":
        payload["claims"] = [claim for claim in payload["claims"] if claim["typ"] != "roles"]
    elif identity == "disallowed":
        payload["claims"][0]["val"] = "disallowed-agent"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if identity != "missing":
        headers["x-ms-client-principal"] = base64.b64encode(json.dumps(payload).encode()).decode()
    async with running_client(composition) as client:
        initialized = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        if identity != "authorized":
            assert initialized.status_code == (401 if identity == "missing" else 403)
            assert composition.use_case.requests == []
            return
        headers["mcp-session-id"] = initialized.headers["mcp-session-id"]
        headers["mcp-protocol-version"] = "2025-06-18"
        await client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        response = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "ask_human",
                    "arguments": {
                        "kind": "approval",
                        "prompt": "Deploy?",
                        "idempotencyKey": str(uuid4()),
                        "phoneNumber": "+15555550101",
                    },
                },
            },
        )
    messages = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    result = messages[-1]["result"]
    assert result.get("isError", False) is (identity != "authorized")
    if identity == "authorized":
        assert composition.use_case.requests[0][0].application_id == AGENT_APP_ID
        assert composition.use_case.requests[0][0].subject_id == "agent-object-id"


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


@pytest.mark.parametrize(
    ("event_name", "event_type", "code"),
    [
        ("CallConnected", CallEventType.CONNECTED, None),
        ("CreateCallFailed", CallEventType.DEPENDENCY_FAILED, 500),
        ("RecognizeFailed", CallEventType.DEPENDENCY_FAILED, 500),
        ("PlayCompleted", CallEventType.PLAY_COMPLETED, None),
        ("PlayFailed", CallEventType.PLAY_FAILED, 500),
    ],
)
def test_callback_payload_parsing_forwards_lifecycle_and_technical_events(
    event_name: str,
    event_type: CallEventType,
    code: int | None,
) -> None:
    connected = [
        {
            "specversion": "1.0",
            "id": "event-2",
            "source": "calling",
            "type": f"Microsoft.Communication.{event_name}",
            "data": {
                "operationContext": str(REQUEST_ID),
                "callConnectionId": "call-1",
                **({"resultInformation": {"code": code, "subCode": 0}} if code is not None else {}),
            },
        }
    ]

    assert parse_callback_events(connected) == [
        CallEvent(
            request_id=REQUEST_ID,
            event_type=event_type,
            call_id="call-1",
            acs_code=code,
            event_id="event-2",
        )
    ]

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
