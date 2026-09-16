"""Composition-root tests over the real ASGI application and PostgreSQL."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from support.fakes import FakeCallAutomationGateway, FakeTelemetry

from ask_my_human.config import Settings
from ask_my_human.errors import AskMyHumanError, ErrorCode
from ask_my_human.main import Runtime, create_app
from ask_my_human.persistence.pool import PostgresPool
from ask_my_human.persistence.repository import PostgresRequestRepository

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "acs"
AGENT_APPLICATION_ID = "11111111-1111-4111-8111-111111111111"
CALLBACK_TOKEN = "callback-token"  # noqa: S105 - test-only sentinel, not a credential


def principal_header() -> str:
    payload = {
        "auth_typ": "aad",
        "claims": [
            {"typ": "appid", "val": AGENT_APPLICATION_ID},
            {"typ": "oid", "val": "agent-subject"},
            {"typ": "roles", "val": "AskHuman.Invoke"},
        ],
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def settings_for(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,  # type: ignore[arg-type]
        acs_endpoint="https://test.communication.azure.com",  # type: ignore[arg-type]
        acs_source_phone_number="+15555550100",  # type: ignore[arg-type]
        my_mobile_number="+15555550101",  # type: ignore[arg-type]
        azure_ai_endpoint="https://test.cognitiveservices.azure.com",  # type: ignore[arg-type]
        acs_callback_audience="https://askmyhuman.test",  # type: ignore[arg-type]
        entra_tenant_id="22222222-2222-4222-8222-222222222222",
        entra_client_id="33333333-3333-4333-8333-333333333333",
        authorized_agent_app_ids=(AGENT_APPLICATION_ID,),
        mcp_allowed_hosts=("testserver",),
        deadline_seconds=20,
        work_cutoff_seconds=15,
        poll_interval_milliseconds=50,
    )


@asynccontextmanager
async def composed_app(
    database_url: str,
) -> AsyncIterator[tuple[AsyncClient, FakeCallAutomationGateway, dict[str, Any]]]:
    """Run one composed application, including the MCP session manager, per test."""
    gateway = FakeCallAutomationGateway()
    state: dict[str, Any] = {"closed": False, "tokens": []}

    async def runtime_factory(settings: Settings) -> Runtime:
        pool = PostgresPool(settings.database_url.get_secret_value())

        async def close() -> None:
            state["closed"] = True

        async def validate_callback_token(token: str) -> None:
            state["tokens"].append(token)
            if token != CALLBACK_TOKEN:
                raise AskMyHumanError(ErrorCode.UNAUTHENTICATED, "Invalid callback token")

        return Runtime(
            pool=pool,
            repository=PostgresRequestRepository(pool.pool),
            gateway=gateway,
            telemetry=FakeTelemetry(),
            validate_callback_token=validate_callback_token,
            close=close,
        )

    app = create_app(settings_for(database_url), runtime_factory=runtime_factory)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver", timeout=30.0
        ) as client,
    ):
        yield client, gateway, state
    assert state["closed"] is True


async def _wait_for_call(gateway: FakeCallAutomationGateway) -> UUID:
    for _ in range(200):
        if gateway.created:
            return gateway.created[0].request_id
        await asyncio.sleep(0.05)
    raise AssertionError("the composition root never placed a call")


def callback_payload(request_id: UUID) -> list[dict[str, Any]]:
    event = json.loads((FIXTURES / "recognize-choice-completed.json").read_text())
    event["data"]["operationContext"] = str(request_id)
    return [event]


@pytest.mark.asyncio
async def test_health_and_metadata_routes_are_composed(database_url: str) -> None:
    async with composed_app(database_url) as (client, _, _):
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")
        metadata = await client.get("/.well-known/oauth-protected-resource")

    assert live.status_code == 200
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert metadata.status_code == 200
    assert metadata.json()["resource"].startswith("api://")


@pytest.mark.asyncio
async def test_request_without_principal_is_rejected(database_url: str) -> None:
    async with composed_app(database_url) as (client, gateway, _):
        response = await client.post(
            "/v1/requests",
            json={"kind": "approval", "prompt": "Deploy?", "idempotencyKey": str(uuid4())},
        )

    assert response.status_code == 401
    assert gateway.created == []


@pytest.mark.asyncio
async def test_request_completes_through_the_composed_callback_route(
    database_url: str, postgres_pool: PostgresPool
) -> None:
    del postgres_pool  # Truncates the table before the application opens its own pool.
    async with composed_app(database_url) as (client, gateway, state):
        ask = asyncio.create_task(
            client.post(
                "/v1/requests",
                headers={"x-ms-client-principal": principal_header()},
                json={"kind": "approval", "prompt": "Deploy?", "idempotencyKey": str(uuid4())},
            )
        )

        request_id = await _wait_for_call(gateway)
        callback = await client.post(
            "/v1/callbacks/acs",
            headers={"Authorization": "Bearer " + CALLBACK_TOKEN},
            json=callback_payload(request_id),
        )
        response = await ask

    assert callback.status_code == 200
    assert state["tokens"] == [CALLBACK_TOKEN]
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requestId"] == str(request_id)
    assert body["status"] == "responded"
    assert body["outcome"] == "approved"
    assert gateway.acknowledged == [f"call-{request_id}"]


@pytest.mark.asyncio
async def test_callback_route_rejects_a_missing_token(database_url: str) -> None:
    async with composed_app(database_url) as (client, _, _):
        response = await client.post("/v1/callbacks/acs", json=callback_payload(uuid4()))

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_mcp_transport_is_mounted_without_shadowing_http_routes(database_url: str) -> None:
    async with composed_app(database_url) as (client, _, _):
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "x-ms-client-principal": principal_header(),
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )

    assert response.status_code != 404
    assert "jsonrpc" in response.text.lower(), response.text
