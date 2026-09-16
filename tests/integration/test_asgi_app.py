"""Composition tests for the sole ASGI application in ``main.py``."""

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Mount

from ask_my_human.main import create_app

pytestmark = pytest.mark.usefixtures("database_url")


@pytest.fixture
def configured_client(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ACS_ENDPOINT", "https://example.communication.azure.com")
    monkeypatch.setenv("ACS_SOURCE_PHONE_NUMBER", "+15555550100")
    monkeypatch.setenv("MY_MOBILE_NUMBER", "+15555550101")
    monkeypatch.setenv("AZURE_AI_ENDPOINT", "https://example.cognitiveservices.azure.com")
    monkeypatch.setenv("ACS_CALLBACK_AUDIENCE", "https://askmyhuman.example.com")
    monkeypatch.setenv("ENTRA_TENANT_ID", "00000000-0000-0000-0000-000000000000")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "00000000-0000-0000-0000-000000000000")
    monkeypatch.setenv("AUTHORIZED_AGENT_APP_IDS", "00000000-0000-0000-0000-000000000000")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "testserver")

    app = create_app()
    with TestClient(app) as client:
        yield client


def test_liveness_reports_ok_without_dependencies(configured_client: TestClient) -> None:
    response = configured_client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_ready_once_the_pool_is_open(configured_client: TestClient) -> None:
    response = configured_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_oauth_protected_resource_metadata_is_served(configured_client: TestClient) -> None:
    response = configured_client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json()["resource"] == "api://00000000-0000-0000-0000-000000000000"


def test_requests_route_rejects_unauthenticated_agents(configured_client: TestClient) -> None:
    response = configured_client.post(
        "/v1/requests",
        json={"kind": "approval", "prompt": "Deploy now?", "idempotencyKey": None},
    )

    assert response.status_code == 401


def test_callbacks_route_rejects_missing_bearer_token(configured_client: TestClient) -> None:
    response = configured_client.post("/v1/callbacks/acs", json=[])

    assert response.status_code == 401


def test_mcp_mount_does_not_shadow_http_routes(configured_client: TestClient) -> None:
    app = cast(FastAPI, configured_client.app)
    mount_route = app.routes[-1]

    assert isinstance(mount_route, Mount)
    assert mount_route.path == ""

    for path in (
        "/health/live",
        "/health/ready",
        "/.well-known/oauth-protected-resource",
    ):
        response = configured_client.get(path)
        assert response.status_code == 200, path
