import pytest

from ask_my_human.config import Settings


@pytest.fixture(autouse=True)
def isolate_local_configuration(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    if request.node.get_closest_marker("live") is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
        monkeypatch.setenv("ACS_CALLBACK_URL", "https://example.invalid/v1/callbacks/acs")
