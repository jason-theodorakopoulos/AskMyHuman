"""Unit coverage for composition-root helpers that no integration test exercises."""

import asyncio
import base64
import json
from collections.abc import Mapping, MutableMapping
from typing import Any
from uuid import uuid4

import httpx
import pytest
from support.fakes import FakeAskHumanUseCase

from ask_my_human import main
from ask_my_human.config import Settings
from ask_my_human.contracts import AskHumanRequest, RequestKind
from ask_my_human.domain.models import CallEvent, CallEventType, Principal
from ask_my_human.errors import AskMyHumanError, ErrorCode
from ask_my_human.observability import AzureMonitorTelemetry

APPLICATION_ID = "11111111-1111-4111-8111-111111111111"

ENVIRONMENT = {
    "DATABASE_URL": "postgresql://user@localhost:5432/askmyhuman",
    "ACS_ENDPOINT": "https://test.communication.azure.com",
    "ACS_SOURCE_PHONE_NUMBER": "+15555550100",
    "MY_MOBILE_NUMBER": "+15555550101",
    "AZURE_AI_ENDPOINT": "https://test.cognitiveservices.azure.com",
    "ACS_CALLBACK_AUDIENCE": "https://askmyhuman.test",
    "ENTRA_TENANT_ID": "22222222-2222-4222-8222-222222222222",
    "ENTRA_CLIENT_ID": "33333333-3333-4333-8333-333333333333",
    "AUTHORIZED_AGENT_APP_IDS": APPLICATION_ID,
    "MCP_ALLOWED_HOSTS": "askmyhuman.test",
}


def apply_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(main.CONNECTION_STRING_VARIABLE, raising=False)


def principal_header(role: str = "AskHuman.Invoke") -> bytes:
    payload = {
        "auth_typ": "aad",
        "claims": [
            {"typ": "appid", "val": APPLICATION_ID},
            {"typ": "oid", "val": "agent-subject"},
            {"typ": "roles", "val": role},
        ],
    }
    return base64.b64encode(json.dumps(payload).encode())


def recognize_event(request_id: str) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": str(uuid4()),
        "source": "/calling/callConnections/call",
        "type": "Microsoft.Communication.RecognizeCompleted",
        "data": {
            "operationContext": request_id,
            "callConnectionId": "call",
            "choiceResult": {"label": "approve"},
        },
    }


def connected_event(request_id: str) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": str(uuid4()),
        "source": "/calling/callConnections/call",
        "type": "Microsoft.Communication.CallConnected",
        "data": {"operationContext": request_id, "callConnectionId": "call"},
    }


def test_load_settings_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    apply_environment(monkeypatch)

    settings = main.load_settings()

    assert settings.mcp_allowed_hosts == ("askmyhuman.test",)


def test_parse_callback_events_keeps_only_terminal_events() -> None:
    request_id = str(uuid4())

    events = main.parse_callback_events([connected_event(request_id), recognize_event(request_id)])

    assert [event.event_type for event in events] == [CallEventType.APPROVED]


def test_parse_callback_events_accepts_a_single_event_object() -> None:
    events = main.parse_callback_events(recognize_event(str(uuid4())))

    assert len(events) == 1


def test_parse_callback_events_rejects_non_object_items() -> None:
    with pytest.raises(ValueError, match="CloudEvent"):
        main.parse_callback_events(["not-an-object"])


@pytest.mark.asyncio
async def test_use_case_slot_reports_dependency_failure_before_startup() -> None:
    slot = main._UseCaseSlot()
    request = AskHumanRequest(kind=RequestKind.APPROVAL, prompt="Deploy?", idempotencyKey=uuid4())

    with pytest.raises(AskMyHumanError) as ask_error:
        await slot.ask(Principal(subject_id="s", application_id="a"), request, _Signal())
    with pytest.raises(AskMyHumanError):
        await slot.handle_call_event(
            CallEvent(request_id=uuid4(), event_type=CallEventType.APPROVED)
        )

    assert ask_error.value.code is ErrorCode.DEPENDENCY_FAILURE


@pytest.mark.asyncio
async def test_use_case_slot_delegates_once_bound() -> None:
    slot = main._UseCaseSlot()
    delegate = FakeAskHumanUseCase()
    slot.bind(delegate)
    request = AskHumanRequest(kind=RequestKind.APPROVAL, prompt="Deploy?", idempotencyKey=uuid4())

    await slot.ask(Principal(subject_id="s", application_id="a"), request, _Signal())
    await slot.handle_call_event(CallEvent(request_id=uuid4(), event_type=CallEventType.APPROVED))
    slot.unbind()

    assert len(delegate.requests) == 1
    assert len(delegate.events) == 1


@pytest.mark.asyncio
async def test_callback_validator_slot_requires_a_bound_validator() -> None:
    slot = main._CallbackValidatorSlot()

    with pytest.raises(AskMyHumanError) as error:
        await slot.validate("token")

    assert error.value.code is ErrorCode.DEPENDENCY_FAILURE


def test_pool_slot_is_closed_until_startup_binds_a_pool() -> None:
    slot = main._PoolSlot()

    assert slot.closed is True


@pytest.mark.asyncio
async def test_auth_context_middleware_ignores_non_http_scopes() -> None:
    seen: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        del receive, send
        seen.append(scope["type"])

    middleware = main._ClientPrincipalAuthContextMiddleware(app, (APPLICATION_ID,))

    await middleware({"type": "lifespan"}, _receive, _send)

    assert seen == ["lifespan"]


@pytest.mark.asyncio
async def test_auth_context_middleware_publishes_the_authorized_principal() -> None:
    from mcp.server.auth.middleware.auth_context import get_access_token

    subjects: list[str | None] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        del scope, receive, send
        token = get_access_token()
        subjects.append(None if token is None else token.subject)

    middleware = main._ClientPrincipalAuthContextMiddleware(app, (APPLICATION_ID,))
    scope = {"type": "http", "headers": [(b"x-ms-client-principal", principal_header())]}

    await middleware(scope, _receive, _send)

    assert subjects == ["agent-subject"]


@pytest.mark.asyncio
async def test_auth_context_middleware_leaves_unauthorized_requests_anonymous() -> None:
    from mcp.server.auth.middleware.auth_context import get_access_token

    tokens: list[object] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        del scope, receive, send
        tokens.append(get_access_token())

    middleware = main._ClientPrincipalAuthContextMiddleware(app, (APPLICATION_ID,))
    scope = {"type": "http", "headers": [(b"x-ms-client-principal", principal_header("other"))]}

    await middleware(scope, _receive, _send)

    assert tokens == [None]


def test_configure_telemetry_stays_in_process_without_a_connection_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(main.CONNECTION_STRING_VARIABLE, raising=False)

    assert isinstance(main._configure_telemetry(), AzureMonitorTelemetry)


def test_configure_telemetry_exports_when_a_connection_string_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    telemetry = AzureMonitorTelemetry()

    def configure(*, connection_string: str | None = None) -> AzureMonitorTelemetry:
        captured.append(str(connection_string))
        return telemetry

    monkeypatch.setenv(main.CONNECTION_STRING_VARIABLE, "InstrumentationKey=00000000")
    monkeypatch.setattr(main, "configure_observability", configure)

    assert main._configure_telemetry() is telemetry
    assert captured == ["InstrumentationKey=00000000"]


class _ClosingDouble:
    """Record whether the composition root closed this client exactly once."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1

    async def aclose(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_create_azure_runtime_builds_and_closes_every_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_environment(monkeypatch)
    settings = main.load_settings()
    built: list[_ClosingDouble] = []

    def record(*args: object, **kwargs: object) -> _ClosingDouble:
        double = _ClosingDouble()
        built.append(double)
        return double

    monkeypatch.setattr(main, "DefaultAzureCredential", record)
    monkeypatch.setattr(main, "CallAutomationClient", record)
    monkeypatch.setattr(httpx, "AsyncClient", record)

    runtime = await main.create_azure_runtime(settings)

    assert len(built) == 3
    assert [double.closed for double in built] == [0, 0, 0]

    await runtime.close()

    assert [double.closed for double in built] == [1, 1, 1]
    assert isinstance(runtime.telemetry, AzureMonitorTelemetry)


@pytest.mark.asyncio
async def test_stop_tasks_cancels_the_maintenance_loops() -> None:
    cancellation = main._LifespanCancellation()

    async def loop() -> None:
        await cancellation.wait()

    tasks = [asyncio.create_task(loop())]
    await main._stop_tasks(cancellation, tasks)

    assert cancellation.cancelled is True
    assert all(task.done() for task in tasks)


def test_module_attribute_builds_the_application_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_environment(monkeypatch)
    monkeypatch.delitem(main.__dict__, "app", raising=False)

    application = main.app

    paths = set(application.openapi()["paths"])
    assert {"/v1/requests", "/health/live", "/v1/callbacks/acs"} <= paths
    monkeypatch.delitem(main.__dict__, "app", raising=False)


def test_unknown_module_attribute_raises() -> None:
    with pytest.raises(AttributeError):
        main.missing_attribute  # noqa: B018


def test_settings_type_is_reused_by_the_composition_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_environment(monkeypatch)

    assert isinstance(main.load_settings(), Settings)


class _Signal:
    @property
    def cancelled(self) -> bool:
        return False

    async def wait(self) -> None:  # pragma: no cover - never awaited in these tests
        await asyncio.sleep(0)


async def _receive() -> MutableMapping[str, Any]:  # pragma: no cover - never awaited
    return {"type": "http.request"}


async def _send(message: Mapping[str, Any]) -> None:  # pragma: no cover - never awaited
    return None
