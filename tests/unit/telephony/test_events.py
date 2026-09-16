import json
from pathlib import Path
from typing import Any

import pytest

from ask_my_human.domain.models import CallEventType
from ask_my_human.telephony.events import AcsEventType, parse_callback_event

FIXTURES = Path(__file__).parents[2] / "fixtures" / "acs"


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES / name).open(encoding="utf-8") as fixture:
        value: dict[str, Any] = json.load(fixture)
    return value


@pytest.mark.parametrize(
    ("fixture_name", "acs_type", "domain_type", "answer", "dependency_failure"),
    [
        ("call-connected.json", AcsEventType.CALL_CONNECTED, CallEventType.CONNECTED, None, False),
        (
            "call-disconnected.json",
            AcsEventType.CALL_DISCONNECTED,
            CallEventType.DECLINED,
            None,
            False,
        ),
        (
            "create-call-failed.json",
            AcsEventType.CREATE_CALL_FAILED,
            CallEventType.DEPENDENCY_FAILED,
            None,
            True,
        ),
        (
            "recognize-choice-completed.json",
            AcsEventType.RECOGNIZE_COMPLETED,
            CallEventType.APPROVED,
            None,
            False,
        ),
        (
            "recognize-failed.json",
            AcsEventType.RECOGNIZE_FAILED,
            CallEventType.NO_ANSWER,
            None,
            False,
        ),
        (
            "recognize-speech-completed.json",
            AcsEventType.RECOGNIZE_COMPLETED,
            CallEventType.ANSWERED,
            "Stop deployment.",
            False,
        ),
    ],
)
def test_sanitized_callback_fixture(
    fixture_name: str,
    acs_type: AcsEventType,
    domain_type: CallEventType | None,
    answer: str | None,
    dependency_failure: bool,
) -> None:
    callback = parse_callback_event(load_fixture(fixture_name))

    assert callback.event_type is acs_type
    assert callback.dependency_failure is dependency_failure
    assert callback.call_event is None if domain_type is None else callback.call_event is not None
    if callback.call_event is not None:
        assert callback.call_event.event_type is domain_type
        assert callback.call_event.answer == answer
        assert callback.call_event.call_id == callback.call_connection_id
        assert callback.call_event.event_id == callback.event_id


@pytest.mark.parametrize("sub_code", [8510, 8511, 99999])
def test_technical_recognition_failure_is_not_silence(sub_code: int) -> None:
    payload = load_fixture("recognize-failed.json")
    payload["data"]["resultInformation"] = {"code": 500, "subCode": sub_code}
    callback = parse_callback_event(payload)
    assert callback.call_event is not None
    assert callback.call_event.event_type is CallEventType.DEPENDENCY_FAILED
    assert callback.call_event.acs_code == 500


@pytest.mark.parametrize("event_type", [AcsEventType.PLAY_COMPLETED, AcsEventType.PLAY_FAILED])
def test_playback_callbacks_keep_correlation(event_type: AcsEventType) -> None:
    payload = load_fixture("call-connected.json")
    payload["type"] = event_type.value
    callback = parse_callback_event(payload)
    assert callback.call_event is not None
    assert callback.call_event.call_id == callback.call_connection_id
    assert callback.call_event.event_type in {
        CallEventType.PLAY_COMPLETED,
        CallEventType.PLAY_FAILED,
    }


@pytest.mark.parametrize(
    ("code", "sub_code", "expected"),
    [
        (480, 560480, CallEventType.NO_ANSWER),
        (486, 0, CallEventType.BUSY),
        (0, 540486, CallEventType.BUSY),
        (0, 560486, CallEventType.BUSY),
        (0, 8539, CallEventType.BUSY),
        (0, 8540, CallEventType.BUSY),
        (603, 0, CallEventType.DECLINED),
        (0, 8538, CallEventType.DECLINED),
        (487, 10024, CallEventType.DECLINED),
        (500, 99999, CallEventType.DISCONNECTED),
    ],
)
def test_disconnect_numeric_result_mapping(
    code: int, sub_code: int, expected: CallEventType
) -> None:
    payload = load_fixture("call-disconnected.json")
    payload["data"]["resultInformation"] = {
        "code": code,
        "subCode": sub_code,
        "message": "this text is never classified",
    }

    callback = parse_callback_event(payload)

    assert callback.call_event is not None
    assert callback.call_event.event_type is expected


@pytest.mark.parametrize("missing", ["specversion", "id", "source", "type", "data"])
def test_required_cloudevent_field_is_rejected(missing: str) -> None:
    payload = load_fixture("call-connected.json")
    del payload[missing]

    with pytest.raises(ValueError):
        parse_callback_event(payload)


@pytest.mark.parametrize("missing", ["operationContext", "callConnectionId"])
def test_required_acs_data_field_is_rejected(missing: str) -> None:
    payload = load_fixture("call-connected.json")
    del payload["data"][missing]

    with pytest.raises(ValueError):
        parse_callback_event(payload)


def test_recognition_completion_requires_exactly_one_result() -> None:
    payload = load_fixture("recognize-choice-completed.json")
    payload["data"]["speechResult"] = {"speech": "also present"}

    with pytest.raises(ValueError, match="exactly one"):
        parse_callback_event(payload)


def test_unknown_event_type_is_rejected() -> None:
    payload = load_fixture("call-connected.json")
    payload["type"] = "Microsoft.Communication.FutureEvent"

    with pytest.raises(ValueError, match="unsupported ACS event type"):
        parse_callback_event(payload)
