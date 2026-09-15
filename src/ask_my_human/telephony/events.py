"""Strict parsing and domain mapping for ACS Call Automation callbacks."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from ask_my_human.domain.models import CallEvent, CallEventType


class AcsEventType(StrEnum):
    CALL_CONNECTED = "Microsoft.Communication.CallConnected"
    CALL_DISCONNECTED = "Microsoft.Communication.CallDisconnected"
    CREATE_CALL_FAILED = "Microsoft.Communication.CreateCallFailed"
    RECOGNIZE_COMPLETED = "Microsoft.Communication.RecognizeCompleted"
    RECOGNIZE_FAILED = "Microsoft.Communication.RecognizeFailed"
    RECOGNIZE_CANCELED = "Microsoft.Communication.RecognizeCanceled"


@dataclass(frozen=True, slots=True)
class ResultInformation:
    code: int
    sub_code: int


@dataclass(frozen=True, slots=True)
class AcsCallbackEvent:
    event_id: str
    event_type: AcsEventType
    request_id: UUID
    call_connection_id: str
    result_information: ResultInformation | None = None
    choice_label: str | None = None
    speech: str | None = None

    @property
    def dependency_failure(self) -> bool:
        return self.event_type is AcsEventType.CREATE_CALL_FAILED and self.call_event is None

    @property
    def call_event(self) -> CallEvent | None:
        event_type = self._domain_event_type()
        if event_type is None:
            return None
        answer = (
            self.speech.strip() if event_type is CallEventType.ANSWERED and self.speech else None
        )
        return CallEvent(request_id=self.request_id, event_type=event_type, answer=answer)

    def _domain_event_type(self) -> CallEventType | None:
        if self.event_type is AcsEventType.CALL_CONNECTED:
            return None
        if self.event_type is AcsEventType.RECOGNIZE_COMPLETED:
            if self.choice_label == "approve":
                return CallEventType.APPROVED
            if self.choice_label == "reject":
                return CallEventType.REJECTED
            if self.speech is not None and self.speech.strip():
                return CallEventType.ANSWERED
            return CallEventType.NO_ANSWER
        if self.event_type is AcsEventType.RECOGNIZE_FAILED:
            return CallEventType.NO_ANSWER
        if self.event_type is AcsEventType.RECOGNIZE_CANCELED:
            return CallEventType.CANCELLED

        classified = _classify_result(self.result_information)
        if classified is not None:
            return classified
        if self.event_type is AcsEventType.CALL_DISCONNECTED:
            return CallEventType.DISCONNECTED
        return None


def parse_callback_event(payload: Mapping[str, Any]) -> AcsCallbackEvent:
    """Parse the required CloudEvent and ACS data fields without message inspection."""
    spec_version = _required_string(payload, "specversion")
    if spec_version != "1.0":
        raise ValueError("specversion must be '1.0'")

    event_id = _required_string(payload, "id")
    _required_string(payload, "source")
    raw_event_type = _required_string(payload, "type")
    try:
        event_type = AcsEventType(raw_event_type)
    except ValueError as error:
        raise ValueError(f"unsupported ACS event type: {raw_event_type}") from error

    data = _required_mapping(payload, "data")
    request_id = _required_uuid(data, "operationContext")
    call_connection_id = _required_string(data, "callConnectionId")
    result_information = _optional_result_information(data)

    choice_label: str | None = None
    speech: str | None = None
    if event_type is AcsEventType.RECOGNIZE_COMPLETED:
        choice = data.get("choiceResult")
        speech_result = data.get("speechResult")
        if (choice is None) == (speech_result is None):
            raise ValueError("RecognizeCompleted requires exactly one recognition result")
        if choice is not None:
            choice_label = _required_string(_as_mapping(choice, "choiceResult"), "label")
        else:
            speech = _required_string(
                _as_mapping(speech_result, "speechResult"), "speech", allow_blank=True
            )

    if (
        event_type in {AcsEventType.CREATE_CALL_FAILED, AcsEventType.RECOGNIZE_FAILED}
        and result_information is None
    ):
        raise ValueError(f"{event_type.value} requires resultInformation")

    return AcsCallbackEvent(
        event_id=event_id,
        event_type=event_type,
        request_id=request_id,
        call_connection_id=call_connection_id,
        result_information=result_information,
        choice_label=choice_label,
        speech=speech,
    )


def _classify_result(result: ResultInformation | None) -> CallEventType | None:
    if result is None:
        return None
    if (result.code, result.sub_code) == (480, 560480):
        return CallEventType.NO_ANSWER
    if result.code in {486, 540486, 560486} or result.sub_code in {
        540486,
        560486,
        8539,
        8540,
    }:
        return CallEventType.BUSY
    if result.code == 603 or result.sub_code == 8538:
        return CallEventType.DECLINED
    if (result.code, result.sub_code) == (487, 10024):
        return CallEventType.DECLINED
    return None


def _required_mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    if key not in value:
        raise ValueError(f"missing required field: {key}")
    return _as_mapping(value[key], key)


def _as_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _required_string(value: Mapping[str, Any], key: str, *, allow_blank: bool = False) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str):
        raise ValueError(f"{key} must be a string")
    if not allow_blank and not candidate.strip():
        raise ValueError(f"{key} must not be blank")
    return candidate


def _required_uuid(value: Mapping[str, Any], key: str) -> UUID:
    try:
        return UUID(_required_string(value, key))
    except ValueError as error:
        raise ValueError(f"{key} must be a UUID") from error


def _optional_result_information(value: Mapping[str, Any]) -> ResultInformation | None:
    candidate = value.get("resultInformation")
    if candidate is None:
        return None
    result = _as_mapping(candidate, "resultInformation")
    code = result.get("code")
    sub_code = result.get("subCode")
    if isinstance(code, bool) or not isinstance(code, int):
        raise ValueError("resultInformation.code must be an integer")
    if isinstance(sub_code, bool) or not isinstance(sub_code, int):
        raise ValueError("resultInformation.subCode must be an integer")
    return ResultInformation(code=code, sub_code=sub_code)
