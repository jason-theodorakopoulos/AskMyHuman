"""Credential-free regressions for the paid-call harness's fail-closed gates."""

import asyncio
import inspect
import json
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from azure.monitor.query import LogsQueryStatus
from e2e import test_live_call as harness
from fastapi import FastAPI
from support.fakes import FakeAskHumanUseCase
from unit.test_deploy_script import Deployment
from unit.test_deploy_script import deployment as deployment
from unit.test_harvest_live_evidence import ACS_RESOURCE, APP_RESOURCE, REVISION, WORKSPACE

from ask_my_human.api.requests import create_requests_router
from ask_my_human.contracts import AskHumanRequest, AskHumanResult, Outcome, RequestStatus
from ask_my_human.domain.models import HumanRequest, Principal, RequestState
from ask_my_human.live_evidence import (
    ApplicationEvidence,
    CallbackDelivery,
    CallCorrelation,
    EvidenceSnapshot,
    ProviderAttempt,
    ProviderEvidence,
)


@pytest.fixture(autouse=True)
async def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network and credential access are forbidden in harness unit tests.")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(harness, "ClientSecretCredential", blocked)
    monkeypatch.delenv("RUN_LIVE_AZURE_TESTS", raising=False)


def test_network_and_credential_guard_remains_active() -> None:
    with socket.socket() as connection, pytest.raises(AssertionError, match="forbidden"):
        connection.connect(("127.0.0.1", 1))
    with pytest.raises(AssertionError, match="forbidden"):
        harness.ClientSecretCredential("dummy", "dummy", "dummy")


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
        (_body(outcome="answered", answer=" padded "), Outcome.ANSWERED, 1),
        (_body(outcome="answered", answer=123), Outcome.ANSWERED, 1),
        (_body(answer="unexpected"), Outcome.APPROVED, 1),
        (_body(status="expired"), Outcome.APPROVED, 1),
        (_body(requestId="AAAAAAAA-AAAA-4AAA-AAAA-AAAAAAAAAAAA"), Outcome.APPROVED, 1),
    ],
)
@pytest.mark.parametrize("omit_null_answer", [False, True])
def test_terminal_gate_rejects_false_positives(
    body: dict[str, object], outcome: Outcome, elapsed: float, omit_null_answer: bool
) -> None:
    if omit_null_answer and body.get("answer") is None:
        body = body.copy()
        body.pop("answer")
    with pytest.raises(AssertionError):
        harness._validate_terminal_wire(body, outcome=outcome, elapsed=elapsed)


def test_terminal_gate_accepts_exact_result_at_deadline() -> None:
    body = _body()
    result = harness._validate_terminal_wire(body, outcome=Outcome.APPROVED, elapsed=210)
    assert result.model_dump(mode="json", by_alias=True) == body


@pytest.mark.parametrize("exclude_none", [True, False], ids=["http", "mcp"])
@pytest.mark.parametrize("outcome", list(Outcome))
async def test_terminal_gate_accepts_canonical_wire_and_store(
    outcome: Outcome, exclude_none: bool
) -> None:
    stored = _stored()
    responded = outcome in {Outcome.APPROVED, Outcome.REJECTED, Outcome.ANSWERED}
    result = AskHumanResult(
        requestId=stored.request_id,
        status=RequestStatus.RESPONDED if responded else RequestStatus.EXPIRED,
        outcome=outcome,
        answer="spoken answer" if outcome is Outcome.ANSWERED else None,
    )
    stored = replace(
        stored,
        state=RequestState.RESPONDED if responded else RequestState.EXPIRED,
        result=result,
    )
    body = result.model_dump(mode="json", by_alias=True, exclude_none=exclude_none)
    repository = MagicMock()
    repository.get = AsyncMock(return_value=stored)
    assert harness._validate_terminal_wire(body, outcome=outcome, elapsed=210) == result
    assert await harness._assert_stored_terminal(repository, body, outcome=outcome) == stored
    repository.get.assert_awaited_once_with(result.request_id)


@pytest.mark.parametrize("field", ["requestId", "status", "outcome"])
def test_terminal_gate_rejects_missing_required_fields(field: str) -> None:
    body = _body()
    body.pop("answer")
    body.pop(field)
    with pytest.raises(AssertionError):
        harness._validate_terminal_wire(body, outcome=Outcome.APPROVED, elapsed=1)


@pytest.mark.parametrize("field", ["request_id", "status", "outcome", "answer"])
@pytest.mark.parametrize("exclude_none", [True, False], ids=["http", "mcp"])
async def test_terminal_gate_rejects_any_store_mismatch(field: str, exclude_none: bool) -> None:
    stored = _stored()
    assert stored.result is not None
    body = stored.result.model_dump(mode="json", by_alias=True, exclude_none=exclude_none)
    changes = {
        "request_id": uuid4(),
        "status": RequestStatus.EXPIRED,
        "outcome": Outcome.REJECTED,
        "answer": "unexpected answer",
    }
    repository = MagicMock()
    repository.get = AsyncMock(
        return_value=replace(
            stored, result=stored.result.model_copy(update={field: changes[field]})
        )
    )
    with pytest.raises(AssertionError, match="differs"):
        await harness._assert_stored_terminal(repository, body, outcome=Outcome.APPROVED)


def _evidence() -> tuple[dict[str, object], dict[str, object]]:
    now = datetime.now(tz=UTC)
    common: dict[str, object] = {
        "endpoint": "https://example.invalid",
        "image": "registry.invalid/app@sha256:" + "a" * 64,
        "revision": "reviewed-app--" + "b" * 12 + "-" + "a" * 12,
    }
    approval = common | {
        "record": "approval-123",
        "approver": "operator",
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "database_sha256": sha256(b"dummy-dsn").hexdigest(),
        "database_isolated": True,
        "decisions": {f"DR-0{number}": "approved-record" for number in range(1, 6)},
        "scenarios": {"test_example": "setup-record"},
        "evidence_file": "/dummy/evidence.json",
        "evidence_review_file": "/dummy/review.json",
        "evidence_reviewer": "approved-reviewer",
        "acs_resource_id": ACS_RESOURCE,
        "application_insights_resource_id": APP_RESOURCE,
        "telemetry_workspace": str(WORKSPACE),
        "telemetry_settle_seconds": 60,
        "mcp_timeout_seconds": 225,
    }
    deployment = common | {
        "source": "az containerapp revision show",
        "captured_at": now.isoformat(),
        "source_sha": "b" * 40,
        "active": True,
        "running_state": "Running",
        "health_state": "Healthy",
        "ready": True,
        "traffic_percent": 100,
        "authentication_verified": True,
        "paid_calls_authorized": False,
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
    assert result.revision == approval["revision"]


@pytest.fixture
def verified_deployment(deployment: Deployment) -> dict[str, object]:
    deployment.verification()
    response = deployment.run("verify")
    assert response.returncode == 0, response.stderr
    evidence: dict[str, object] = json.loads(response.stdout)
    assert "database_sha256" not in evidence
    assert evidence["authentication_verified"] is True
    assert evidence["paid_calls_authorized"] is False
    assert not any(
        call["args"][:2] == ["acr", "build"]
        or call["args"][:3] == ["deployment", "group", "create"]
        for call in deployment.calls("az")
    )
    return evidence


def test_preflight_accepts_actual_verifier_output_with_separate_database_approval(
    verified_deployment: dict[str, object],
) -> None:
    approval, _ = _evidence()
    approval.update(
        {field: verified_deployment[field] for field in ("endpoint", "image", "revision")}
    )
    result = harness._validate_preflight(
        json.dumps(approval),
        json.dumps(verified_deployment),
        "https://app.invalid",
        "dummy-dsn",
        datetime.now(tz=UTC),
    )
    assert result.database_sha256 == sha256(b"dummy-dsn").hexdigest()
    assert result.database_isolated is True
    assert result.revision == verified_deployment["revision"]


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("deployment", "source", "unverified"),
        ("deployment", "source_sha", "not-a-sha"),
        ("deployment", "source_sha", "c" * 40),
        ("deployment", "image", "registry.invalid/app@sha256:" + "c" * 64),
        ("deployment", "revision", "other-revision"),
        ("deployment", "endpoint", "https://other.invalid"),
        ("deployment", "captured_at", "2020-01-01T00:00:00Z"),
        ("deployment", "authentication_verified", False),
        ("deployment", "authentication_verified", 1),
        ("deployment", "authentication_verified", "true"),
        ("deployment", "paid_calls_authorized", True),
        ("deployment", "paid_calls_authorized", 0),
        ("deployment", "extra", "unreviewed"),
        ("approval", "database_sha256", "0" * 64),
        ("approval", "database_isolated", False),
    ],
)
def test_preflight_rejects_mutated_verifier_handoff(
    verified_deployment: dict[str, object], target: str, field: str, value: object
) -> None:
    approval, _ = _evidence()
    approval.update(
        {field: verified_deployment[field] for field in ("endpoint", "image", "revision")}
    )
    (approval if target == "approval" else verified_deployment)[field] = value
    with pytest.raises(AssertionError, match="evidence"):
        harness._validate_preflight(
            json.dumps(approval),
            json.dumps(verified_deployment),
            "https://app.invalid",
            "dummy-dsn",
            datetime.now(tz=UTC),
        )


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("deployment", "authentication_verified"),
        ("deployment", "paid_calls_authorized"),
        ("deployment", "source_sha"),
        ("approval", "database_sha256"),
        ("approval", "database_isolated"),
        ("approval", "record"),
        ("approval", "decisions"),
    ],
)
def test_preflight_requires_independent_approval_and_verification_fields(
    verified_deployment: dict[str, object], target: str, field: str
) -> None:
    approval, _ = _evidence()
    approval.update(
        {field: verified_deployment[field] for field in ("endpoint", "image", "revision")}
    )
    (approval if target == "approval" else verified_deployment).pop(field)
    with pytest.raises(AssertionError, match="evidence"):
        harness._validate_preflight(
            json.dumps(approval),
            json.dumps(verified_deployment),
            "https://app.invalid",
            "dummy-dsn",
            datetime.now(tz=UTC),
        )


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
        request=AskHumanRequest(
            kind="approval",
            prompt="dummy",
            idempotencyKey=uuid4(),
            phoneNumber="+15555550101",
        ),
        request_hash="0" * 64,
        state=RequestState.RESPONDED,
        created_at=now,
        expires_at=now + timedelta(seconds=210),
        call_id="dummy-call",
        result=result,
    )


def _provider(stored: HumanRequest, *, attempts: int = 1) -> EvidenceSnapshot:
    now = datetime.now(tz=UTC)
    call_hash = sha256(b"dummy-call").hexdigest()
    return EvidenceSnapshot(
        record="export-record",
        revision=REVISION,
        workspace=WORKSPACE,
        acs_resource_id=ACS_RESOURCE,
        application_insights_resource_id=APP_RESOURCE,
        window_start=now - timedelta(minutes=5),
        window_end=now,
        queried_at=now,
        provider_query_sha256="a" * 64,
        application_query_sha256="b" * 64,
        provider=ProviderEvidence(
            attempts=[
                ProviderAttempt(
                    call_id_sha256=call_hash,
                    correlation_id_sha256="c" * 64,
                    observed_at=now,
                    result_code=201,
                )
                for _ in range(attempts)
            ]
        ),
        application=ApplicationEvidence(
            correlations=[
                CallCorrelation(
                    request_id=stored.request_id,
                    call_id_sha256=call_hash,
                    observed_at=now,
                )
            ]
            if attempts
            else [],
            deliveries=[],
            pending_joins=[],
        ),
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
    terminal_at = evidence.window_end - timedelta(seconds=2)
    evidence.application.deliveries = [
        CallbackDelivery(
            request_id=stored.request_id,
            call_id_sha256=sha256(b"dummy-call").hexdigest(),
            event_id_sha256=sha256(b"same-event").hexdigest(),
            delivery_id=uuid4(),
            received_at=terminal_at - timedelta(seconds=1),
            observed_at=terminal_at - timedelta(seconds=1),
        )
        for _ in range(copies)
    ]
    with pytest.raises(AssertionError, match="duplicate"):
        harness._assert_duplicate_evidence(evidence, stored, terminal_at)


def test_duplicate_callback_accepts_application_receipts() -> None:
    stored = _stored()
    evidence = _provider(stored)
    terminal_at = evidence.window_end - timedelta(seconds=2)
    evidence.application.deliveries = [
        CallbackDelivery(
            request_id=stored.request_id,
            call_id_sha256=sha256(b"dummy-call").hexdigest(),
            event_id_sha256=sha256(b"same-event").hexdigest(),
            delivery_id=uuid4(),
            received_at=terminal_at + timedelta(seconds=number),
            observed_at=terminal_at + timedelta(seconds=number),
        )
        for number in range(2)
    ]
    harness._assert_duplicate_evidence(evidence, stored, terminal_at)


@pytest.mark.parametrize("mutate", [False, True])
def test_harness_requires_the_approved_review_of_exact_export_bytes(
    tmp_path: Path,
    mutate: bool,
) -> None:
    evidence = _provider(_stored())
    raw = evidence.model_dump_json().encode()
    snapshot_file = tmp_path / "evidence.json"
    review_file = tmp_path / "review.json"
    snapshot_file.write_bytes(raw + (b"\n" if mutate else b""))
    review_file.write_text(
        json.dumps(
            {
                "source": "operator-export-review",
                "record": "review-record",
                "reviewer": "approved-reviewer",
                "snapshot_sha256": sha256(raw).hexdigest(),
                "reviewed_at": datetime.now(tz=UTC).isoformat(),
                "diagnostics_verified": True,
                "sampling_disabled": True,
                "ingestion_checked": True,
                "late_arrival_risk_accepted": True,
            }
        )
    )
    approval, _ = _evidence()
    approval.update({"evidence_file": str(snapshot_file), "evidence_review_file": str(review_file)})
    parsed = harness._Approval.model_validate_json(json.dumps(approval))
    if mutate:
        with pytest.raises(AssertionError, match="Reviewed"):
            harness._read_evidence(parsed)
        assert (
            harness._read_interval_evidence(
                parsed, started=evidence.window_start, finished=evidence.window_end
            )
            is None
        )
    else:
        assert harness._read_evidence(parsed) == evidence
        assert (
            harness._read_interval_evidence(
                parsed, started=evidence.window_start, finished=evidence.window_end
            )
            == evidence
        )


async def test_evidence_refresh_waits_for_a_matching_review_and_full_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _provider(_stored())
    approval, _ = _evidence()
    parsed = harness._Approval.model_validate_json(json.dumps(approval))
    earlier = evidence.model_copy(update={"window_end": evidence.window_end - timedelta(seconds=1)})
    read = MagicMock(side_effect=[AssertionError("review not yet published"), earlier, evidence])
    pause = AsyncMock()
    monkeypatch.setattr(harness, "_read_evidence", read)
    monkeypatch.setattr(asyncio, "sleep", pause)
    assert (
        await harness._await_evidence(
            parsed, started=evidence.window_start, finished=evidence.window_end
        )
        == evidence
    )
    assert read.call_count == 3
    assert pause.await_count == 2


def test_evidence_refresh_rejects_a_window_missing_the_scenario_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _provider(_stored())
    approval, _ = _evidence()
    parsed = harness._Approval.model_validate_json(json.dumps(approval))
    monkeypatch.setattr(harness, "_read_evidence", MagicMock(return_value=evidence))
    with pytest.raises(AssertionError, match="misses the start"):
        harness._read_interval_evidence(
            parsed,
            started=evidence.window_start - timedelta(seconds=1),
            finished=evidence.window_end,
        )


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


@pytest.fixture
async def invalid_request_response() -> httpx.Response:
    use_case = FakeAskHumanUseCase()
    app = FastAPI()
    app.include_router(
        create_requests_router(
            use_case=use_case,
            authenticate=AsyncMock(return_value=Principal("dummy-agent", "dummy-app")),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://example.invalid"
    ) as client:
        response = await client.post("/v1/requests", json={})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert use_case.requests == []
    return response


@pytest.mark.parametrize("anonymous_status", [200, 302, 404, 401])
@pytest.mark.parametrize("authorized_status", [400, 422])
@pytest.mark.parametrize("authorized_code", ["invalid_request", "forbidden"])
def test_preflight_uses_cost_free_dummy_requests(
    monkeypatch: pytest.MonkeyPatch,
    anonymous_status: int,
    authorized_status: int,
    authorized_code: str,
    invalid_request_response: httpx.Response,
) -> None:
    approval, _ = _evidence()
    parsed = harness._Approval.model_validate_json(json.dumps(approval))
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200)
        if request.headers.get("authorization") == "Bearer dummy-access":
            if authorized_status == 400 and authorized_code == "invalid_request":
                return httpx.Response(
                    invalid_request_response.status_code, content=invalid_request_response.content
                )
            return httpx.Response(
                authorized_status,
                json=invalid_request_response.json() | {"code": authorized_code},
            )
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
    monkeypatch.setattr(harness, "_read_evidence", MagicMock())
    monkeypatch.setattr(harness, "_required_env", MagicMock(return_value="dummy-value"))
    monkeypatch.setattr(harness, "ClientSecretCredential", MagicMock())
    query = MagicMock()
    query.return_value.__enter__.return_value.query_workspace.return_value.status = (
        LogsQueryStatus.SUCCESS
    )
    monkeypatch.setattr(harness, "SyncLogsQueryClient", query)
    preflight = inspect.unwrap(harness.live_preflight)
    if (
        anonymous_status == 401
        and authorized_status == 400
        and authorized_code == "invalid_request"
    ):
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
    monkeypatch.setattr(harness, "_read_interval_evidence", MagicMock(return_value=None))
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
