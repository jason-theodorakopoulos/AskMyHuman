from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ask_my_human.contracts import AskHumanRequest, Outcome, RequestKind, RequestStatus
from ask_my_human.domain.models import (
    CallEvent,
    CallEventType,
    HumanRequest,
    Principal,
    RequestState,
)
from ask_my_human.domain.transitions import complete, result_for_event


@pytest.mark.parametrize(
    ("event_type", "status", "outcome"),
    [
        (CallEventType.APPROVED, RequestStatus.RESPONDED, Outcome.APPROVED),
        (CallEventType.REJECTED, RequestStatus.RESPONDED, Outcome.REJECTED),
        (CallEventType.NO_ANSWER, RequestStatus.EXPIRED, Outcome.NO_ANSWER),
        (CallEventType.BUSY, RequestStatus.EXPIRED, Outcome.BUSY),
        (CallEventType.DECLINED, RequestStatus.EXPIRED, Outcome.DECLINED),
        (CallEventType.DISCONNECTED, RequestStatus.EXPIRED, Outcome.DISCONNECTED),
        (CallEventType.CANCELLED, RequestStatus.EXPIRED, Outcome.CANCELLED),
        (CallEventType.DEADLINE_EXCEEDED, RequestStatus.EXPIRED, Outcome.DEADLINE_EXCEEDED),
    ],
)
def test_event_maps_to_terminal_result(
    event_type: CallEventType, status: RequestStatus, outcome: Outcome
) -> None:
    result = result_for_event(CallEvent(request_id=uuid4(), event_type=event_type))
    assert (result.status, result.outcome) == (status, outcome)


def test_answered_event_normalizes_text() -> None:
    result = result_for_event(
        CallEvent(
            request_id=uuid4(), event_type=CallEventType.ANSWERED, answer="  Stop deployment.  "
        )
    )
    assert result.answer == "Stop deployment."


def test_approval_event_ignores_callback_text() -> None:
    result = result_for_event(
        CallEvent(request_id=uuid4(), event_type=CallEventType.APPROVED, answer="irrelevant")
    )
    assert result.answer is None


@pytest.mark.parametrize("answer", [None, "   "])
def test_answered_event_requires_nonblank_text(answer: str | None) -> None:
    with pytest.raises(ValueError, match="answered event requires nonblank text"):
        result_for_event(
            CallEvent(request_id=uuid4(), event_type=CallEventType.ANSWERED, answer=answer)
        )


def test_terminal_request_cannot_transition_again() -> None:
    request_id = uuid4()
    request = HumanRequest(
        request_id=request_id,
        principal=Principal(subject_id="subject", application_id="app"),
        request=AskHumanRequest(
            kind=RequestKind.APPROVAL, prompt="Continue?", idempotencyKey=uuid4()
        ),
        request_hash="hash",
        state=RequestState.RESPONDED,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
    )
    assert (
        complete(request, CallEvent(request_id=request_id, event_type=CallEventType.APPROVED))
        is None
    )


def test_request_ignores_event_for_another_request() -> None:
    request = HumanRequest(
        request_id=uuid4(),
        principal=Principal(subject_id="subject", application_id="app"),
        request=AskHumanRequest(
            kind=RequestKind.APPROVAL, prompt="Continue?", idempotencyKey=uuid4()
        ),
        request_hash="hash",
        state=RequestState.PENDING,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
    )
    with pytest.raises(ValueError, match="does not belong"):
        complete(request, CallEvent(request_id=uuid4(), event_type=CallEventType.APPROVED))
