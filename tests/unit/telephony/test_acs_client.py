from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from azure.communication.callautomation import (
    CallConnectionProperties,
    DtmfTone,
    RecognizeInputType,
)
from azure.communication.callautomation.aio import CallAutomationClient

from ask_my_human.contracts import AskHumanRequest, RequestKind
from ask_my_human.domain.models import HumanRequest, Principal, RequestState
from ask_my_human.telephony.acs_client import AcsCallAutomationGateway


def human_request(kind: RequestKind = RequestKind.APPROVAL) -> HumanRequest:
    now = datetime.now(UTC)
    return HumanRequest(
        request_id=uuid4(),
        principal=Principal(subject_id="subject", application_id="application"),
        request=AskHumanRequest(
            kind=kind,
            prompt="Deploy this release?" if kind is RequestKind.APPROVAL else "What changed?",
            idempotencyKey=uuid4(),
        ),
        request_hash="hash",
        state=RequestState.PENDING,
        created_at=now,
        expires_at=now + timedelta(seconds=210),
    )


def gateway(
    *, enable_dtmf_fallback: bool = True
) -> tuple[AcsCallAutomationGateway, MagicMock, MagicMock]:
    client = MagicMock(spec=CallAutomationClient)
    connection = MagicMock()
    connection.start_recognizing_media = AsyncMock()
    connection.play_media = AsyncMock()
    connection.hang_up = AsyncMock()
    client.get_call_connection.return_value = connection
    adapter = AcsCallAutomationGateway(
        client,
        callback_url="https://service.example/v1/callbacks/acs",
        source_phone_number="+15555550100",
        target_phone_number="+15555550101",
        cognitive_services_endpoint="https://speech.example",
        locale="en-US",
        voice_name="en-US-AvaMultilingualNeural",
        enable_dtmf_fallback=enable_dtmf_fallback,
    )
    return adapter, client, connection


async def test_create_call_uses_outbound_numbers_callback_and_request_context() -> None:
    adapter, client, _ = gateway()
    request = human_request()
    client.create_call = AsyncMock(
        return_value=CallConnectionProperties(call_connection_id="call-connection-id")
    )

    call_id = await adapter.create_call(request)

    assert call_id == "call-connection-id"
    args, kwargs = client.create_call.await_args
    assert args[0].properties["value"] == "+15555550101"
    assert args[1] == "https://service.example/v1/callbacks/acs"
    assert kwargs["source_caller_id_number"].properties["value"] == "+15555550100"
    assert kwargs["operation_context"] == str(request.request_id)
    assert kwargs["cognitive_services_endpoint"] == "https://speech.example"
    assert "media_streaming" not in kwargs


async def test_create_call_rejects_missing_call_connection_id() -> None:
    adapter, client, _ = gateway()
    client.create_call = AsyncMock(return_value=CallConnectionProperties())

    with pytest.raises(RuntimeError, match="no call connection ID"):
        await adapter.create_call(human_request())


async def test_approval_starts_one_choice_recognition_with_fixed_labels_and_dtmf() -> None:
    adapter, _, connection = gateway()
    request = human_request(RequestKind.APPROVAL)

    await adapter.start_recognition("call-id", request)

    connection.start_recognizing_media.assert_awaited_once()
    args, kwargs = connection.start_recognizing_media.await_args
    assert args[0] is RecognizeInputType.CHOICES
    assert args[1].properties["value"] == "+15555550101"
    assert kwargs["operation_context"] == str(request.request_id)
    assert kwargs["initial_silence_timeout"] == 20
    assert kwargs["speech_language"] == "en-US"
    assert kwargs["play_prompt"].text == (
        "Deploy this release? Say approve or press 1. Say reject or press 2."
    )
    assert [(choice.label, choice.tone) for choice in kwargs["choices"]] == [
        ("approve", DtmfTone.ONE),
        ("reject", DtmfTone.TWO),
    ]


async def test_approval_can_disable_dtmf_fallback() -> None:
    adapter, _, connection = gateway(enable_dtmf_fallback=False)

    await adapter.start_recognition("call-id", human_request())

    _, kwargs = connection.start_recognizing_media.await_args
    assert [choice.tone for choice in kwargs["choices"]] == [None, None]
    assert "press" not in kwargs["play_prompt"].text


async def test_input_starts_one_speech_recognition_without_choices() -> None:
    adapter, _, connection = gateway()
    request = human_request(RequestKind.INPUT)

    await adapter.start_recognition("call-id", request)

    connection.start_recognizing_media.assert_awaited_once()
    args, kwargs = connection.start_recognizing_media.await_args
    assert args[0] is RecognizeInputType.SPEECH
    assert kwargs["play_prompt"].text == "What changed?"
    assert "choices" not in kwargs


async def test_acknowledgement_is_played_once_before_hangup() -> None:
    adapter, client, connection = gateway()

    await adapter.acknowledge_and_hang_up("call-id")

    client.get_call_connection.assert_called_once_with("call-id")
    assert [method_call[0] for method_call in connection.method_calls] == [
        "play_media",
        "hang_up",
    ]
    acknowledgement = connection.play_media.await_args.args[0]
    assert acknowledgement.text == "Thank you. Your response has been recorded."
    assert connection.play_media.await_args.args[1] == "all"


async def test_hang_up_terminates_the_call_for_everyone() -> None:
    adapter, client, connection = gateway()

    await adapter.hang_up("call-id")

    client.get_call_connection.assert_called_once_with("call-id")
    connection.hang_up.assert_awaited_once_with(True)
