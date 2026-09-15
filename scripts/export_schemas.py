"""Export public JSON Schemas deterministically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from ask_my_human.contracts import AskHumanRequest, AskHumanResult, ExecutionError

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS: dict[str, type[BaseModel]] = {
    "ask-human-request.schema.json": AskHumanRequest,
    "ask-human-result.schema.json": AskHumanResult,
    "ask-human-error.schema.json": ExecutionError,
}


def content(model: type[BaseModel]) -> str:
    schema = model.model_json_schema(by_alias=True)
    if model is AskHumanResult:
        schema["oneOf"] = [
            {
                "properties": {
                    "status": {"const": "responded"},
                    "outcome": {"enum": ["approved", "rejected"]},
                    "answer": {"type": "null"},
                }
            },
            {
                "properties": {
                    "status": {"const": "responded"},
                    "outcome": {"const": "answered"},
                    "answer": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 4000,
                        "pattern": r"\S",
                    },
                },
                "required": ["answer"],
            },
            {
                "properties": {
                    "status": {"const": "expired"},
                    "outcome": {
                        "enum": [
                            "no_answer",
                            "busy",
                            "declined",
                            "disconnected",
                            "cancelled",
                            "deadline_exceeded",
                        ]
                    },
                    "answer": {"type": "null"},
                }
            },
        ]
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema_dir = ROOT / "schemas"
    mismatches: list[str] = []
    for name, model in SCHEMAS.items():
        path = schema_dir / name
        expected = content(model)
        if args.check:
            if not path.is_file() or path.read_text() != expected:
                mismatches.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected)
    if mismatches:
        names = ", ".join(mismatches)
        print(f"Generated JSON Schemas differ ({names}); run scripts/export_schemas.py.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
