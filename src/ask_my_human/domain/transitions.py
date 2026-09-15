"""Terminal state transition rules."""

from ask_my_human.contracts import AskHumanResult, Outcome, RequestStatus
from ask_my_human.domain.models import CallEvent, CallEventType, HumanRequest, RequestState

_RESPONDED = {
    CallEventType.APPROVED: Outcome.APPROVED,
    CallEventType.REJECTED: Outcome.REJECTED,
    CallEventType.ANSWERED: Outcome.ANSWERED,
}
_EXPIRED = {
    CallEventType.NO_ANSWER: Outcome.NO_ANSWER,
    CallEventType.BUSY: Outcome.BUSY,
    CallEventType.DECLINED: Outcome.DECLINED,
    CallEventType.DISCONNECTED: Outcome.DISCONNECTED,
    CallEventType.CANCELLED: Outcome.CANCELLED,
    CallEventType.DEADLINE_EXCEEDED: Outcome.DEADLINE_EXCEEDED,
}


def result_for_event(event: CallEvent) -> AskHumanResult:
    """Map one typed callback to a valid public terminal result."""
    if event.event_type in _RESPONDED:
        outcome = _RESPONDED[event.event_type]
        answer = event.answer.strip() if event.answer else None
        if outcome is Outcome.ANSWERED and answer is None:
            raise ValueError("an answered event requires nonblank text")
        return AskHumanResult(
            requestId=event.request_id,
            status=RequestStatus.RESPONDED,
            outcome=outcome,
            answer=answer if outcome is Outcome.ANSWERED else None,
        )
    return AskHumanResult(
        requestId=event.request_id,
        status=RequestStatus.EXPIRED,
        outcome=_EXPIRED[event.event_type],
    )


def complete(request: HumanRequest, event: CallEvent) -> AskHumanResult | None:
    """Return the first terminal result, or None once the request is terminal."""
    if request.state is not RequestState.PENDING or event.request_id != request.request_id:
        return None
    return result_for_event(event)
