import json
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest

from ask_my_human.contracts import (
    AskHumanRequest,
    AskHumanResult,
    ExecutionError,
    Outcome,
    RequestKind,
    RequestStatus,
)
from ask_my_human.errors import ErrorCode

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def validate(filename: str, instance: Mapping[str, object]) -> None:
    jsonschema.Draft202012Validator(json.loads((SCHEMAS / filename).read_text())).validate(instance)


def test_request_schema_validates_normalized_approval() -> None:
    request = AskHumanRequest(
        kind=RequestKind.APPROVAL, prompt="  Deploy now?  ", idempotencyKey=uuid4()
    )
    payload = request.model_dump(by_alias=True, mode="json")
    assert payload["prompt"] == "Deploy now?"
    validate("ask-human-request.schema.json", payload)


@pytest.mark.parametrize(
    ("result", "filename"),
    [
        (
            AskHumanResult(
                requestId=uuid4(), status=RequestStatus.RESPONDED, outcome=Outcome.APPROVED
            ),
            "ask-human-result.schema.json",
        ),
        (
            AskHumanResult(
                requestId=uuid4(),
                status=RequestStatus.RESPONDED,
                outcome=Outcome.ANSWERED,
                answer="Yes, use the safer option.",
            ),
            "ask-human-result.schema.json",
        ),
        (
            AskHumanResult(
                requestId=uuid4(), status=RequestStatus.EXPIRED, outcome=Outcome.NO_ANSWER
            ),
            "ask-human-result.schema.json",
        ),
        (
            ExecutionError(
                requestId=None,
                code=ErrorCode.INVALID_REQUEST,
                message="Invalid request.",
                retryable=False,
            ),
            "ask-human-error.schema.json",
        ),
    ],
)
def test_terminal_contracts_validate(
    result: AskHumanResult | ExecutionError, filename: str
) -> None:
    validate(filename, result.model_dump(by_alias=True, mode="json"))


def test_invalid_result_combination_is_rejected() -> None:
    with pytest.raises(ValueError, match="incompatible"):
        AskHumanResult(requestId=uuid4(), status=RequestStatus.EXPIRED, outcome=Outcome.APPROVED)


@pytest.mark.parametrize(
    "payload",
    [
        {"requestId": str(uuid4()), "status": "expired", "outcome": "approved"},
        {"requestId": str(uuid4()), "status": "responded", "outcome": "no_answer"},
        {"requestId": str(uuid4()), "status": "responded", "outcome": "answered"},
        {
            "requestId": str(uuid4()),
            "status": "expired",
            "outcome": "no_answer",
            "answer": "unexpected",
        },
    ],
)
def test_result_schema_rejects_invalid_discriminator_combinations(
    payload: dict[str, str],
) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate("ask-human-result.schema.json", payload)


def test_request_schema_rejects_whitespace_only_prompt() -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate(
            "ask-human-request.schema.json",
            {"kind": "input", "prompt": "   ", "idempotencyKey": str(uuid4())},
        )


def test_request_model_and_schema_reject_same_overlong_wire_prompt() -> None:
    payload = {
        "kind": "input",
        "prompt": f" {'x' * 2000} ",
        "idempotencyKey": str(uuid4()),
    }
    with pytest.raises(ValueError, match="2000"):
        AskHumanRequest.model_validate(payload)
    with pytest.raises(jsonschema.ValidationError):
        validate("ask-human-request.schema.json", payload)


def test_unknown_request_field_is_rejected() -> None:
    with pytest.raises(ValueError):
        AskHumanRequest(kind=RequestKind.INPUT, prompt="Need context", idempotencyKey=uuid4(), extra=True)  # type: ignore[call-arg]
