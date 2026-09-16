"""Unit tests for the ASGI lifespan's startup-failure cleanup behaviour."""

from contextlib import AbstractAsyncContextManager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI

from ask_my_human import main

_SETTINGS_ENV = {
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
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


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _SETTINGS_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)


@pytest.mark.asyncio
async def test_lifespan_closes_already_created_clients_when_pool_open_fails() -> None:
    app = FastAPI()
    credential_close = AsyncMock()
    http_client_aclose = AsyncMock()
    call_automation_client_close = AsyncMock()

    with (
        patch.object(main, "DefaultAzureCredential") as credential_cls,
        patch.object(main, "httpx") as httpx_module,
        patch.object(main, "CallAutomationClient") as call_client_cls,
        patch.object(main, "PostgresPool") as pool_cls,
    ):
        credential_cls.return_value.close = credential_close
        httpx_module.AsyncClient.return_value.aclose = http_client_aclose
        call_client_cls.return_value.close = call_automation_client_close
        pool_cls.return_value.open = AsyncMock(side_effect=RuntimeError("database unreachable"))

        lifespan_context = main._lifespan(app)

        with pytest.raises(RuntimeError, match="database unreachable"):
            await _enter(lifespan_context)

    credential_close.assert_awaited_once()
    http_client_aclose.assert_awaited_once()
    call_automation_client_close.assert_awaited_once()


async def _enter(context: AbstractAsyncContextManager[None]) -> None:
    await context.__aenter__()
