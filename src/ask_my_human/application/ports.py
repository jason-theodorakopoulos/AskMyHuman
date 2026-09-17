"""Narrow async application boundaries."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from ask_my_human.contracts import (
    AskHumanRequest,
    AskHumanResult,
    Outcome,
    RequestKind,
    RequestStatus,
)
from ask_my_human.domain.models import CallEvent, HumanRequest, Principal
from ask_my_human.errors import ErrorCode

Admission = Literal[
    "created",
    "joined_pending",
    "replayed",
    "conflict",
    "pending_admission_lost",
]


class AskHumanUseCase(Protocol):
    async def ask(
        self,
        principal: Principal,
        request: AskHumanRequest,
        cancellation: "CancellationSignal",
    ) -> AskHumanResult: ...

    async def handle_call_event(self, event: CallEvent) -> None: ...


class CancellationSignal(Protocol):
    @property
    def cancelled(self) -> bool: ...

    async def wait(self) -> None: ...


class RequestRepository(Protocol):
    async def create_or_replay(
        self,
        principal: Principal,
        request: AskHumanRequest,
        request_hash: str,
        expires_at: datetime,
    ) -> tuple[Admission, HumanRequest]:
        """Return created, joined-pending, replayed, conflict, or admission-loss."""

    async def attach_call_id(self, request_id: UUID, call_id: str) -> bool: ...

    async def claim_recognition(self, request_id: UUID) -> bool: ...

    async def get(self, request_id: UUID) -> HumanRequest | None: ...

    async def complete_if_pending(
        self,
        result: AskHumanResult,
        *,
        before: datetime | None = None,
    ) -> bool: ...

    async def complete_error_if_pending(
        self,
        request_id: UUID,
        error_code: ErrorCode,
        error_message: str,
    ) -> bool: ...

    async def expire_stale(self, now: datetime) -> int: ...

    async def expire_stale_calls(self, now: datetime) -> Sequence[HumanRequest]: ...

    async def pending_count(self) -> int: ...

    async def purge_terminal(self, before: datetime) -> int: ...


class CallAutomationGateway(Protocol):
    async def create_call(self, request: HumanRequest) -> str: ...

    async def start_recognition(self, call_id: str, request: HumanRequest) -> None: ...

    async def acknowledge_and_hang_up(
        self,
        call_id: str,
        *,
        request_id: UUID | None = None,
    ) -> None: ...

    async def handle_playback_event(self, event: CallEvent) -> None: ...

    async def hang_up(self, call_id: str) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class TelemetryOperation(StrEnum):
    ASK = "ask"
    JOIN_PENDING = "join_pending"
    CALL_CREATED = "call_created"
    CALLBACK_ACCEPTED = "callback_accepted"
    CALLBACK = "callback"
    REPOSITORY = "repository"
    CREATE_CALL = "create_call"
    RECOGNIZE = "recognize"


class Telemetry(Protocol):
    def span(
        self,
        operation: TelemetryOperation,
        *,
        request_id: UUID,
        kind: RequestKind | None = None,
        call_id: str | None = None,
        event_id: str | None = None,
        pending_join: bool | None = None,
    ) -> AbstractContextManager[object]: ...

    def dependency_failed(
        self,
        operation: TelemetryOperation,
        *,
        acs_code: int | None = None,
        error_code: ErrorCode | None = None,
    ) -> None: ...

    def set_pending(self, pending: bool) -> None: ...

    def record(
        self,
        *,
        operation: TelemetryOperation,
        request_id: UUID,
        kind: RequestKind | None = None,
        status: RequestStatus | None = None,
        outcome: Outcome | None = None,
        acs_code: int | None = None,
        elapsed_ms: int | None = None,
        replay: bool | None = None,
        call_id: str | None = None,
        event_id: str | None = None,
        delivery_id: UUID | None = None,
        received_at: datetime | None = None,
    ) -> None: ...
