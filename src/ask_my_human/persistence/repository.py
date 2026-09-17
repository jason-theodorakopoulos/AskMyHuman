"""Atomic PostgreSQL implementation of the request repository."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, nullcontext
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ask_my_human.application.ports import Admission, Telemetry, TelemetryOperation
from ask_my_human.contracts import (
    AskHumanRequest,
    AskHumanResult,
    Outcome,
    RequestKind,
    RequestStatus,
)
from ask_my_human.domain.models import HumanRequest, Principal, RequestState
from ask_my_human.errors import ErrorCode

_COLUMNS = """
request_id, subject_id, application_id, idempotency_key, request_hash, kind, prompt,
phone_number, status, outcome, answer, error_code, error_message, acs_call_connection_id,
created_at, expires_at, completed_at, recognition_started
"""


class PostgresRequestRepository:
    def __init__(self, pool: AsyncConnectionPool[Any], telemetry: Telemetry | None = None) -> None:
        self._pool = pool
        self._telemetry = telemetry

    @asynccontextmanager
    async def _connection(
        self, request_id: UUID | None = None
    ) -> AsyncIterator[AsyncConnection[Any]]:
        span = (
            self._telemetry.span(TelemetryOperation.REPOSITORY, request_id=request_id or uuid4())
            if self._telemetry is not None
            else nullcontext()
        )
        with span:
            try:
                async with self._pool.connection() as connection:
                    yield connection
            except Exception:
                if self._telemetry is not None:
                    self._telemetry.dependency_failed(
                        TelemetryOperation.REPOSITORY, error_code=ErrorCode.DEPENDENCY_FAILURE
                    )
                raise

    async def create_or_replay(
        self,
        principal: Principal,
        request: AskHumanRequest,
        request_hash: str,
        expires_at: datetime,
    ) -> tuple[Admission, HumanRequest]:
        request_id = uuid4()
        async with self._connection(request_id) as connection:
            row = await self._insert_pending(
                connection,
                request_id,
                principal,
                request,
                request_hash,
                expires_at,
            )
            if row is not None:
                return "created", self._to_domain(row)

            existing = await self._get_by_idempotency(
                connection, principal.subject_id, request.idempotency_key
            )
            if existing is not None:
                item = self._to_domain(existing)
                if item.request_hash != request_hash:
                    return "conflict", item
                if item.state is RequestState.PENDING:
                    return "joined_pending", item
                return "replayed", item

        attempted = HumanRequest(
            request_id=request_id,
            principal=principal,
            request=request,
            request_hash=request_hash,
            state=RequestState.PENDING,
            created_at=datetime.now(tz=UTC),
            expires_at=expires_at,
        )
        return "pending_admission_lost", attempted

    async def attach_call_id(self, request_id: UUID, call_id: str) -> bool:
        async with self._connection(request_id) as connection:
            cursor = await connection.execute(
                """
                UPDATE human_requests
                SET acs_call_connection_id = %s
                WHERE request_id = %s
                  AND status = 'pending'
                  AND (acs_call_connection_id IS NULL OR acs_call_connection_id = %s)
                """,
                (call_id, request_id, call_id),
            )
            return int(cursor.rowcount) == 1

    async def claim_recognition(self, request_id: UUID) -> bool:
        async with self._connection(request_id) as connection:
            cursor = await connection.execute(
                """
                UPDATE human_requests SET recognition_started = TRUE
                WHERE request_id = %s AND status = 'pending'
                  AND acs_call_connection_id IS NOT NULL AND recognition_started = FALSE
                  AND now() < expires_at
                """,
                (request_id,),
            )
            return int(cursor.rowcount) == 1

    async def get(self, request_id: UUID) -> HumanRequest | None:
        async with (
            self._connection(request_id) as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            await cursor.execute(
                f"SELECT {_COLUMNS} FROM human_requests WHERE request_id = %s",
                (request_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else self._to_domain(row)

    async def complete_if_pending(
        self,
        result: AskHumanResult,
        *,
        before: datetime | None = None,
    ) -> bool:
        async with self._connection(result.request_id) as connection:
            cursor = await connection.execute(
                """
                UPDATE human_requests
                SET status = %s, outcome = %s, answer = %s, completed_at = now()
                WHERE request_id = %s AND status = 'pending'
                                    AND (%s <> 'responded' OR (
                                            now() < expires_at
                                            AND clock_timestamp() < expires_at
                                            AND clock_timestamp() < COALESCE(%s, expires_at)
                                            AND ((kind = 'approval'
                                                AND %s IN ('approved', 'rejected'))
                                                OR (kind = 'input' AND %s = 'answered'))
                                    ))
                """,
                (
                    result.status.value,
                    result.outcome.value,
                    result.answer,
                    result.request_id,
                    result.status.value,
                    before,
                    result.outcome.value,
                    result.outcome.value,
                ),
            )
            return int(cursor.rowcount) == 1

    async def complete_error_if_pending(
        self,
        request_id: UUID,
        error_code: ErrorCode,
        error_message: str,
    ) -> bool:
        async with self._connection(request_id) as connection:
            cursor = await connection.execute(
                """
                UPDATE human_requests
                SET status = 'failed', error_code = %s, error_message = %s,
                    completed_at = now()
                WHERE request_id = %s AND status = 'pending'
                """,
                (error_code.value, error_message, request_id),
            )
            return int(cursor.rowcount) == 1

    async def expire_stale(self, now: datetime) -> int:
        return len(await self.expire_stale_calls(now))

    async def expire_stale_calls(self, now: datetime) -> Sequence[HumanRequest]:
        async with (
            self._connection() as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            await cursor.execute(
                f"""
                UPDATE human_requests
                SET status = 'expired', outcome = 'deadline_exceeded', completed_at = %s
                WHERE status = 'pending' AND expires_at <= %s
                RETURNING {_COLUMNS}
                """,
                (now, now),
            )
            return [self._to_domain(row) for row in await cursor.fetchall()]

    async def pending_count(self) -> int:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT count(*) FROM human_requests WHERE status = 'pending'"
            )
            row = await cursor.fetchone()
            return int(row[0]) if row is not None else 0

    async def purge_terminal(self, before: datetime) -> int:
        async with self._connection() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM human_requests
                WHERE status <> 'pending' AND completed_at < %s
                """,
                (before,),
            )
            return int(cursor.rowcount)

    async def _insert_pending(
        self,
        connection: AsyncConnection[Any],
        request_id: UUID,
        principal: Principal,
        request: AskHumanRequest,
        request_hash: str,
        expires_at: datetime,
    ) -> dict[str, Any] | None:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                f"""
                INSERT INTO human_requests (
                    request_id, subject_id, application_id, idempotency_key, request_hash,
                    kind, prompt, phone_number, status, created_at, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', now(), %s)
                ON CONFLICT DO NOTHING
                RETURNING {_COLUMNS}
                """,
                (
                    request_id,
                    principal.subject_id,
                    principal.application_id,
                    request.idempotency_key,
                    request_hash,
                    request.kind.value,
                    request.prompt,
                    request.phone_number,
                    expires_at,
                ),
            )
            return await cursor.fetchone()

    async def _get_by_idempotency(
        self,
        connection: AsyncConnection[Any],
        subject_id: str,
        idempotency_key: UUID,
    ) -> dict[str, Any] | None:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                f"""
                SELECT {_COLUMNS}
                FROM human_requests
                WHERE subject_id = %s AND idempotency_key = %s
                """,
                (subject_id, idempotency_key),
            )
            return await cursor.fetchone()

    @staticmethod
    def _to_domain(row: dict[str, Any]) -> HumanRequest:
        if row["phone_number"] is None:
            raise RuntimeError("Legacy request has no callable destination")
        result = None
        if row["status"] in {RequestState.RESPONDED.value, RequestState.EXPIRED.value}:
            result = AskHumanResult(
                requestId=row["request_id"],
                status=RequestStatus(row["status"]),
                outcome=Outcome(row["outcome"]),
                answer=row["answer"],
            )
        return HumanRequest(
            request_id=row["request_id"],
            principal=Principal(subject_id=row["subject_id"], application_id=row["application_id"]),
            request=AskHumanRequest(
                kind=RequestKind(row["kind"]),
                prompt=row["prompt"],
                idempotencyKey=row["idempotency_key"],
                phoneNumber=row["phone_number"],
            ),
            request_hash=row["request_hash"],
            state=RequestState(row["status"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            call_id=row["acs_call_connection_id"],
            result=result,
            error_code=None if row["error_code"] is None else ErrorCode(row["error_code"]),
            error_message=row["error_message"],
            recognition_started=row["recognition_started"],
        )
