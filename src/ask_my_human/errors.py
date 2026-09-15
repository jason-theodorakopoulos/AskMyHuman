"""Stable public application errors."""

from enum import StrEnum
from uuid import UUID


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    RATE_LIMITED = "rate_limited"
    DEPENDENCY_FAILURE = "dependency_failure"
    INTERNAL = "internal"


class AskMyHumanError(Exception):
    """An error safe to expose through the public protocol."""

    def __init__(
        self, code: ErrorCode, message: str, *, request_id: UUID | None = None
    ) -> None:
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(message)

    @property
    def retryable(self) -> bool:
        return self.code in {
            ErrorCode.RATE_LIMITED,
            ErrorCode.DEPENDENCY_FAILURE,
            ErrorCode.INTERNAL,
        }
