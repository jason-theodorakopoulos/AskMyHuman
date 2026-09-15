"""Narrow async application boundaries."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from ask_my_human.contracts import AskHumanRequest, AskHumanResult
from ask_my_human.domain.models import CallEvent, HumanRequest, Principal

Admission = Literal["created", "joined", "replayed", "conflict", "pending_exists"]


class AskHumanUseCase(Protocol):
    async def ask(self, principal: Principal, request: AskHumanRequest) -> AskHumanResult: ...

    async def handle_call_event(self, event: CallEvent) -> None: ...


class RequestRepository(Protocol):
    async def create_or_replay(
        self,
        principal: Principal,
        request: AskHumanRequest,
        request_hash: str,
        expires_at: datetime,
    ) -> tuple[Admission, HumanRequest]: ...

    async def attach_call_id(self, request_id: UUID, call_id: str) -> bool: ...

    async def get(self, request_id: UUID) -> HumanRequest | None: ...

    async def complete_if_pending(self, result: AskHumanResult) -> bool: ...

    async def expire_stale(self, now: datetime) -> int: ...

    async def purge_terminal(self, before: datetime) -> int: ...


class CallAutomationGateway(Protocol):
    async def create_call(self, request: HumanRequest) -> str: ...

    async def start_recognition(self, call_id: str, request: HumanRequest) -> None: ...

    async def acknowledge_and_hang_up(self, call_id: str) -> None: ...

    async def hang_up(self, call_id: str) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class Telemetry(Protocol):
    def record(
        self,
        *,
        operation: Literal["ask", "callback", "repository"],
        request_id: UUID,
        kind: str | None = None,
        status: str | None = None,
        outcome: str | None = None,
        acs_code: int | None = None,
        elapsed_ms: int | None = None,
        replay: bool | None = None,
    ) -> None: ...
