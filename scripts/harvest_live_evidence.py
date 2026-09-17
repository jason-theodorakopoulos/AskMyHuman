"""Harvest content-free live evidence from a Log Analytics workspace."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, TypedDict, cast
from uuid import UUID

from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus
from pydantic import BaseModel, ConfigDict, Field


class EvidenceError(RuntimeError):
    """Raised when workspace data cannot prove a complete evidence interval."""


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Attempt(_EvidenceModel):
    request_id: UUID
    attempt_id: str = Field(min_length=1)
    call_id: str = Field(min_length=1)


class Delivery(_EvidenceModel):
    request_id: UUID
    call_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    delivery_id: str = Field(min_length=1)
    received_at: datetime
    accepted: Literal[True] = True


class PendingJoin(_EvidenceModel):
    request_id: UUID
    event_id: str = Field(min_length=1)
    observed_at: datetime


class ProviderEvidence(_EvidenceModel):
    source: Literal["acs-provider"] = "acs-provider"
    attempt_source: Literal["acs-provider"] = "acs-provider"
    delivery_source: Literal["content-free-app-telemetry"] = "content-free-app-telemetry"
    pending_join_source: Literal["content-free-app-telemetry"] = "content-free-app-telemetry"
    record: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    window_start: datetime
    complete_through: datetime
    attempts: list[Attempt]
    deliveries: list[Delivery]
    pending_joins: list[PendingJoin]


class TelemetryEvidence(_EvidenceModel):
    source: Literal["log-analytics-export"] = "log-analytics-export"
    record: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    workspace: str = Field(min_length=1)
    complete_through: datetime


class ProviderRow(TypedDict):
    attempt_id: str
    call_id: str


class AppRow(TypedDict):
    observed_at: datetime
    span_id: str
    name: str
    request_id: str
    call_id: str
    event_id: str
    pending_join: bool


class QueryTable(Protocol):
    columns: Sequence[object]
    rows: Sequence[Sequence[object]]


class QueryResult(Protocol):
    status: object
    tables: Sequence[QueryTable]


PROVIDER_QUERY = """
ACSCallAutomationIncomingOperations
| where TimeGenerated >= datetime({window_start})
| where OperationName =~ "CreateCall"
| where ResultType in~ ("Succeeded", "Success")
| project attempt_id=tostring(OperationId), call_id=tostring(CallConnectionId)
""".strip()

APP_QUERY = """
AppDependencies
| where TimeGenerated >= datetime({window_start})
| where AppRoleInstance == {revision}
| where Name in ("askhuman.acs.create_call", "askhuman.acs.callback", "askhuman.request")
| extend request_id=tostring(Properties["request_id"]),
         call_id=tostring(Properties["call_id"]),
         event_id=tostring(Properties["event_id"]),
         pending_join=tobool(Properties["pending_join"])
| where isnotempty(request_id)
| project observed_at=TimeGenerated, span_id=Id, name=Name, request_id,
          call_id, event_id, pending_join
""".strip()

PROVIDER_WATERMARK_QUERY = """
ACSCallAutomationIncomingOperations
| where TimeGenerated >= datetime({window_start})
| summarize complete_through=max(ingestion_time())
""".strip()

APP_WATERMARK_QUERY = """
AppDependencies
| where TimeGenerated >= datetime({window_start})
| where AppRoleInstance == {revision}
| summarize complete_through=max(ingestion_time())
""".strip()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise EvidenceError("Evidence timestamps must include a UTC offset.")
    return value.astimezone(UTC)


def build_provider_evidence(
    *,
    provider_rows: Sequence[ProviderRow],
    app_rows: Sequence[AppRow],
    provider_watermark: datetime,
    app_watermark: datetime,
    window_start: datetime,
    required_complete_through: datetime,
    revision: str,
    record: str,
) -> ProviderEvidence:
    start = _utc(window_start)
    required = _utc(required_complete_through)
    watermarks = (_utc(provider_watermark), _utc(app_watermark))
    if start > required or min(watermarks) < required:
        raise EvidenceError("Provider or application ingestion is incomplete for the interval.")

    call_correlations: dict[str, tuple[UUID, str]] = {}
    deliveries: list[Delivery] = []
    pending_joins: list[PendingJoin] = []
    for app_row in app_rows:
        observed_at = _utc(app_row["observed_at"])
        if not start <= observed_at <= required:
            continue
        try:
            request_id = UUID(app_row["request_id"])
        except ValueError as error:
            raise EvidenceError("Application evidence contains an invalid request ID.") from error
        if app_row["name"] == "askhuman.acs.create_call" and app_row["call_id"]:
            existing = call_correlations.get(app_row["call_id"])
            correlation = (request_id, app_row["span_id"])
            if existing is not None and existing[0] != request_id:
                raise EvidenceError("A call ID maps to multiple request IDs.")
            call_correlations[app_row["call_id"]] = correlation
        elif app_row["name"] == "askhuman.acs.callback":
            if not app_row["call_id"] or not app_row["event_id"] or not app_row["span_id"]:
                raise EvidenceError("Callback evidence lacks opaque correlation fields.")
            deliveries.append(
                Delivery(
                    request_id=request_id,
                    call_id=app_row["call_id"],
                    event_id=app_row["event_id"],
                    delivery_id=app_row["span_id"],
                    received_at=observed_at,
                )
            )
        elif app_row["name"] == "askhuman.request" and app_row["pending_join"]:
            if not app_row["span_id"]:
                raise EvidenceError("Pending-join evidence lacks a span ID.")
            pending_joins.append(
                PendingJoin(
                    request_id=request_id,
                    event_id=app_row["span_id"],
                    observed_at=observed_at,
                )
            )

    attempts: list[Attempt] = []
    seen_attempts: set[tuple[str, str]] = set()
    for provider_row in provider_rows:
        key = (provider_row["attempt_id"], provider_row["call_id"])
        if not all(key) or key in seen_attempts:
            continue
        seen_attempts.add(key)
        provider_correlation = call_correlations.get(provider_row["call_id"])
        if provider_correlation is None:
            raise EvidenceError("An ACS create-call attempt has no exact application correlation.")
        attempts.append(
            Attempt(
                request_id=provider_correlation[0],
                attempt_id=provider_row["attempt_id"],
                call_id=provider_row["call_id"],
            )
        )

    correlated_calls = {attempt.call_id for attempt in attempts}
    if set(call_correlations) != correlated_calls:
        raise EvidenceError("An application create-call correlation lacks ACS provider evidence.")

    return ProviderEvidence(
        record=record,
        revision=revision,
        window_start=start,
        complete_through=min(watermarks),
        attempts=attempts,
        deliveries=deliveries,
        pending_joins=pending_joins,
    )


def _column_name(column: object) -> str:
    if isinstance(column, str):
        return column
    name = getattr(column, "name", None)
    if not isinstance(name, str):
        raise EvidenceError("Log Analytics returned an unnamed column.")
    return name


def _query_rows(client: LogsQueryClient, workspace: str, query: str) -> list[dict[str, object]]:
    result = cast(QueryResult, client.query_workspace(workspace, query, timespan=None))
    if result.status != LogsQueryStatus.SUCCESS or len(result.tables) != 1:
        raise EvidenceError("Log Analytics returned a partial or malformed result.")
    table = result.tables[0]
    columns = [_column_name(column) for column in table.columns]
    return [dict(zip(columns, row, strict=True)) for row in table.rows]


def _watermark(client: LogsQueryClient, workspace: str, query: str) -> datetime:
    rows = _query_rows(client, workspace, query)
    if len(rows) != 1 or not isinstance(rows[0].get("complete_through"), datetime):
        raise EvidenceError("The workspace ingestion watermark is unavailable.")
    return cast(datetime, rows[0]["complete_through"])


def _provider_rows(rows: Sequence[Mapping[str, object]]) -> list[ProviderRow]:
    return [
        ProviderRow(attempt_id=str(row.get("attempt_id", "")), call_id=str(row.get("call_id", "")))
        for row in rows
    ]


def _app_rows(rows: Sequence[Mapping[str, object]]) -> list[AppRow]:
    converted: list[AppRow] = []
    for row in rows:
        observed_at = row.get("observed_at")
        if not isinstance(observed_at, datetime):
            raise EvidenceError("Application evidence has an invalid timestamp.")
        converted.append(
            AppRow(
                observed_at=observed_at,
                span_id=str(row.get("span_id", "")),
                name=str(row.get("name", "")),
                request_id=str(row.get("request_id", "")),
                call_id=str(row.get("call_id", "")),
                event_id=str(row.get("event_id", "")),
                pending_join=row.get("pending_join") is True,
            )
        )
    return converted


def _kql_string(value: str) -> str:
    return json.dumps(value)


def _write(path: Path, evidence: BaseModel) -> None:
    path.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _parse_datetime(value: str) -> datetime:
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, EvidenceError) as error:
        raise argparse.ArgumentTypeError(
            "Expected an ISO-8601 timestamp with an offset."
        ) from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("provider", "telemetry"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--window-start", required=True, type=_parse_datetime)
    parser.add_argument("--complete-through", required=True, type=_parse_datetime)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--record", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    try:
        with LogsQueryClient(credential) as client:
            app_watermark = _watermark(
                client,
                args.workspace,
                APP_WATERMARK_QUERY.format(
                    window_start=args.window_start.isoformat(),
                    revision=_kql_string(args.revision),
                ),
            )
            if args.mode == "telemetry":
                if app_watermark < args.complete_through:
                    raise EvidenceError("Application telemetry ingestion is incomplete.")
                _write(
                    args.output,
                    TelemetryEvidence(
                        record=args.record,
                        revision=args.revision,
                        workspace=args.workspace,
                        complete_through=app_watermark,
                    ),
                )
                return 0

            provider_query = PROVIDER_QUERY.format(window_start=args.window_start.isoformat())
            app_query = APP_QUERY.format(
                window_start=args.window_start.isoformat(),
                revision=_kql_string(args.revision),
            )
            provider_watermark = _watermark(
                client,
                args.workspace,
                PROVIDER_WATERMARK_QUERY.format(window_start=args.window_start.isoformat()),
            )
            evidence = build_provider_evidence(
                provider_rows=_provider_rows(_query_rows(client, args.workspace, provider_query)),
                app_rows=_app_rows(_query_rows(client, args.workspace, app_query)),
                provider_watermark=provider_watermark,
                app_watermark=app_watermark,
                window_start=args.window_start,
                required_complete_through=args.complete_through,
                revision=args.revision,
                record=args.record,
            )
            _write(args.output, evidence)
            return 0
    except EvidenceError as error:
        parser.exit(2, f"Evidence unavailable: {error}\n")
    finally:
        credential.close()


if __name__ == "__main__":
    raise SystemExit(main())
