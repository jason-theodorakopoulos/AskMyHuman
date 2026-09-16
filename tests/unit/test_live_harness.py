"""Credential-free regressions for the paid-call harness's fail-closed gates."""

import asyncio
import inspect
import json
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from azure.monitor.query import LogsQueryStatus
from e2e import test_live_call as harness

from ask_my_human.contracts import AskHumanRequest, AskHumanResult, Outcome
from ask_my_human.domain.models import HumanRequest, Principal, RequestState


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network and credential access are forbidden in harness unit tests.")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(harness, "ClientSecretCredential", blocked)
    monkeypatch.delenv("RUN_LIVE_AZURE_TESTS", raising=False)


def _body(**changes: object) -> dict[str, object]:
    return {
        "requestId": str(uuid4()),
        "status": "responded",
        "outcome": "approved",
        "answer": None,
    } | changes


@pytest.mark.parametrize(
    ("body", "outcome", "elapsed"),
    [
        (_body(outcome="rejected"), Outcome.APPROVED, 1),
        (_body(status="expired", outcome="no_answer"), Outcome.ANSWERED, 1),
        (_body(outcome="answered", answer="   "), Outcome.ANSWERED, 1),
        (_body(status="expired", outcome="disconnected"), Outcome.NO_ANSWER, 1),
        (_body(status="expired", outcome="deadline_exceeded"), Outcome.CANCELLED, 1),
        (_body(), Outcome.APPROVED, 210.01),
        (_body(extra="sensitive-value"), Outcome.APPROVED, 1),
    ],
)
def test_terminal_gate_rejects_false_positives(
    body: dict[str, object], outcome: Outcome, elapsed: float
) -> None:
    with pytest.raises(AssertionError):
        harness._validate_terminal_wire(body, outcome=outcome, elapsed=elapsed)


def test_terminal_gate_accepts_exact_result_at_deadline() -> None:
    body = _body()
    result = harness._validate_terminal_wire(body, outcome=Outcome.APPROVED, elapsed=210)
    assert result.model_dump(mode="json", by_alias=True) == body


def _evidence() -> tuple[dict[str, object], dict[str, object]]:
    now = datetime.now(tz=UTC)
    common: dict[str, object] = {
        "endpoint": "https://example.invalid",
        "image": "registry.invalid/app@sha256:" + "a" * 64,
        "revision": "reviewed-revision",
        "database_sha256": sha256(b"dummy-dsn").hexdigest(),
    }
    approval = common | {
        "record": "approval-123",
        "approver": "operator",
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "database_isolated": True,
        "decisions": {f"DR-0{number}": "approved-record" for number in range(1, 6)},
        "scenarios": {"test_example": "setup-record"},
        "provider_evidence_file": "/dummy/provider.json",
        "telemetry_workspace": "dummy-workspace",
        "telemetry_evidence_file": "/dummy/telemetry.json",
        "telemetry_settle_seconds": 60,
        "mcp_timeout_seconds": 225,
    }
    deployment = common | {
        "source": "az containerapp revision show",
        "captured_at": now.isoformat(),
        "active": True,
        "running_state": "Running",
        "health_state": "Healthy",
        "ready": True,
        "traffic_percent": 100,
    }
    return approval, deployment


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("approval", "endpoint", "http://example.invalid"),
        ("approval", "image", "registry.invalid/app:latest"),
        ("approval", "database_isolated", False),
        ("approval", "database_sha256", "0" * 64),
        ("approval", "decisions", {"DR-01": "approved"}),
        ("approval", "mcp_timeout_seconds", 210),
        ("approval", "expires_at", "2020-01-01T00:00:00Z"),
        ("deployment", "captured_at", "2020-01-01T00:00:00Z"),
        ("deployment", "captured_at", "2099-01-01T00:00:00Z"),
        ("deployment", "revision", "unreviewed"),
        ("deployment", "health_state", "Unhealthy"),
        ("deployment", "ready", False),
        ("deployment", "traffic_percent", 50),
    ],
)
def test_preflight_rejects_unapproved_targets(target: str, field: str, value: object) -> None:
    approval, deployment = _evidence()
    (approval if target == "approval" else deployment)[field] = value
    with pytest.raises(AssertionError, match="evidence"):
        harness._validate_preflight(
            json.dumps(approval),
            json.dumps(deployment),
            "https://example.invalid",
            "dummy-dsn",
            datetime.now(tz=UTC),
        )


def test_preflight_accepts_bound_fresh_evidence() -> None:
    approval, deployment = _evidence()
    result = harness._validate_preflight(
        json.dumps(approval),
        json.dumps(deployment),
        "https://example.invalid",
        "dummy-dsn",
        datetime.now(tz=UTC),
    )
    assert result.revision == "reviewed-revision"


@pytest.mark.parametrize("status", [200, 302, 404, 422, 500])
def test_auth_gate_rejects_missing_auth_enforcement(status: int) -> None:
    with pytest.raises(AssertionError, match="blocked"):
        harness._assert_auth_boundary(status, {401, 403})


def _stored() -> HumanRequest:
    now = datetime.now(tz=UTC)
    body = _body()
    result = AskHumanResult.model_validate(body)
    return HumanRequest(
        request_id=result.request_id,
        principal=Principal("dummy-agent", "dummy-app"),
        request=AskHumanRequest(kind="approval", prompt="dummy", idempotencyKey=uuid4()),
        request_hash="0" * 64,
        state=RequestState.RESPONDED,
        created_at=now,
        expires_at=now + timedelta(seconds=210),
        call_id="dummy-call",
        result=result,
    )


def _provider(stored: HumanRequest, *, attempts: int = 1) -> harness._ProviderEvidence:
    now = datetime.now(tz=UTC)
    return harness._ProviderEvidence(
        source="acs-http-dependency",
        record="export-record",
        revision="reviewed-revision",
        window_start=now - timedelta(minutes=5),
        complete_through=now,
        attempts=[
            harness._Attempt(
                request_id=stored.request_id,
                attempt_id=f"attempt-{number}",
                call_id="dummy-call",
            )
            for number in range(attempts)
        ],
        deliveries=[],
    )


@pytest.mark.parametrize("attempts", [0, 2])
def test_independent_call_count_rejects_missing_or_duplicate_attempts(attempts: int) -> None:
    stored = _stored()
    with pytest.raises(AssertionError, match="exactly one"):
        harness._assert_one_attempt(_provider(stored, attempts=attempts), stored)


def test_attempt_correlation_must_match_storage() -> None:
    stored = _stored()
    with pytest.raises(AssertionError, match="correlation"):
        harness._assert_one_attempt(_provider(stored), replace(stored, call_id="other-call"))


def test_concurrent_replay_cannot_pass_with_only_a_terminal_replay() -> None:
    stored = _stored()
    with pytest.raises(AssertionError, match="pending-join"):
        harness._assert_pending_join(
            _provider(stored),
            stored.request_id,
            started=stored.created_at,
            finished=stored.expires_at,
        )


def test_wire_storage_equality_is_complete() -> None:
    stored = _stored()
    assert stored.result is not None
    different = stored.result.model_copy(update={"outcome": Outcome.REJECTED})
    with pytest.raises(AssertionError, match="differs"):
        harness._assert_stored_matches(stored, different)


@pytest.mark.parametrize("elapsed", [0.1, 16])
def test_cancellation_rejects_deadline_or_late_result(elapsed: float) -> None:
    stored = _stored()
    result = AskHumanResult(
        requestId=stored.request_id,
        status="expired",
        outcome=Outcome.DEADLINE_EXCEEDED if elapsed < 1 else Outcome.CANCELLED,
    )
    with pytest.raises(AssertionError):
        harness._assert_cancelled(
            replace(stored, state=RequestState.EXPIRED, result=result), elapsed=elapsed
        )


@pytest.mark.parametrize("copies", [0, 1, 2])
def test_duplicate_callback_requires_distinct_delivery_after_terminal(copies: int) -> None:
    stored = _stored()
    evidence = _provider(stored)
    terminal_at = datetime.now(tz=UTC)
    evidence.deliveries = [
        harness._Delivery(
            request_id=stored.request_id,
            call_id="dummy-call",
            event_id="same-event",
            delivery_id=f"delivery-{number}",
            received_at=terminal_at - timedelta(seconds=1),
            accepted=True,
        )
        for number in range(copies)
    ]
    with pytest.raises(AssertionError, match="duplicate"):
        harness._assert_duplicate_evidence(evidence, stored, terminal_at)


def test_duplicate_callback_accepts_provider_receipts() -> None:
    stored = _stored()
    evidence = _provider(stored)
    terminal_at = datetime.now(tz=UTC)
    evidence.deliveries = [
        harness._Delivery(
            request_id=stored.request_id,
            call_id="dummy-call",
            event_id="same-event",
            delivery_id=f"delivery-{number}",
            received_at=terminal_at + timedelta(seconds=number),
            accepted=True,
        )
        for number in range(2)
    ]
    harness._assert_duplicate_evidence(evidence, stored, terminal_at)


@pytest.mark.parametrize(
    ("fixture", "required"),
    [
        ("access_token", "live_approval"),
        ("client", "live_preflight"),
        ("pool", "live_preflight"),
        ("mcp_session", "live_preflight"),
        ("client", "call_audit"),
        ("mcp_session", "call_audit"),
    ],
)
def test_paid_fixture_graph_cannot_bypass_gates(fixture: str, required: str) -> None:
    function = inspect.unwrap(getattr(harness, fixture))
    assert required in inspect.signature(function).parameters


def test_approval_checks_opt_in_before_reading_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = MagicMock(side_effect=AssertionError("Must not read live inputs without opt-in."))
    monkeypatch.setattr(harness, "_required_env", reader)
    with pytest.raises(pytest.fail.Exception, match="opt-in"):
        inspect.unwrap(harness.live_approval)()
    reader.assert_not_called()


async def test_pending_gate_rejects_already_completed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored()
    monkeypatch.setattr(harness, "_request_id_for", AsyncMock(return_value=stored.request_id))
    repository = MagicMock()
    repository.get = AsyncMock(return_value=stored)
    task = asyncio.create_task(asyncio.Event().wait())
    try:
        with pytest.raises(AssertionError, match="already terminated"):
            await harness._await_pending(repository, MagicMock(), uuid4(), task)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.parametrize("anonymous_status", [200, 302, 404, 401])
def test_preflight_uses_cost_free_dummy_requests(
    monkeypatch: pytest.MonkeyPatch,
    anonymous_status: int,
) -> None:
    approval, _ = _evidence()
    parsed = harness._Approval.model_validate_json(json.dumps(approval))
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200)
        if request.headers.get("authorization") == "Bearer dummy-access":
            return httpx.Response(422)
        return httpx.Response(anonymous_status)

    original_client = httpx.Client
    mock_transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(
            **kwargs,
            transport=mock_transport,
        ),
    )
    monkeypatch.setattr(harness, "_read_provider", MagicMock())
    monkeypatch.setattr(harness, "_telemetry_watermark", MagicMock())
    monkeypatch.setattr(harness, "_required_env", MagicMock(return_value="dummy-value"))
    monkeypatch.setattr(harness, "ClientSecretCredential", MagicMock())
    query = MagicMock()
    query.return_value.__enter__.return_value.query_workspace.return_value.status = (
        LogsQueryStatus.SUCCESS
    )
    monkeypatch.setattr(harness, "SyncLogsQueryClient", query)
    preflight = inspect.unwrap(harness.live_preflight)
    if anonymous_status == 401:
        assert preflight(parsed, "dummy-access", None) == parsed
    else:
        with pytest.raises(pytest.fail.Exception, match="preflight failed"):
            preflight(parsed, "dummy-access", None)
    assert calls
    for request in calls:
        if request.method == "POST":
            assert json.loads(request.content) in ({}, [])


@pytest.mark.parametrize("partial", [True, False])
async def test_telemetry_rejects_partial_or_invalid_counts(partial: bool) -> None:
    logs = MagicMock()
    result = MagicMock()
    result.status = "Partial" if partial else LogsQueryStatus.SUCCESS
    result.tables[0].rows = [[-1]]
    logs.query_workspace = AsyncMock(return_value=result)
    with pytest.raises(pytest.fail.Exception, match="suppressed") as failure:
        await harness._telemetry_count(logs, "dummy-workspace", "private-sentinel")
    assert "private-sentinel" not in str(failure.value)


async def test_telemetry_query_accepts_complete_counts() -> None:
    logs = MagicMock()
    result = MagicMock()
    result.status = LogsQueryStatus.SUCCESS
    result.tables[0].rows = [[0]]
    logs.query_workspace = AsyncMock(return_value=result)
    assert await harness._telemetry_count(logs, "dummy-workspace", "dummy-term") == 0


@pytest.mark.parametrize("insertion_fails", [False, True])
async def test_retention_tolerates_race_and_always_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    insertion_fails: bool,
) -> None:
    insert = AsyncMock(
        side_effect=[None, RuntimeError("dummy failure")] if insertion_fails else None
    )
    monkeypatch.setattr(harness, "_insert_terminal_row", insert)
    maintenance = MagicMock()
    maintenance.return_value.purge_once = AsyncMock(return_value=0)
    monkeypatch.setattr(harness, "RequestMaintenance", maintenance)
    repository = MagicMock()
    repository.get = AsyncMock(side_effect=[None, _stored()])
    pool = MagicMock()
    connection = pool.pool.connection.return_value.__aenter__.return_value
    connection.execute = AsyncMock()
    if insertion_fails:
        with pytest.raises(RuntimeError, match="dummy failure"):
            await harness.test_live_backdated_terminal_row_is_purged_by_the_production_path(
                pool,
                repository,
            )
    else:
        await harness.test_live_backdated_terminal_row_is_purged_by_the_production_path(
            pool,
            repository,
        )
    connection.execute.assert_awaited_once()
    statement, identifiers = connection.execute.call_args.args
    assert "DELETE FROM human_requests WHERE request_id IN" in statement
    assert len(identifiers) == 2


@pytest.mark.parametrize(
    "category",
    [
        "prompt",
        "answer",
        "phone",
        "idempotency",
        "authorization",
        "callback",
        "database",
        "connection_string",
        "delayed_prompt",
    ],
)
async def test_privacy_gate_rejects_every_sensitive_category_and_delayed_ingestion(
    monkeypatch: pytest.MonkeyPatch,
    category: str,
) -> None:
    approval, _ = _evidence()
    parsed = harness._Approval.model_validate_json(json.dumps(approval))
    original = _stored()
    result = AskHumanResult(
        requestId=original.request_id,
        status="responded",
        outcome=Outcome.ANSWERED,
        answer="spoken proof",
    )
    stored = replace(original, result=result)
    values = {
        "LIVE_SPOKEN_ANSWER_SENTINEL": "spoken proof",
        "LIVE_HUMAN_PHONE_NUMBER": "dummy-phone",
        "DATABASE_URL": "dummy-database",
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "dummy-connection",
    }
    needles = {
        "answer": "spoken proof",
        "phone": "dummy-phone",
        "database": "dummy-database",
        "connection_string": "dummy-connection",
        "authorization": "dummy-access",
    }

    async def ask(client: object, prompt: str, *, kind: str, key: object) -> httpx.Response:
        needles["prompt"] = prompt.split(":")[0]
        needles["idempotency"] = str(key)
        return httpx.Response(200, json=result.model_dump(mode="json", by_alias=True))

    async def callback(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(401)

    cycles = 0

    async def count(logs: object, workspace: str, term: str) -> int:
        nonlocal cycles
        if term.startswith("prompt-"):
            cycles += 1
        if term == str(stored.request_id):
            return 1
        if category == "delayed_prompt":
            return int(cycles >= 2 and term == needles["prompt"])
        if category == "callback":
            return int(term.startswith("callback-"))
        return int(term == needles[category])

    monkeypatch.setattr(harness, "_required_env", lambda name: values.get(name, "dummy"))
    monkeypatch.setattr(harness, "_ask", ask)
    monkeypatch.setattr(harness, "_assert_stored_terminal", AsyncMock(return_value=stored))
    monkeypatch.setattr(harness, "AsyncClientSecretCredential", MagicMock())
    monkeypatch.setattr(harness, "LogsQueryClient", MagicMock())
    monkeypatch.setattr(harness, "_telemetry_count", count)
    monkeypatch.setattr(harness, "_telemetry_watermark", lambda approval: datetime.now(tz=UTC))
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    client = MagicMock()
    client.post = callback
    with pytest.raises(pytest.fail.Exception, match="Sensitive"):
        await harness.test_live_telemetry_records_identifiers_but_no_prompt_content(
            client,
            parsed,
            MagicMock(),
            "dummy-access",
        )
