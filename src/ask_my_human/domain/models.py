"""Internal domain models with no adapter dependencies."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from ask_my_human.contracts import AskHumanRequest, AskHumanResult
from ask_my_human.errors import ErrorCode


class RequestState(StrEnum):
    PENDING = "pending"
    RESPONDED = "responded"
    EXPIRED = "expired"
    FAILED = "failed"


class CallEventType(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ANSWERED = "answered"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    DECLINED = "declined"
    DISCONNECTED = "disconnected"
    CANCELLED = "cancelled"
    DEADLINE_EXCEEDED = "deadline_exceeded"


@dataclass(frozen=True, slots=True)
class Principal:
    subject_id: str
    application_id: str


@dataclass(frozen=True, slots=True)
class CallEvent:
    request_id: UUID
    event_type: CallEventType
    answer: str | None = None


@dataclass(frozen=True, slots=True)
class HumanRequest:
    request_id: UUID
    principal: Principal
    request: AskHumanRequest
    request_hash: str
    state: RequestState
    created_at: datetime
    expires_at: datetime
    call_id: str | None = None
    result: AskHumanResult | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None
