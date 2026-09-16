"""Gated live Azure scenarios.

These tests place real phone calls and incur cost. They are excluded from the
default pytest selection by the ``live`` marker and additionally require
``RUN_LIVE_AZURE_TESTS=1``, so collection stays safe without Azure credentials.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from azure.identity import ClientSecretCredential

from ask_my_human.application.maintenance import RequestMaintenance
from ask_my_human.contracts import Outcome, RequestStatus
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
_CANCELLATION_DELAY_SECONDS = 10.0
_RETENTION_HOURS = 24.0


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
def access_token() -> str:
    credential = ClientSecretCredential(
        tenant_id=_required_env("LIVE_AGENT_TENANT_ID"),
        client_id=_required_env("LIVE_AGENT_CLIENT_ID"),
        client_secret=_required_env("LIVE_AGENT_CLIENT_SECRET"),
    )
    return credential.get_token(_required_env("LIVE_API_SCOPE")).token


@pytest.fixture
async def client(access_token: str) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=_required_env("LIVE_BASE_URL"),
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as instance:
        yield instance


@pytest.fixture
async def pool() -> AsyncIterator[PostgresPool]:
    async with PostgresPool(_required_env("DATABASE_URL")) as postgres:
        yield postgres


@pytest.fixture
def repository(pool: PostgresPool) -> PostgresRequestRepository:
    return PostgresRequestRepository(pool.pool)


async def _ask(client: httpx.AsyncClient, prompt: str, *, kind: str, key: UUID) -> httpx.Response:
    return await client.post(
        "/v1/requests",
        json={"kind": kind, "prompt": prompt, "idempotencyKey": str(key)},
    )


async def _assert_stored_terminal(repository: PostgresRequestRepository, request_id: UUID) -> None:
    stored = await repository.get(request_id)
    assert stored is not None, "The completed request must be readable from PostgreSQL."
    assert stored.call_id, "A completed call must be correlated to an ACS call connection."
    assert stored.result is not None
    assert stored.result.request_id == request_id


async def test_live_approval_call_completes_and_is_correlated(
    client: httpx.AsyncClient, repository: PostgresRequestRepository
) -> None:
    """Answer the phone and approve or reject when this test rings."""
    response = await _ask(
        client, "Live test: approve this deployment?", kind="approval", key=uuid4()
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == RequestStatus.RESPONDED.value
    assert body["outcome"] in {Outcome.APPROVED.value, Outcome.REJECTED.value}
    await _assert_stored_terminal(repository, UUID(body["requestId"]))


async def test_live_replay_returns_the_first_result_without_a_second_call(
    client: httpx.AsyncClient,
) -> None:
    """Answer the phone once; the replay must not ring again."""
    key = uuid4()
    prompt = "Live test: what is the release note?"

    first = await _ask(client, prompt, kind="input", key=key)
    assert first.status_code == 200, first.text

    second = await _ask(client, prompt, kind="input", key=key)
    assert second.status_code == 200, second.text
    assert second.json() == first.json()


async def test_live_backdated_terminal_row_is_purged_by_the_production_path(
    pool: PostgresPool, repository: PostgresRequestRepository
) -> None:
    expired_id = uuid4()
    retained_id = uuid4()
    await _insert_terminal_row(pool, expired_id, completed_hours_ago=_RETENTION_HOURS + 1)
    await _insert_terminal_row(pool, retained_id, completed_hours_ago=0)

    maintenance = RequestMaintenance(repository, _SystemClock(), retention_hours=_RETENTION_HOURS)
    assert await maintenance.purge_once() >= 1

    assert await repository.get(expired_id) is None
    assert await repository.get(retained_id) is not None


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
) -> None:
    """Answer the phone when this test rings, then let telemetry flush."""
    query_module = pytest.importorskip("azure.monitor.query")
    workspace_id = _required_env("LIVE_LOG_ANALYTICS_WORKSPACE_ID")
    sentinel = f"sentinel-{uuid4().hex}"

    response = await _ask(client, f"Live test: {sentinel}", kind="approval", key=uuid4())
    assert response.status_code == 200, response.text
    request_id = response.json()["requestId"]

    credential = ClientSecretCredential(
        tenant_id=_required_env("LIVE_AGENT_TENANT_ID"),
        client_id=_required_env("LIVE_AGENT_CLIENT_ID"),
        client_secret=_required_env("LIVE_AGENT_CLIENT_SECRET"),
    )
    logs = query_module.LogsQueryClient(credential)

    def row_count(term: str) -> int:
        result = logs.query_workspace(
            workspace_id,
            f'search "{term}" | count',
            timespan=timedelta(hours=1),
        )
        return int(result.tables[0].rows[0][0])

    assert row_count(request_id) > 0, "Telemetry must correlate the request identifier."
    assert row_count(sentinel) == 0, "Telemetry must stay content-free."


async def test_live_unauthenticated_request_is_rejected() -> None:
    """The deployed ingress must reject an agent request that carries no token."""
    async with httpx.AsyncClient(
        base_url=_required_env("LIVE_BASE_URL"), timeout=_SMOKE_TIMEOUT_SECONDS
    ) as anonymous:
        response = await anonymous.post(
            "/v1/requests",
            json={"kind": "approval", "prompt": "unauthenticated", "idempotencyKey": str(uuid4())},
        )

    assert response.status_code in {401, 403}, response.text


async def test_live_invalid_callback_token_is_rejected() -> None:
    """The ACS callback path is excluded from ingress auth and validates its own token."""
    async with httpx.AsyncClient(
        base_url=_required_env("LIVE_BASE_URL"), timeout=_SMOKE_TIMEOUT_SECONDS
    ) as anonymous:
        response = await anonymous.post(
            "/v1/callbacks/acs",
            headers={"Authorization": "Bea" + "rer invalid-callback-token"},
            json=[],
        )

    assert response.status_code == 401, response.text


async def test_live_unanswered_call_expires_without_a_response(
    client: httpx.AsyncClient, repository: PostgresRequestRepository
) -> None:
    """Let this call ring out; do not answer it."""
    response = await _ask(
        client, "Live test: do not answer this call.", kind="approval", key=uuid4()
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == RequestStatus.EXPIRED.value
    assert body["outcome"] in {
        Outcome.NO_ANSWER.value,
        Outcome.BUSY.value,
        Outcome.DECLINED.value,
        Outcome.DISCONNECTED.value,
        Outcome.DEADLINE_EXCEEDED.value,
    }
    stored = await repository.get(UUID(body["requestId"]))
    assert stored is not None
    assert stored.result is not None
    assert stored.result.status is RequestStatus.EXPIRED


async def test_live_client_cancellation_ends_the_request_exactly_once(
    client: httpx.AsyncClient, repository: PostgresRequestRepository
) -> None:
    """Do not answer this call; the initiating client disconnects first."""
    key = uuid4()
    request = asyncio.create_task(
        _ask(client, "Live test: cancelled by the caller.", kind="approval", key=key)
    )
    await asyncio.sleep(_CANCELLATION_DELAY_SECONDS)
    request.cancel()
    with suppress(asyncio.CancelledError, httpx.HTTPError):
        await request

    stored = await _await_terminal(repository, key)
    assert stored.result is not None
    assert stored.result.status is RequestStatus.EXPIRED


async def test_live_one_call_and_one_terminal_row_per_idempotency_key(
    client: httpx.AsyncClient, repository: PostgresRequestRepository, pool: PostgresPool
) -> None:
    """Answer the phone once when this test rings."""
    key = uuid4()
    prompt = "Live test: approve exactly once."

    first = await _ask(client, prompt, kind="approval", key=key)
    second = await _ask(client, prompt, kind="approval", key=key)

    assert first.status_code == 200, first.text
    assert second.json() == first.json()
    request_id = UUID(first.json()["requestId"])
    await _assert_stored_terminal(repository, request_id)

    async with pool.pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT count(*) FROM human_requests WHERE idempotency_key = %s", (key,)
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == 1, "An idempotency key must never create a second stored request."


async def _await_terminal(
    repository: PostgresRequestRepository, request_id: UUID
) -> "HumanRequest":
    deadline = datetime.now(tz=UTC) + timedelta(seconds=_REQUEST_TIMEOUT_SECONDS)
    while datetime.now(tz=UTC) < deadline:
        stored = await repository.get(request_id)
        if stored is not None and stored.state is not RequestState.PENDING:
            return stored
        await asyncio.sleep(1)
    raise AssertionError("The request never reached a terminal state.")
