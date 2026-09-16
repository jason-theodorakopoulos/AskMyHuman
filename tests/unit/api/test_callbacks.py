from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from support.fakes import FakeAskHumanUseCase, FakeTelemetry

from ask_my_human.api.callbacks import create_callbacks_router
from ask_my_human.application.ports import TelemetryOperation
from ask_my_human.domain.models import CallEvent, CallEventType
from ask_my_human.errors import AskMyHumanError, ErrorCode


def callback_body() -> list[dict[str, object]]:
    return [{"type": "RecognizeCompleted", "data": {"operationContext": str(uuid4())}}]


def app_for(
    use_case: FakeAskHumanUseCase,
    validate_token: object,
    parse_events: object,
    telemetry: FakeTelemetry | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_callbacks_router(
            use_case=use_case,
            validate_token=validate_token,  # type: ignore[arg-type]
            parse_events=parse_events,  # type: ignore[arg-type]
            telemetry=telemetry,
        )
    )
    return app


@pytest.mark.asyncio
async def test_token_is_validated_before_body_parsing() -> None:
    calls: list[str] = []

    async def reject(token: str) -> None:
        calls.append(f"validate:{token}")
        raise AskMyHumanError(ErrorCode.UNAUTHENTICATED, "Invalid callback token")

    def parse(_payload: object) -> Sequence[CallEvent]:
        calls.append("parse")
        return []

    use_case = FakeAskHumanUseCase()
    async with AsyncClient(
        transport=ASGITransport(app=app_for(use_case, reject, parse)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/callbacks/acs",
            headers={"Authorization": "Bearer signed-token"},
            content=b"not-json",
        )

    assert response.status_code == 401
    assert calls == ["validate:signed-token"]
    assert use_case.events == []


@pytest.mark.asyncio
async def test_missing_bearer_token_is_rejected_before_validator_and_parser() -> None:
    calls: list[str] = []

    async def validate(_token: str) -> None:
        calls.append("validate")

    def parse(_payload: object) -> Sequence[CallEvent]:
        calls.append("parse")
        return []

    async with AsyncClient(
        transport=ASGITransport(app=app_for(FakeAskHumanUseCase(), validate, parse)),
        base_url="http://test",
    ) as client:
        response = await client.post("/v1/callbacks/acs", json=callback_body())

    assert response.status_code == 401
    assert calls == []


@pytest.mark.asyncio
async def test_authenticated_events_are_delegated_to_use_case() -> None:
    request_id = uuid4()
    event = CallEvent(request_id=request_id, event_type=CallEventType.APPROVED)
    parsed_payloads: list[object] = []

    async def validate(token: str) -> None:
        assert token == "signed-token"

    def parse(payload: object) -> Sequence[CallEvent]:
        parsed_payloads.append(payload)
        return [event]

    use_case = FakeAskHumanUseCase()
    body = callback_body()
    async with AsyncClient(
        transport=ASGITransport(app=app_for(use_case, validate, parse)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/callbacks/acs",
            headers={"Authorization": "Bearer signed-token"},
            json=body,
        )

    assert response.status_code == 200
    assert response.content == b""
    assert parsed_payloads == [body]
    assert use_case.events == [event]


@pytest.mark.asyncio
async def test_authenticated_duplicate_and_late_callbacks_return_200() -> None:
    event = CallEvent(
        request_id=uuid4(),
        event_type=CallEventType.DISCONNECTED,
        call_id="provider-call",
        event_id="provider-event",
    )
    telemetry = FakeTelemetry()
    started = datetime.now(UTC)

    async def validate(_token: str) -> None:
        return None

    def parse(_payload: object) -> Sequence[CallEvent]:
        return [event]

    use_case = FakeAskHumanUseCase()
    async with AsyncClient(
        transport=ASGITransport(app=app_for(use_case, validate, parse, telemetry)),
        base_url="http://test",
    ) as client:
        first = await client.post(
            "/v1/callbacks/acs",
            headers={"Authorization": "Bearer signed-token"},
            json=callback_body(),
        )
        duplicate = await client.post(
            "/v1/callbacks/acs",
            headers={"Authorization": "Bearer signed-token"},
            json=callback_body(),
        )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert use_case.events == [event, event]
    assert len(telemetry.records) == 2
    assert telemetry.records[0]["delivery_id"] != telemetry.records[1]["delivery_id"]
    for record in telemetry.records:
        assert record["operation"] is TelemetryOperation.CALLBACK_ACCEPTED
        assert record["request_id"] == event.request_id
        assert record["call_id"] == event.call_id
        assert record["event_id"] == event.event_id
        assert isinstance(record["received_at"], datetime)
        assert started <= record["received_at"] <= datetime.now(UTC)


@pytest.mark.asyncio
async def test_partially_processed_batch_does_not_record_acceptance() -> None:
    event = CallEvent(
        request_id=uuid4(),
        event_type=CallEventType.DISCONNECTED,
        call_id="provider-call",
        event_id="provider-event",
    )
    telemetry = FakeTelemetry()

    class FailingUseCase(FakeAskHumanUseCase):
        async def handle_call_event(self, event: CallEvent) -> None:
            if self.events:
                raise RuntimeError("answer-SENSITIVE")
            await super().handle_call_event(event)

    async def validate(_token: str) -> None:
        return None

    def parse(_payload: object) -> Sequence[CallEvent]:
        return [event, event]

    use_case = FailingUseCase()
    async with AsyncClient(
        transport=ASGITransport(app=app_for(use_case, validate, parse, telemetry)),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/callbacks/acs",
            headers={"Authorization": "Bearer signed-token"},
            json=callback_body(),
        )

    assert response.status_code == 500
    assert use_case.events == [event]
    assert telemetry.records == []
    assert "SENSITIVE" not in response.text
