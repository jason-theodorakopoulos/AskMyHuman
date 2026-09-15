import json
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest

from ask_my_human.contracts import (
    AskHumanRequest,
    AskHumanResult,
    ExecutionError,
    Outcome,
    RequestStatus,
)

SCHEMAS = Path("schemas")


def validate(filename: str, instance: dict[str, object]) -> None:
    jsonschema.Draft202012Validator(json.loads((SCHEMAS / filename).read_text())).validate(instance)


def test_request_schema_validates_normalized_approval() -> None:
    request = AskHumanRequest(kind="approval", prompt="  Deploy now?  ", idempotencyKey=uuid4())
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
                requestId=None, code="invalid_request", message="Invalid request.", retryable=False
            ),
            "ask-human-error.schema.json",
        ),
    ],
)
def test_terminal_contracts_validate(result: object, filename: str) -> None:
    validate(filename, result.model_dump(by_alias=True, mode="json"))  # type: ignore[union-attr]


def test_invalid_result_combination_is_rejected() -> None:
    with pytest.raises(ValueError, match="incompatible"):
        AskHumanResult(requestId=uuid4(), status=RequestStatus.EXPIRED, outcome=Outcome.APPROVED)


def test_unknown_request_field_is_rejected() -> None:
    with pytest.raises(ValueError):
        AskHumanRequest(kind="input", prompt="Need context", idempotencyKey=uuid4(), extra=True)
