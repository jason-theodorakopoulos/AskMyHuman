"""Gated live Azure scenarios.

These tests place real phone calls and incur cost. They are excluded from the
default pytest selection by the ``live`` marker and additionally require
``RUN_LIVE_AZURE_TESTS=1``, so collection stays safe without Azure credentials.
"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

import httpx
import httpx2
import pytest
from azure.identity import ClientSecretCredential
from azure.identity.aio import ClientSecretCredential as AsyncClientSecretCredential
from azure.monitor.query import LogsQueryClient as SyncLogsQueryClient
from azure.monitor.query import LogsQueryStatus
from azure.monitor.query.aio import LogsQueryClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ask_my_human.application.maintenance import RequestMaintenance
from ask_my_human.contracts import AskHumanResult, Outcome, RequestStatus
from ask_my_human.domain.models import HumanRequest, RequestState
from ask_my_human.persistence.pool import PostgresPool
from ask_my_human.persistence.repository import PostgresRequestRepository

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_AZURE_TESTS") != "1",
        reason="Live Azure tests require RUN_LIVE_AZURE_TESTS=1 and manual credentials.",
    ),
]

_REQUEST_TIMEOUT_SECONDS = 240.0
_SMOKE_TIMEOUT_SECONDS = 30.0
_INVALID_CALLBACK_AUTHORIZATION = "Bearer invalid-callback-token"  # noqa: S105 - test-only sentinel, not a credential
_CANCELLATION_TIMEOUT_SECONDS = 15.0
_RETENTION_HOURS = 24.0


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Approval(_EvidenceModel):
    record: str = Field(min_length=1)
    approver: str = Field(min_length=1)
    expires_at: datetime
    endpoint: str
    image: str = Field(pattern=r"^\S+@sha256:[0-9a-f]{64}$")
    revision: str = Field(min_length=1)
    database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_isolated: Literal[True]
    decisions: dict[str, str]
    scenarios: dict[str, str]
    provider_evidence_file: str = Field(min_length=1)
    telemetry_workspace: str = Field(min_length=1)
    telemetry_evidence_file: str = Field(min_length=1)
    telemetry_settle_seconds: int = Field(ge=60, le=600)
    mcp_timeout_seconds: int = Field(ge=225, le=240)


class _Deployment(_EvidenceModel):
    source: Literal["az containerapp revision show"]
    captured_at: datetime
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    endpoint: str
    image: str = Field(pattern=r"^\S+@sha256:[0-9a-f]{64}$")
    revision: str
    active: Literal[True]
    running_state: Literal["Running", "RunningAtMaxScale"]
    health_state: Literal["Healthy"]
    ready: Literal[True]
    traffic_percent: Literal[100]
    authentication_verified: Literal[True]
    paid_calls_authorized: Literal[False]

    @field_validator("authentication_verified", "paid_calls_authorized", mode="before")
    @classmethod
    def validate_proof_flags(cls, value: object) -> bool:
        if type(value) is not bool:
            raise ValueError("Verification proof flags must be JSON booleans.")
        return value


class _Attempt(_EvidenceModel):
    request_id: UUID
    attempt_id: str = Field(min_length=1)
    call_id: str = Field(min_length=1)


class _Delivery(_EvidenceModel):
    request_id: UUID
    call_id: str
    event_id: str
    delivery_id: str
    received_at: datetime
    accepted: Literal[True]


class _PendingJoin(_EvidenceModel):
    request_id: UUID
    event_id: str = Field(min_length=1)
    observed_at: datetime


class _ProviderEvidence(_EvidenceModel):
    source: Literal["acs-provider", "acs-http-dependency"]
    attempt_source: Literal["acs-provider"] = "acs-provider"
    delivery_source: Literal["content-free-app-telemetry"] = "content-free-app-telemetry"
    pending_join_source: Literal["content-free-app-telemetry"] = "content-free-app-telemetry"
    record: str = Field(min_length=1)
    revision: str
    window_start: datetime
    complete_through: datetime
    attempts: list[_Attempt]
    deliveries: list[_Delivery]
    pending_joins: list[_PendingJoin] = Field(default_factory=list)


class _TelemetryEvidence(_EvidenceModel):
    source: Literal["log-analytics-export"]
    record: str = Field(min_length=1)
    revision: str
    workspace: str
    complete_through: datetime


def _telemetry_watermark(approval: _Approval) -> datetime:
    try:
        evidence = _TelemetryEvidence.model_validate_json(
            Path(approval.telemetry_evidence_file).read_text()
        )
        if (
            evidence.revision != approval.revision
            or evidence.workspace != approval.telemetry_workspace
        ):
            raise ValueError
        if evidence.complete_through > datetime.now(tz=UTC):
            raise ValueError
        return evidence.complete_through
    except (OSError, ValueError, TypeError):
        raise AssertionError(
            "Telemetry export interval evidence is unavailable or invalid."
        ) from None


def _read_provider(approval: _Approval) -> _ProviderEvidence:
    try:
        evidence = _ProviderEvidence.model_validate_json(
            Path(approval.provider_evidence_file).read_text()
        )
        if evidence.revision != approval.revision or not (
            evidence.window_start <= evidence.complete_through <= datetime.now(tz=UTC)
        ):
            raise ValueError
        return evidence
    except (OSError, ValueError, TypeError):
        raise AssertionError("Authorized provider evidence is unavailable or invalid.") from None


def _assert_one_attempt(evidence: _ProviderEvidence, stored: HumanRequest) -> None:
    if stored.result is None or stored.state not in {RequestState.RESPONDED, RequestState.EXPIRED}:
        raise AssertionError("The accepted key has no public terminal result.")
    attempts = [item for item in evidence.attempts if item.request_id == stored.request_id]
    if len({item.attempt_id for item in attempts}) != 1:
        raise AssertionError("Provider evidence must prove exactly one actual ACS create attempt.")
    if any(item.call_id != stored.call_id for item in attempts):
        raise AssertionError("Provider evidence does not match the stored call correlation.")


class _CallAudit:
    def __init__(self) -> None:
        self.started = datetime.now(tz=UTC)
        self.keys: set[UUID] = set()

    def capture(self, content: bytes) -> None:
        body = json.loads(content)
        if body.get("method") == "tools/call":
            body = body["params"]["arguments"]
        if "idempotencyKey" in body:
            self.keys.add(UUID(body["idempotencyKey"]))


async def _await_provider(
    approval: _Approval,
    *,
    started: datetime,
    finished: datetime,
) -> _ProviderEvidence:
    async with asyncio.timeout(180):
        while True:
            evidence = _read_provider(approval)
            if evidence.window_start > started:
                raise AssertionError("Provider evidence misses the start of the call interval.")
            if evidence.complete_through >= finished:
                return evidence
            await asyncio.sleep(5)


@pytest.fixture
async def call_audit(
    live_preflight: _Approval,
    repository: PostgresRequestRepository,
    pool: PostgresPool,
) -> AsyncIterator[_CallAudit]:
    audit = _CallAudit()
    yield audit
    if not audit.keys:
        return
    evidence = await _await_provider(
        live_preflight,
        started=audit.started,
        finished=datetime.now(tz=UTC),
    )
    for key in audit.keys:
        stored = await _await_terminal(repository, pool, key, timeout=15)
        _assert_one_attempt(evidence, stored)
        async with pool.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT count(*) FROM human_requests WHERE idempotency_key = %s",
                (key,),
            )
            row = await cursor.fetchone()
        if row is None or row[0] != 1:
            raise AssertionError("An accepted key must have exactly one stored terminal row.")


def _validate_preflight(
    approval_json: str, deployment_json: str, endpoint: str, database: str, now: datetime
) -> _Approval:
    try:
        approval = _Approval.model_validate_json(approval_json)
        deployment = _Deployment.model_validate_json(deployment_json)
        address = httpx.URL(endpoint)
        valid_origin = (
            address.scheme == "https"
            and bool(address.host)
            and not address.userinfo
            and not address.query
            and not address.fragment
            and address.path == "/"
        )
        if not valid_origin or endpoint != approval.endpoint or endpoint != deployment.endpoint:
            raise ValueError
        if (
            approval.expires_at <= now
            or not 0 <= (now - deployment.captured_at).total_seconds() <= 900
        ):
            raise ValueError
        if any(
            getattr(approval, field) != getattr(deployment, field)
            for field in ("image", "revision")
        ):
            raise ValueError
        digest = deployment.image.rsplit("@sha256:", 1)[1]
        if not deployment.revision.endswith(f"--{deployment.source_sha[:12]}-{digest[:12]}"):
            raise ValueError
        if sha256(database.encode()).hexdigest() != approval.database_sha256:
            raise ValueError
        if set(approval.decisions) != {f"DR-0{number}" for number in range(1, 6)}:
            raise ValueError
        if not all(value.strip() for value in approval.decisions.values()):
            raise ValueError
        return approval
    except (ValueError, TypeError):
        raise AssertionError(
            "Live approval or deployment evidence is missing, stale, or mismatched."
        ) from None


@pytest.fixture(scope="session")
def live_approval() -> _Approval:
    if os.getenv("RUN_LIVE_AZURE_TESTS") != "1":
        pytest.fail("Live execution requires explicit opt-in.", pytrace=False)
    return _validate_preflight(
        _required_env("LIVE_APPROVAL_JSON"),
        _required_env("LIVE_DEPLOYMENT_EVIDENCE_JSON"),
        _required_env("LIVE_BASE_URL"),
        _required_env("DATABASE_URL"),
        datetime.now(tz=UTC),
    )


def _assert_auth_boundary(status: int, expected: set[int]) -> None:
    if status not in expected:
        raise AssertionError("Authentication preflight failed; paid calls are blocked.")


@pytest.fixture(scope="session", autouse=True)
def live_preflight(
    live_approval: _Approval,
    access_token: str,
    quiet_live_sdk: None,
) -> _Approval:
    try:
        _read_provider(live_approval)
        _telemetry_watermark(live_approval)
        with (
            ClientSecretCredential(
                tenant_id=_required_env("LIVE_AGENT_TENANT_ID"),
                client_id=_required_env("LIVE_AGENT_CLIENT_ID"),
                client_secret=_required_env("LIVE_AGENT_CLIENT_SECRET"),
            ) as credential,
            SyncLogsQueryClient(credential) as logs,
        ):
            query = logs.query_workspace(
                live_approval.telemetry_workspace,
                "print count=0",
                timespan=timedelta(minutes=1),
                server_timeout=30,
            )
            if query.status != LogsQueryStatus.SUCCESS:
                raise AssertionError("Required telemetry queries are unavailable.")
        with httpx.Client(base_url=live_approval.endpoint, timeout=_SMOKE_TIMEOUT_SECONDS) as probe:
            for headers in ({}, {"Authorization": "Bearer invalid-agent-token"}):
                for path in ("/v1/requests", "/mcp"):
                    response = probe.post(path, headers=headers, json={})
                    _assert_auth_boundary(response.status_code, {401, 403})
            callback = probe.post(
                "/v1/callbacks/acs",
                json=[],
                headers={"Authorization": _INVALID_CALLBACK_AUTHORIZATION},
            )
            _assert_auth_boundary(callback.status_code, {401})
            health = probe.get("/health/ready", headers={"Authorization": f"Bearer {access_token}"})
            _assert_auth_boundary(health.status_code, {200})
            authorized = probe.post(
                "/v1/requests", json={}, headers={"Authorization": f"Bearer {access_token}"}
            )
            _assert_auth_boundary(authorized.status_code, {400})
            if authorized.json().get("code") != "invalid_request":
                raise AssertionError("Authorized request validation preflight failed.")
    except Exception:
        pytest.fail(
            "Live authentication/readiness preflight failed (details suppressed).", pytrace=False
        )
    return live_approval


@pytest.fixture(scope="session")
def quiet_live_sdk() -> Iterator[None]:
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield None
    finally:
        logging.disable(previous)


@pytest.fixture(autouse=True)
def live_scenario(request: pytest.FixtureRequest, live_preflight: _Approval) -> None:
    record = live_preflight.scenarios.get(request.node.name, "")
    if not record.strip():
        pytest.fail(
            "Scenario lacks approved operator setup; live execution is blocked.", pytrace=False
        )


def _validate_terminal_wire(body: object, *, outcome: Outcome, elapsed: float) -> AskHumanResult:
    try:
        result = AskHumanResult.model_validate(body)
    except ValueError:
        raise AssertionError("Invalid terminal result (content suppressed).") from None
    if result.outcome is not outcome:
        raise AssertionError("Unexpected terminal outcome (content suppressed).")
    if not isinstance(body, dict) or result.model_dump(mode="json", by_alias=True) != {
        "answer": None,
        **body,
    }:
        raise AssertionError("The terminal wire result is not canonical (content suppressed).")
    if not 0 <= elapsed <= 210:
        raise AssertionError("The caller exceeded the 210-second terminal bound.")
    return result


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.fail(f"Live tests require {name} to be set.")
    return value


class _SystemClock:
    """Real clock for the production purge path; live tests never fake time."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)

    async def sleep(self, seconds: float) -> None:
        raise AssertionError("Live tests must not sleep through the maintenance loop.")


@pytest.fixture(scope="session")
def access_token(live_approval: _Approval, quiet_live_sdk: None) -> str:
    del live_approval
    with ClientSecretCredential(
        tenant_id=_required_env("LIVE_AGENT_TENANT_ID"),
        client_id=_required_env("LIVE_AGENT_CLIENT_ID"),
        client_secret=_required_env("LIVE_AGENT_CLIENT_SECRET"),
    ) as credential:
        return credential.get_token(_required_env("LIVE_API_SCOPE")).token


@pytest.fixture
async def client(
    access_token: str,
    live_preflight: _Approval,
    call_audit: _CallAudit,
) -> AsyncIterator[httpx.AsyncClient]:
    async def capture(request: httpx.Request) -> None:
        if request.method == "POST" and request.url.path == "/v1/requests":
            call_audit.capture(request.content)

    async with httpx.AsyncClient(
        base_url=live_preflight.endpoint,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_REQUEST_TIMEOUT_SECONDS,
        event_hooks={"request": [capture]},
    ) as instance:
        health = await instance.get("/health/ready", timeout=_SMOKE_TIMEOUT_SECONDS)
        assert health.status_code == 200, "Authenticated readiness preflight failed."
        yield instance


@pytest.fixture
async def pool(live_preflight: _Approval) -> AsyncIterator[PostgresPool]:
    del live_preflight
    async with PostgresPool(_required_env("DATABASE_URL")) as postgres:
        yield postgres


@pytest.fixture
def repository(pool: PostgresPool) -> PostgresRequestRepository:
    return PostgresRequestRepository(pool.pool)


async def _ask(client: httpx.AsyncClient, prompt: str, *, kind: str, key: UUID) -> httpx.Response:
    started = monotonic()
    response = await client.post(
        "/v1/requests",
        json={"kind": kind, "prompt": prompt, "idempotencyKey": str(key)},
    )
    assert monotonic() - started <= 210, "The request exceeded the product deadline."
    return response


def _assert_stored_matches(stored: HumanRequest | None, result: AskHumanResult) -> None:
    if stored is None or not stored.call_id or stored.result != result:
        raise AssertionError("Stored terminal result differs from the caller result.")


async def _assert_stored_terminal(
    repository: PostgresRequestRepository, body: object, *, outcome: Outcome
) -> HumanRequest:
    result = _validate_terminal_wire(body, outcome=outcome, elapsed=0)
    stored = await repository.get(result.request_id)
    _assert_stored_matches(stored, result)
    assert stored is not None
    if stored.result is None or stored.result.model_dump(
        mode="json", by_alias=True
    ) != result.model_dump(mode="json", by_alias=True):
        raise AssertionError("The complete stored and wire representations differ.")
    return stored


async def _telemetry_count(logs: LogsQueryClient, workspace: str, term: str) -> int:
    try:
        result = await logs.query_workspace(
            workspace,
            f"search * | where tostring(pack_all()) contains_cs {json.dumps(term)} | count",
            timespan=timedelta(hours=1),
            server_timeout=30,
        )
        if result.status != LogsQueryStatus.SUCCESS:
            raise ValueError
        value = result.tables[0].rows[0][0]
        if type(value) is not int or value < 0:
            raise ValueError
        return value
    except Exception:
        pytest.fail("Telemetry query failed (content suppressed).", pytrace=False)


@pytest.mark.parametrize("outcome", [Outcome.APPROVED, Outcome.REJECTED])
async def test_live_approval_call_completes_and_is_correlated(
    client: httpx.AsyncClient, repository: PostgresRequestRepository, outcome: Outcome
) -> None:
    """Answer the phone and give the decision requested by this scenario."""
    response = await _ask(
        client, f"Live test: respond with {outcome.value}.", kind="approval", key=uuid4()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == RequestStatus.RESPONDED.value
    assert body["outcome"] == outcome.value
    await _assert_stored_terminal(repository, body, outcome=outcome)


async def test_live_replay_returns_the_first_result_without_a_second_call(
    client: httpx.AsyncClient,
    repository: PostgresRequestRepository,
) -> None:
    """Answer the phone once; the replay must not ring again."""
    key = uuid4()
    prompt = "Live test: what is the release note?"

    first = await _ask(client, prompt, kind="input", key=key)
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == RequestStatus.RESPONDED.value
    assert body["outcome"] == Outcome.ANSWERED.value
    assert isinstance(body.get("answer"), str) and body["answer"].strip()
    await _assert_stored_terminal(repository, body, outcome=Outcome.ANSWERED)

    second = await _ask(client, prompt, kind="input", key=key)
    assert second.status_code == 200
    if second.json() != first.json():
        raise AssertionError("Replay changed the terminal result (content suppressed).")


async def test_live_backdated_terminal_row_is_purged_by_the_production_path(
    pool: PostgresPool, repository: PostgresRequestRepository
) -> None:
    expired_id = uuid4()
    retained_id = uuid4()
    try:
        await _insert_terminal_row(pool, expired_id, completed_hours_ago=_RETENTION_HOURS + 1)
        await _insert_terminal_row(pool, retained_id, completed_hours_ago=0)
        maintenance = RequestMaintenance(
            repository, _SystemClock(), retention_hours=_RETENTION_HOURS
        )
        await maintenance.purge_once()
        assert await repository.get(expired_id) is None
        assert await repository.get(retained_id) is not None
    finally:
        async with pool.pool.connection() as connection:
            await connection.execute(
                "DELETE FROM human_requests WHERE request_id IN (%s, %s)",
                (expired_id, retained_id),
            )


async def _insert_terminal_row(
    pool: PostgresPool, request_id: UUID, *, completed_hours_ago: float
) -> None:
    completed_at = datetime.now(tz=UTC) - timedelta(hours=completed_hours_ago)
    async with pool.pool.connection() as connection:
        await connection.execute(
            """
            INSERT INTO human_requests (
                request_id, subject_id, application_id, idempotency_key, request_hash,
                kind, prompt, status, outcome, answer, created_at, expires_at, completed_at
            ) VALUES (
                %s, 'live-retention', 'live-retention', %s, %s,
                'approval', 'retention probe', 'responded', 'approved', NULL, %s, %s, %s
            )
            """,
            (
                request_id,
                uuid4(),
                "0" * 64,
                completed_at,
                completed_at,
                completed_at,
            ),
        )


async def test_live_telemetry_records_identifiers_but_no_prompt_content(
    client: httpx.AsyncClient,
    live_preflight: _Approval,
    repository: PostgresRequestRepository,
    access_token: str,
) -> None:
    """Speak the approved answer sentinel; query every category across the export interval."""
    key = uuid4()
    sentinels = {
        "prompt": f"prompt-{uuid4().hex}",
        "answer": _required_env("LIVE_SPOKEN_ANSWER_SENTINEL"),
        "phone": _required_env("LIVE_HUMAN_PHONE_NUMBER"),
        "idempotency": str(key),
        "authorization": access_token,
        "callback": f"callback-{uuid4().hex}",
        "database": _required_env("DATABASE_URL"),
        "connection_string": _required_env("APPLICATIONINSIGHTS_CONNECTION_STRING"),
    }
    response = await _ask(
        client,
        f"{sentinels['prompt']}: please say {sentinels['answer']}",
        kind="input",
        key=key,
    )
    if response.status_code != 200:
        pytest.fail("Telemetry scenario did not produce a terminal result.", pytrace=False)
    stored = await _assert_stored_terminal(repository, response.json(), outcome=Outcome.ANSWERED)
    if (
        stored.result is None
        or sentinels["answer"].casefold() not in (stored.result.answer or "").casefold()
    ):
        pytest.fail("The spoken sentinel was not observed in the answer.", pytrace=False)
    callback = await client.post(
        "/v1/callbacks/acs",
        params={"token": sentinels["callback"]},
        json=[{"sentinel": sentinels["callback"]}],
        headers={"Authorization": _INVALID_CALLBACK_AUTHORIZATION},
    )
    _assert_auth_boundary(callback.status_code, {401})
    finished = datetime.now(tz=UTC)
    credential = AsyncClientSecretCredential(
        tenant_id=_required_env("LIVE_AGENT_TENANT_ID"),
        client_id=_required_env("LIVE_AGENT_CLIENT_ID"),
        client_secret=_required_env("LIVE_AGENT_CLIENT_SECRET"),
    )
    async with credential, LogsQueryClient(credential) as logs:

        async def row_count(term: str) -> int:
            return await _telemetry_count(logs, live_preflight.telemetry_workspace, term)

        try:
            async with asyncio.timeout(live_preflight.telemetry_settle_seconds + 180):
                started = monotonic()
                while True:
                    for category, sentinel in sentinels.items():
                        if await row_count(sentinel):
                            pytest.fail(
                                f"Sensitive {category} appeared in telemetry.", pytrace=False
                            )
                    correlated = await row_count(str(stored.request_id)) > 0
                    settled = monotonic() - started >= live_preflight.telemetry_settle_seconds
                    exported = _telemetry_watermark(live_preflight) >= finished
                    if correlated and settled and exported:
                        break
                    await asyncio.sleep(5)
        except TimeoutError:
            pytest.fail(
                "Telemetry ingestion evidence did not complete within the bound.", pytrace=False
            )


async def test_live_unauthenticated_request_is_rejected() -> None:
    """The deployed ingress must reject an agent request that carries no token."""
    async with httpx.AsyncClient(
        base_url=_required_env("LIVE_BASE_URL"), timeout=_SMOKE_TIMEOUT_SECONDS
    ) as anonymous:
        response = await anonymous.post(
            "/v1/requests",
            json={},
        )

    assert response.status_code in {401, 403}


async def test_live_invalid_callback_token_is_rejected() -> None:
    """The ACS callback path is excluded from ingress auth and validates its own token."""
    async with httpx.AsyncClient(
        base_url=_required_env("LIVE_BASE_URL"), timeout=_SMOKE_TIMEOUT_SECONDS
    ) as anonymous:
        response = await anonymous.post(
            "/v1/callbacks/acs",
            headers={"Authorization": _INVALID_CALLBACK_AUTHORIZATION},
            json=[],
        )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("scenario", "outcome"),
    [
        ("Leave the phone unanswered", Outcome.NO_ANSWER),
        ("Answer but remain silent", Outcome.NO_ANSWER),
        ("Make the destination busy", Outcome.BUSY),
        ("Decline the incoming call", Outcome.DECLINED),
        ("Answer and disconnect before responding", Outcome.DISCONNECTED),
        ("Use the operator-controlled deadline scenario", Outcome.DEADLINE_EXCEEDED),
    ],
)
async def test_live_unavailable_outcome(
    client: httpx.AsyncClient,
    repository: PostgresRequestRepository,
    scenario: str,
    outcome: Outcome,
) -> None:
    """Arrange the named scenario before invoking this individually selected test."""
    if outcome is Outcome.DEADLINE_EXCEEDED and os.getenv("LIVE_DEADLINE_SCENARIO_READY") != "1":
        pytest.fail("The forced-deadline scenario requires operator setup and approval.")
    response = await _ask(client, f"Live test: {scenario}.", kind="approval", key=uuid4())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == RequestStatus.EXPIRED.value
    assert body["outcome"] == outcome.value
    await _assert_stored_terminal(repository, body, outcome=outcome)


async def test_live_client_cancellation_ends_the_request_exactly_once(
    client: httpx.AsyncClient, repository: PostgresRequestRepository, pool: PostgresPool
) -> None:
    """Do not answer this call; the initiating client disconnects first."""
    key = uuid4()
    request = asyncio.create_task(
        _ask(client, "Live test: cancelled by the caller.", kind="approval", key=key)
    )
    try:
        await _await_pending(repository, pool, key, request)
        cancelled_at = monotonic()
        request.cancel()
        with suppress(asyncio.CancelledError, httpx.HTTPError):
            await request
        stored = await _await_terminal(repository, pool, key, timeout=_CANCELLATION_TIMEOUT_SECONDS)
        _assert_cancelled(stored, elapsed=monotonic() - cancelled_at)
        replay = await _ask(client, "Live test: cancelled by the caller.", kind="approval", key=key)
        await _assert_stored_terminal(repository, replay.json(), outcome=Outcome.CANCELLED)
    finally:
        request.cancel()
        with suppress(asyncio.CancelledError, httpx.HTTPError):
            await request


async def test_live_replay_has_one_terminal_row_per_idempotency_key(
    client: httpx.AsyncClient, repository: PostgresRequestRepository, pool: PostgresPool
) -> None:
    """Answer the phone once when this test rings."""
    key = uuid4()
    prompt = "Live test: approve exactly once."

    first = await _ask(client, prompt, kind="approval", key=key)
    second = await _ask(client, prompt, kind="approval", key=key)

    assert first.status_code == 200
    assert second.status_code == 200
    if second.json() != first.json():
        raise AssertionError("Replay changed the terminal result (content suppressed).")
    await _assert_stored_terminal(repository, first.json(), outcome=Outcome.APPROVED)

    async with pool.pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT count(*) FROM human_requests WHERE idempotency_key = %s", (key,)
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == 1, "An idempotency key must never create a second stored request."


async def _await_terminal(
    repository: PostgresRequestRepository,
    pool: PostgresPool,
    idempotency_key: UUID,
    *,
    timeout: float = 210,
) -> HumanRequest:
    """Wait for the request stored under an idempotency key to leave the pending state.

    A cancelled client never reads the response body, so the request identifier
    is only discoverable through the stored idempotency key.
    """
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        request_id = await _request_id_for(pool, idempotency_key)
        if request_id is not None:
            stored = await repository.get(request_id)
            if stored is not None and stored.state is not RequestState.PENDING:
                return stored
        await asyncio.sleep(1)
    raise AssertionError("The request never reached a terminal state.")


def _assert_cancelled(stored: HumanRequest, *, elapsed: float) -> None:
    if stored.result is None:
        raise AssertionError("Cancellation has no terminal result.")
    _validate_terminal_wire(
        stored.result.model_dump(mode="json", by_alias=True),
        outcome=Outcome.CANCELLED,
        elapsed=elapsed,
    )
    if elapsed > _CANCELLATION_TIMEOUT_SECONDS:
        raise AssertionError("Cancellation was not prompt.")


async def _await_pending(
    repository: PostgresRequestRepository,
    pool: PostgresPool,
    key: UUID,
    task: asyncio.Task[object],
) -> HumanRequest:
    async with asyncio.timeout(30):
        while True:
            if task.done():
                raise AssertionError("The invocation ended before pending could be observed.")
            request_id = await _request_id_for(pool, key)
            if request_id is not None:
                stored = await repository.get(request_id)
                if stored is not None:
                    if stored.state is not RequestState.PENDING:
                        raise AssertionError(
                            "The request already terminated before cancellation/join."
                        )
                    if stored.call_id:
                        return stored
            await asyncio.sleep(0.1)


@pytest.fixture
async def mcp_session(
    live_preflight: _Approval,
    access_token: str,
    client: httpx.AsyncClient,
    call_audit: _CallAudit,
) -> AsyncIterator[ClientSession]:
    del client

    async def capture(request: httpx2.Request) -> None:
        if request.method == "POST":
            call_audit.capture(request.content)

    async with (
        httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=live_preflight.mcp_timeout_seconds,
            event_hooks={"request": [capture]},
        ) as transport,
        streamable_http_client(
            live_preflight.endpoint.rstrip("/") + "/mcp", http_client=transport
        ) as (
            reader,
            writer,
        ),
        ClientSession(
            reader,
            writer,
            read_timeout_seconds=live_preflight.mcp_timeout_seconds,
        ) as session,
    ):
        await session.initialize()
        yield session


async def _mcp_ask(
    session: ClientSession,
    prompt: str,
    *,
    key: UUID,
    outcome: Outcome,
) -> dict[str, object]:
    started = monotonic()
    response = await session.call_tool(
        "ask_human", {"kind": "approval", "prompt": prompt, "idempotencyKey": str(key)}
    )
    if response.is_error:
        raise AssertionError("MCP returned an execution error (content suppressed).")
    result = _validate_terminal_wire(
        response.structured_content,
        outcome=outcome,
        elapsed=monotonic() - started,
    )
    return result.model_dump(mode="json", by_alias=True)


@pytest.mark.parametrize("outcome", [Outcome.APPROVED, Outcome.DEADLINE_EXCEEDED])
async def test_live_mcp_invoke_and_timeout(
    mcp_session: ClientSession,
    repository: PostgresRequestRepository,
    outcome: Outcome,
) -> None:
    body = await _mcp_ask(
        mcp_session,
        f"Live MCP test: arrange {outcome.value}.",
        key=uuid4(),
        outcome=outcome,
    )
    await _assert_stored_terminal(repository, body, outcome=outcome)


async def test_live_mcp_cancellation(
    mcp_session: ClientSession,
    repository: PostgresRequestRepository,
    pool: PostgresPool,
) -> None:
    key = uuid4()
    task = asyncio.create_task(
        _mcp_ask(
            mcp_session,
            "Live MCP test: cancel while pending.",
            key=key,
            outcome=Outcome.CANCELLED,
        )
    )
    try:
        await _await_pending(repository, pool, key, task)
        started = monotonic()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        stored = await _await_terminal(
            repository,
            pool,
            key,
            timeout=_CANCELLATION_TIMEOUT_SECONDS,
        )
        _assert_cancelled(stored, elapsed=monotonic() - started)
        replay = await _mcp_ask(
            mcp_session,
            "Live MCP test: cancel while pending.",
            key=key,
            outcome=Outcome.CANCELLED,
        )
        await _assert_stored_terminal(repository, replay, outcome=Outcome.CANCELLED)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def test_live_concurrent_replay(
    client: httpx.AsyncClient,
    repository: PostgresRequestRepository,
    pool: PostgresPool,
    live_preflight: _Approval,
) -> None:
    started = datetime.now(tz=UTC)
    key = uuid4()
    prompt = "Live concurrent replay: wait for both callers, then approve."
    first = asyncio.create_task(_ask(client, prompt, kind="approval", key=key))
    try:
        await _await_pending(repository, pool, key, first)
        second = await _ask(client, prompt, kind="approval", key=key)
        response = await first
        if response.status_code != 200 or second.status_code != 200:
            raise AssertionError("Concurrent replay failed.")
        if response.json() != second.json():
            raise AssertionError("Joined callers received different results.")
        stored = await _assert_stored_terminal(
            repository, response.json(), outcome=Outcome.APPROVED
        )
        finished = datetime.now(tz=UTC)
        evidence = await _await_provider(live_preflight, started=started, finished=finished)
        _assert_pending_join(evidence, stored.request_id, started=started, finished=finished)
    finally:
        first.cancel()
        with suppress(asyncio.CancelledError, httpx.HTTPError):
            await first


def _assert_pending_join(
    evidence: _ProviderEvidence,
    request_id: UUID,
    *,
    started: datetime,
    finished: datetime,
) -> None:
    if not any(
        item.request_id == request_id and started <= item.observed_at <= finished
        for item in evidence.pending_joins
    ):
        raise AssertionError("Concurrent replay lacks content-free pending-join evidence.")


def _assert_duplicate_evidence(
    evidence: _ProviderEvidence,
    stored: HumanRequest,
    terminal_at: datetime,
) -> None:
    deliveries = [
        item
        for item in evidence.deliveries
        if (item.request_id == stored.request_id and item.call_id == stored.call_id)
    ]
    for event_id in {item.event_id for item in deliveries}:
        copies = [item for item in deliveries if item.event_id == event_id]
        if len({item.delivery_id for item in copies}) >= 2 and any(
            item.received_at >= terminal_at for item in copies
        ):
            return
    raise AssertionError("No authorized, accepted duplicate callback after terminal completion.")


async def test_live_duplicate_callback_cannot_rewrite_terminal(
    client: httpx.AsyncClient,
    repository: PostgresRequestRepository,
    live_preflight: _Approval,
) -> None:
    """An authorized provider operator redelivers the callback, without a product test hook."""
    started = datetime.now(tz=UTC)
    response = await _ask(
        client,
        "Live duplicate-callback test: approve.",
        kind="approval",
        key=uuid4(),
    )
    if response.status_code != 200:
        raise AssertionError("Duplicate-callback scenario did not complete.")
    stored = await _assert_stored_terminal(repository, response.json(), outcome=Outcome.APPROVED)
    terminal_at = datetime.now(tz=UTC)
    async with asyncio.timeout(180):
        while True:
            evidence = await _await_provider(
                live_preflight,
                started=started,
                finished=terminal_at,
            )
            try:
                _assert_duplicate_evidence(evidence, stored, terminal_at)
            except AssertionError:
                await asyncio.sleep(5)
                continue
            break
    assert stored.result is not None
    _assert_stored_matches(await repository.get(stored.request_id), stored.result)


async def _request_id_for(pool: PostgresPool, idempotency_key: UUID) -> UUID | None:
    async with pool.pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT request_id FROM human_requests WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return UUID(str(row[0]))
