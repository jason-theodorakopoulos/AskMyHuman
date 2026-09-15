"""Gated live Azure scenarios.

These tests place real phone calls and incur cost. They are excluded from the
default pytest selection by the ``live`` marker and additionally require
``RUN_LIVE_AZURE_TESTS=1``, so collection stays safe without Azure credentials.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from azure.identity import ClientSecretCredential

from ask_my_human.application.maintenance import RequestMaintenance
from ask_my_human.contracts import Outcome, RequestStatus
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


async def _assert_stored_terminal(
    repository: PostgresRequestRepository, request_id: UUID
) -> None:
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

    maintenance = RequestMaintenance(
        repository, _SystemClock(), retention_hours=_RETENTION_HOURS
    )
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
