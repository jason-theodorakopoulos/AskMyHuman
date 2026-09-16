import pytest
from pydantic import ValidationError

from ask_my_human.config import Settings


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql://localhost:5432/askmyhuman",
        "acs_endpoint": "https://example.communication.azure.com",
        "acs_source_phone_number": "+15555550100",
        "my_mobile_number": "+15555550101",
        "azure_ai_endpoint": "https://example.cognitiveservices.azure.com",
        "acs_callback_url": "https://askmyhuman.example.com/v1/callbacks/acs",
        "acs_callback_audience": "00000000-0000-4000-8000-000000000001",
        "entra_tenant_id": "tenant",
        "entra_client_id": "client",
        "authorized_agent_app_ids": ("agent",),
        "mcp_allowed_hosts": ("askmyhuman.example.com",),
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_settings_redact_database_url() -> None:
    credential = "test" + "-database-credential"
    configured = settings(database_url=f"postgresql://user:{credential}@localhost:5432/askmyhuman")
    assert credential not in repr(configured)
    assert configured.database_url.get_secret_value().endswith("/askmyhuman")


def test_settings_redact_phone_numbers() -> None:
    source = "+15555550100"
    destination = "+15555550101"
    configured = settings(
        acs_source_phone_number=source,
        my_mobile_number=destination,
    )
    representation = repr(configured)
    assert source not in representation
    assert destination not in representation
    assert configured.acs_source_phone_number.get_secret_value() == source
    assert configured.my_mobile_number.get_secret_value() == destination


@pytest.mark.parametrize("field", ["acs_source_phone_number", "my_mobile_number"])
def test_settings_require_e164_numbers(field: str) -> None:
    invalid_phone = "555-555-0100"
    with pytest.raises(ValidationError) as exc_info:
        settings(**{field: invalid_phone})
    assert invalid_phone not in str(exc_info.value)


def test_settings_require_work_cutoff_before_deadline() -> None:
    with pytest.raises(ValidationError, match="work_cutoff_seconds"):
        settings(work_cutoff_seconds=210)


def test_settings_parse_comma_separated_allow_lists() -> None:
    configured = settings(
        authorized_agent_app_ids="agent-a, agent-b",
        mcp_allowed_hosts="one.example.com, two.example.com",
    )
    assert configured.authorized_agent_app_ids == ("agent-a", "agent-b")
    assert configured.mcp_allowed_hosts == ("one.example.com", "two.example.com")


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("authorized_agent_app_ids", "authorized_agent_app_ids"),
        ("mcp_allowed_hosts", "mcp_allowed_hosts"),
    ],
)
def test_settings_require_nonempty_allow_lists(field: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        settings(**{field: ()})


def test_settings_parse_comma_separated_allow_lists_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = {
        "DATABASE_URL": "postgresql://localhost:5432/askmyhuman",
        "ACS_ENDPOINT": "https://example.communication.azure.com",
        "ACS_SOURCE_PHONE_NUMBER": "+15555550100",
        "MY_MOBILE_NUMBER": "+15555550101",
        "AZURE_AI_ENDPOINT": "https://example.cognitiveservices.azure.com",
        "ACS_CALLBACK_URL": "https://askmyhuman.example.com/v1/callbacks/acs",
        "ACS_CALLBACK_AUDIENCE": "00000000-0000-4000-8000-000000000001",
        "ENTRA_TENANT_ID": "tenant",
        "ENTRA_CLIENT_ID": "client",
        "AUTHORIZED_AGENT_APP_IDS": "agent-a,agent-b",
        "MCP_ALLOWED_HOSTS": "one.example.com,two.example.com",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    configured = Settings()

    assert configured.authorized_agent_app_ids == ("agent-a", "agent-b")
    assert configured.mcp_allowed_hosts == ("one.example.com", "two.example.com")


@pytest.mark.parametrize("audience", ["", " ", "\n"])
def test_callback_audience_rejects_blank_identifiers(audience: str) -> None:
    with pytest.raises(ValidationError, match="acs_callback_audience"):
        settings(acs_callback_audience=audience)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1/callbacks/acs",
        "https://example.com",
        "https://user:password@example.com/v1/callbacks/acs",
        "https://example.com/v1/callbacks/acs?token=secret",
        "https://example.com/v1/callbacks/acs#fragment",
    ],
)
def test_callback_url_requires_a_full_https_endpoint(url: str) -> None:
    with pytest.raises(ValidationError, match="acs_callback_url"):
        settings(acs_callback_url=url)
