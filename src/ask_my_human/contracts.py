"""Public request, result, and error contracts."""

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ask_my_human.errors import ErrorCode

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Answer = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Message = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class RequestKind(StrEnum):
    APPROVAL = "approval"
    INPUT = "input"


class AskHumanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RequestKind
    prompt: Prompt
    idempotency_key: UUID = Field(alias="idempotencyKey")


class RequestStatus(StrEnum):
    RESPONDED = "responded"
    EXPIRED = "expired"


class Outcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ANSWERED = "answered"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    DECLINED = "declined"
    DISCONNECTED = "disconnected"
    CANCELLED = "cancelled"
    DEADLINE_EXCEEDED = "deadline_exceeded"


class AskHumanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID = Field(alias="requestId")
    status: RequestStatus
    outcome: Outcome
    answer: Answer | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "AskHumanResult":
        approval_outcomes = {Outcome.APPROVED, Outcome.REJECTED}
        expired_outcomes = {
            Outcome.NO_ANSWER,
            Outcome.BUSY,
            Outcome.DECLINED,
            Outcome.DISCONNECTED,
            Outcome.CANCELLED,
            Outcome.DEADLINE_EXCEEDED,
        }
        if self.status is RequestStatus.RESPONDED and self.outcome in approval_outcomes:
            if self.answer is not None:
                raise ValueError("approval results cannot include an answer")
        elif self.status is RequestStatus.RESPONDED and self.outcome is Outcome.ANSWERED:
            if self.answer is None:
                raise ValueError("answered results require an answer")
        elif self.status is RequestStatus.EXPIRED and self.outcome in expired_outcomes:
            if self.answer is not None:
                raise ValueError("expired results cannot include an answer")
        else:
            raise ValueError("status and outcome are incompatible")
        return self


class ExecutionError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID | None = Field(default=None, alias="requestId")
    code: ErrorCode
    message: Message
    retryable: bool
