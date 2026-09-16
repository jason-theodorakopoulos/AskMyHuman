"""ASGI composition tests exercising both HTTP route families and ``/mcp``."""

import json
from base64 import b64encode
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ask_my_human.main import app

_SETTINGS_ENV = {
    "ACS_ENDPOINT": "https://example.communication.azure.com",
    "ACS_SOURCE_PHONE_NUMBER": "+15555550100",
    "MY_MOBILE_NUMBER": "+15555550101",
    "AZURE_AI_ENDPOINT": "https://example.cognitiveservices.azure.com",
    "ACS_CALLBACK_AUDIENCE": "https://asgi-app.example.com",
    "ENTRA_TENANT_ID": "00000000-0000-0000-0000-000000000000",
    "ENTRA_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
    "AUTHORIZED_AGENT_APP_IDS": "22222222-2222-2222-2222-222222222222",
    "MCP_ALLOWED_HOSTS": "testserver",
}


@pytest.fixture(scope="module")
def client(database_url: str) -> Iterator[TestClient]:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DATABASE_URL", database_url)
    for key, value in _SETTINGS_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)

    try:
        with TestClient(app) as instance:
            yield instance
    finally:
        monkeypatch.undo()


def _encoded_principal(
    *, application_id: str, roles: tuple[str, ...] = ("AskHuman.Invoke",)
) -> str:
    claims = [{"typ": "azp", "val": application_id}, {"typ": "oid", "val": "subject"}]
    claims.extend({"typ": "roles", "val": role} for role in roles)
    payload = {"auth_typ": "aad", "claims": claims}
    return b64encode(json.dumps(payload).encode()).decode()


def test_liveness_reports_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_ready_once_the_pool_is_open(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_oauth_protected_resource_metadata_reflects_configured_tenant(
    client: TestClient,
) -> None:
    response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == "api://11111111-1111-1111-1111-111111111111"
    assert body["authorization_servers"] == [
        "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000000/v2.0"
    ]


def test_requests_route_rejects_missing_agent_principal(client: TestClient) -> None:
    response = client.post(
        "/v1/requests",
        json={"kind": "approval", "prompt": "Deploy now?", "idempotencyKey": str(uuid4())},
    )

    assert response.status_code == 401


def test_requests_route_rejects_unauthorized_agent_application(client: TestClient) -> None:
    response = client.post(
        "/v1/requests",
        json={"kind": "approval", "prompt": "Deploy now?", "idempotencyKey": str(uuid4())},
        headers={"x-ms-client-principal": _encoded_principal(application_id="not-authorized")},
    )

    assert response.status_code == 403


def test_callbacks_route_rejects_missing_bearer_token(client: TestClient) -> None:
    response = client.post("/v1/callbacks/acs", json=[])

    assert response.status_code == 401


def test_mcp_route_is_mounted_and_not_shadowed_by_v1_routes(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"accept": "application/json, text/event-stream"},
    )

    assert response.status_code != 404


def test_repeated_lifespan_entry_does_not_duplicate_routes(client: TestClient) -> None:
    route_count_before = len(app.router.routes)

    with TestClient(app):
        pass

    assert len(app.router.routes) == route_count_before
