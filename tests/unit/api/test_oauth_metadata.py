from fastapi import FastAPI
from fastapi.testclient import TestClient

from ask_my_human.api.oauth_metadata import create_oauth_metadata_router
from ask_my_human.config import Settings


def test_oauth_protected_resource_metadata_is_exact_and_sanitized() -> None:
    configured = Settings(
        database_url="postgresql://user:database-secret@localhost:5432/askmyhuman",
        acs_endpoint="https://secret.communication.azure.com",
        acs_source_phone_number="+15555550100",
        my_mobile_number="+15555550101",
        azure_ai_endpoint="https://secret.cognitiveservices.azure.com",
        acs_callback_audience="https://askmyhuman.example.com",
        entra_tenant_id="test-tenant-id",
        entra_client_id="ask-my-human-client-id",
        authorized_agent_app_ids=("authorized-agent-id",),
        mcp_allowed_hosts=("askmyhuman.example.com",),
    )
    app = FastAPI()
    app.include_router(create_oauth_metadata_router(configured))

    response = TestClient(app).get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json() == {
        "resource": "api://ask-my-human-client-id",
        "authorization_servers": ["https://login.microsoftonline.com/test-tenant-id/v2.0"],
        "scopes_supported": ["api://ask-my-human-client-id/.default"],
        "bearer_methods_supported": ["header"],
    }
    for secret in (
        "database-secret",
        "+15555550100",
        "+15555550101",
        "secret.communication.azure.com",
        "secret.cognitiveservices.azure.com",
        "authorized-agent-id",
    ):
        assert secret not in response.text
