from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ask_my_human.contracts import AskHumanRequest, Outcome, RequestStatus
from ask_my_human.domain.models import CallEvent, CallEventType, HumanRequest, Principal, RequestState
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
        CallEvent(request_id=uuid4(), event_type=CallEventType.ANSWERED, answer="  Stop deployment.  ")
    )
    assert result.answer == "Stop deployment."


def test_terminal_request_cannot_transition_again() -> None:
    request_id = uuid4()
    request = HumanRequest(
        request_id=request_id,
        principal=Principal(subject_id="subject", application_id="app"),
        request=AskHumanRequest(kind="approval", prompt="Continue?", idempotencyKey=uuid4()),
        request_hash="hash",
        state=RequestState.RESPONDED,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )
    assert complete(request, CallEvent(request_id=request_id, event_type=CallEventType.APPROVED)) is None
