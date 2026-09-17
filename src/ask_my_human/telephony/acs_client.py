"""Async Azure Communication Services Call Automation gateway."""

import asyncio
from contextlib import suppress
from uuid import UUID, uuid4

from azure.communication.callautomation import (
    DtmfTone,
    PhoneNumberIdentifier,
    RecognitionChoice,
    RecognizeInputType,
    TextSource,
)
from azure.communication.callautomation.aio import CallAutomationClient

from ask_my_human.config import Settings
from ask_my_human.contracts import RequestKind
from ask_my_human.domain.models import CallEvent, CallEventType, HumanRequest

_APPROVE_LABEL = "approve"
_REJECT_LABEL = "reject"
_ACKNOWLEDGEMENT = "Thank you. Your response has been recorded."


class AcsCallAutomationGateway:
    def __init__(
        self,
        client: CallAutomationClient,
        *,
        callback_url: str,
        source_phone_number: str,
        cognitive_services_endpoint: str,
        locale: str,
        voice_name: str,
        enable_dtmf_fallback: bool = True,
        playback_timeout_seconds: float = 1.5,
        hangup_timeout_seconds: float = 1,
    ) -> None:
        if playback_timeout_seconds <= 0 or hangup_timeout_seconds <= 0:
            raise ValueError("playback and hangup timeouts must be positive")
        self._client = client
        self._callback_url = callback_url
        self._source = PhoneNumberIdentifier(source_phone_number)
        self._cognitive_services_endpoint = cognitive_services_endpoint
        self._locale = locale
        self._voice_name = voice_name
        self._enable_dtmf_fallback = enable_dtmf_fallback
        self._playback_timeout = playback_timeout_seconds
        self._hangup_timeout = hangup_timeout_seconds
        self._playbacks: dict[str, tuple[UUID, asyncio.Event]] = {}

    @classmethod
    def from_settings(
        cls, client: CallAutomationClient, settings: Settings
    ) -> "AcsCallAutomationGateway":
        callback_url = str(settings.acs_callback_url)
        return cls(
            client,
            callback_url=callback_url,
            source_phone_number=settings.acs_source_phone_number.get_secret_value(),
            cognitive_services_endpoint=str(settings.azure_ai_endpoint).rstrip("/"),
            locale=settings.locale,
            voice_name=settings.voice_name,
        )

    async def create_call(self, request: HumanRequest) -> str:
        target = PhoneNumberIdentifier(request.request.phone_number)
        properties = await self._client.create_call(
            target,
            self._callback_url,
            source_caller_id_number=self._source,
            operation_context=str(request.request_id),
            cognitive_services_endpoint=self._cognitive_services_endpoint,
        )
        call_connection_id = properties.call_connection_id
        if call_connection_id is None or not call_connection_id.strip():
            raise RuntimeError("ACS create_call returned no call connection ID")
        return call_connection_id

    async def start_recognition(self, call_id: str, request: HumanRequest) -> None:
        connection = self._client.get_call_connection(call_id)
        target = PhoneNumberIdentifier(request.request.phone_number)
        prompt = TextSource(
            text=self._recognition_prompt(request),
            source_locale=self._locale,
            voice_name=self._voice_name,
        )
        operation_context = str(request.request_id)
        if request.request.kind is RequestKind.APPROVAL:
            await connection.start_recognizing_media(
                RecognizeInputType.CHOICES,
                target,
                initial_silence_timeout=20,
                play_prompt=prompt,
                operation_context=operation_context,
                speech_language=self._locale,
                choices=self._approval_choices(),
            )
            return

        await connection.start_recognizing_media(
            RecognizeInputType.SPEECH,
            target,
            initial_silence_timeout=20,
            play_prompt=prompt,
            operation_context=operation_context,
            speech_language=self._locale,
        )

    async def acknowledge_and_hang_up(
        self,
        call_id: str,
        *,
        request_id: UUID | None = None,
    ) -> None:
        if call_id in self._playbacks:
            return
        correlation = request_id or uuid4()
        completed = asyncio.Event()
        self._playbacks[call_id] = (correlation, completed)
        connection = self._client.get_call_connection(call_id)
        acknowledgement = TextSource(
            text=_ACKNOWLEDGEMENT,
            source_locale=self._locale,
            voice_name=self._voice_name,
        )
        try:
            with suppress(Exception):
                async with asyncio.timeout(self._playback_timeout):
                    await connection.play_media(
                        acknowledgement,
                        "all",
                        operation_context=str(correlation),
                    )
                    await completed.wait()
        finally:
            self._playbacks.pop(call_id, None)
            async with asyncio.timeout(self._hangup_timeout):
                await connection.hang_up(True)

    async def handle_playback_event(self, event: CallEvent) -> None:
        if event.call_id is None or event.event_type not in {
            CallEventType.PLAY_COMPLETED,
            CallEventType.PLAY_FAILED,
        }:
            return
        playback = self._playbacks.get(event.call_id)
        if playback is not None and playback[0] == event.request_id:
            playback[1].set()

    async def hang_up(self, call_id: str) -> None:
        connection = self._client.get_call_connection(call_id)
        await connection.hang_up(True)

    def _recognition_prompt(self, request: HumanRequest) -> str:
        if request.request.kind is RequestKind.APPROVAL:
            if self._enable_dtmf_fallback:
                return f"{request.request.prompt} Say approve or press 1. Say reject or press 2."
            return f"{request.request.prompt} Say approve or say reject."
        return request.request.prompt

    def _approval_choices(self) -> list[RecognitionChoice]:
        approve_tone = DtmfTone.ONE if self._enable_dtmf_fallback else None
        reject_tone = DtmfTone.TWO if self._enable_dtmf_fallback else None
        return [
            RecognitionChoice(
                label=_APPROVE_LABEL,
                phrases=["Approve", "Yes"],
                tone=approve_tone,
            ),
            RecognitionChoice(
                label=_REJECT_LABEL,
                phrases=["Reject", "No"],
                tone=reject_tone,
            ),
        ]
