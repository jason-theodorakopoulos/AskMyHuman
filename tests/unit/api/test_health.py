from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ask_my_human.api.health import create_readiness_router, liveness_router
from ask_my_human.config import Settings


def settings() -> Settings:
    return Settings(
        database_url="postgresql://user:database-secret@localhost:5432/askmyhuman",
        acs_endpoint="https://example.communication.azure.com",
        acs_source_phone_number="+15555550100",
        my_mobile_number="+15555550101",
        azure_ai_endpoint="https://example.cognitiveservices.azure.com",
        acs_callback_audience="https://askmyhuman.example.com",
        entra_tenant_id="tenant",
        entra_client_id="client",
        authorized_agent_app_ids=("agent",),
        mcp_allowed_hosts=("askmyhuman.example.com",),
    )


@dataclass
class StubPool:
    closed: bool


class InvalidPool:
    @property
    def closed(self) -> bool:
        raise RuntimeError("pool failure with database-secret")


def client(configured: Settings | None, pool: StubPool | InvalidPool) -> TestClient:
    app = FastAPI()
    app.include_router(liveness_router)
    app.include_router(create_readiness_router(configured, pool))
    return TestClient(app)


def test_liveness_proves_process_availability_only() -> None:
    response = client(None, InvalidPool()).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_succeeds_for_valid_config_and_open_pool() -> None:
    response = client(settings(), StubPool(closed=False)).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_fails_until_pool_is_open() -> None:
    pool = StubPool(closed=True)
    test_client = client(settings(), pool)

    unavailable = test_client.get("/health/ready")
    pool.closed = False
    ready = test_client.get("/health/ready")

    assert unavailable.status_code == 503
    assert unavailable.json() == {"status": "unavailable"}
    assert ready.status_code == 200


def test_readiness_fails_for_missing_config_without_disclosure() -> None:
    response = client(None, StubPool(closed=False)).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_readiness_sanitizes_pool_state_failures() -> None:
    response = client(settings(), InvalidPool()).get("/health/ready")
    body = response.text

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "database-secret" not in body
    assert "pool failure" not in body
    assert "+15555550100" not in body
    assert "communication.azure.com" not in body
