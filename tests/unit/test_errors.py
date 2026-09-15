import pytest

from ask_my_human.errors import AskMyHumanError, ErrorCode


@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        (ErrorCode.RATE_LIMITED, True),
        (ErrorCode.DEPENDENCY_FAILURE, True),
        (ErrorCode.INTERNAL, True),
        (ErrorCode.INVALID_REQUEST, False),
        (ErrorCode.UNAUTHENTICATED, False),
        (ErrorCode.FORBIDDEN, False),
        (ErrorCode.IDEMPOTENCY_CONFLICT, False),
    ],
)
def test_error_retryability(code: ErrorCode, retryable: bool) -> None:
    assert AskMyHumanError(code, "safe message").retryable is retryable
