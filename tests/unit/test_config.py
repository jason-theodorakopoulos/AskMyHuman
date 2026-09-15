import pytest
from pydantic import ValidationError

from ask_my_human.config import Settings


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "******localhost:5432/askmyhuman",
        "acs_endpoint": "https://example.communication.azure.com",
        "acs_source_phone_number": "+15555550100",
        "my_mobile_number": "+15555550101",
        "azure_ai_endpoint": "https://example.cognitiveservices.azure.com",
        "acs_callback_audience": "https://askmyhuman.example.com",
        "entra_tenant_id": "tenant",
        "entra_client_id": "client",
        "authorized_agent_app_ids": ("agent",),
        "mcp_allowed_hosts": ("askmyhuman.example.com",),
    }
    values.update(overrides)
    return Settings(**values)


def test_settings_redact_database_url() -> None:
    credential = "test" + "-database-credential"
    configured = settings(database_url=f"postgresql://user:{credential}@localhost:5432/askmyhuman")
    assert credential not in repr(configured)
    assert configured.database_url.get_secret_value().endswith("/askmyhuman")


@pytest.mark.parametrize("field", ["acs_source_phone_number", "my_mobile_number"])
def test_settings_require_e164_numbers(field: str) -> None:
    with pytest.raises(ValidationError):
        settings(**{field: "555-555-0100"})


def test_settings_require_work_cutoff_before_deadline() -> None:
    with pytest.raises(ValidationError, match="work_cutoff_seconds"):
        settings(work_cutoff_seconds=210)
