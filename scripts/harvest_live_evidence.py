"""Read-only, content-free Log Analytics snapshots; never generates an export review."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryResult, LogsQueryStatus

from ask_my_human.live_evidence import (
    ApplicationEvidence,
    CallbackDelivery,
    CallCorrelation,
    EvidenceSnapshot,
    ExportScope,
    PendingJoin,
    ProviderAttempt,
    ProviderEvidence,
)

MAX_ROWS = 10000
PROVIDER_COLUMNS = ["call_id_sha256", "correlation_id_sha256", "observed_at", "result_code"]
APPLICATION_COLUMNS = [
    "operation",
    "observed_at",
    "request_id",
    "call_id_sha256",
    "event_id_sha256",
    "delivery_id",
    "received_at",
    "observation_id",
    "item_count",
]


def build_queries(scope: ExportScope) -> tuple[str, str]:
    window = (
        f"| where TimeGenerated between (datetime({scope.window_start.isoformat()})"
        f" .. datetime({scope.window_end.isoformat()}))"
    )
    provider = "\n".join(
        (
            "ACSCallAutomationIncomingOperations",
            f"| where _ResourceId =~ {json.dumps(scope.acs_resource_id)}",
            window,
            '| where OperationName =~ "CreateCall"',
            '| project call_id_sha256=iff(isempty(CallConnectionId), "", '
            "hash_sha256(CallConnectionId)),",
            'correlation_id_sha256=iff(isempty(CorrelationId), "", hash_sha256(CorrelationId)),',
            "observed_at=TimeGenerated, result_code=ResultSignature",
            f"| take {MAX_ROWS + 1}",
        )
    )
    application = "\n".join(
        (
            "AppDependencies",
            f"| where _ResourceId =~ {json.dumps(scope.application_insights_resource_id)}",
            window,
            '| where AppRoleName == "ask-my-human"',
            f"| where AppVersion == {json.dumps(scope.revision)}",
            '| where Name in ("askhuman.acs.call_created", "askhuman.acs.callback_accepted",',
            '"askhuman.request.join_pending")',
            "| project operation=Name, observed_at=TimeGenerated,",
            "request_id=tostring(Properties.request_id),",
            "call_id_sha256=tostring(Properties.call_id_sha256),",
            "event_id_sha256=tostring(Properties.event_id_sha256),",
            "delivery_id=tostring(Properties.delivery_id),",
            "received_at=todatetime(Properties.received_at),",
            'observation_id=strcat(OperationId, "/", Id), item_count=ItemCount',
            f"| take {MAX_ROWS + 1}",
        )
    )
    return provider, application


def _rows(
    client: LogsQueryClient, scope: ExportScope, query: str, columns: list[str]
) -> list[dict[str, object]]:
    result = client.query_workspace(
        str(scope.workspace),
        query,
        timespan=(scope.window_start, scope.window_end),
        server_timeout=120,
    )
    if not isinstance(result, LogsQueryResult) or result.status != LogsQueryStatus.SUCCESS:
        raise ValueError("A complete query response is required; partial results are rejected.")
    if len(result.tables) != 1:
        raise ValueError("Unexpected query result tables.")
    table = result.tables[0]
    if table.columns != columns or len(table.rows) > MAX_ROWS:
        raise ValueError("Unexpected query schema or truncated export window.")
    return [dict(zip(columns, row, strict=True)) for row in table.rows]


def _timestamp(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Evidence timestamps must include a UTC offset.")
    return value


def _application_evidence(rows: list[dict[str, object]]) -> ApplicationEvidence:
    correlations: list[CallCorrelation] = []
    deliveries: list[CallbackDelivery] = []
    joins: list[PendingJoin] = []
    for row in rows:
        if type(row["item_count"]) is not int or row["item_count"] != 1:
            raise ValueError("Sampled or unweighted application rows cannot prove observations.")
        common = {
            "request_id": UUID(str(row["request_id"])),
            "observed_at": _timestamp(row["observed_at"]),
        }
        if row["operation"] == "askhuman.acs.call_created":
            correlations.append(
                CallCorrelation.model_validate(common | {"call_id_sha256": row["call_id_sha256"]})
            )
        elif row["operation"] == "askhuman.acs.callback_accepted":
            deliveries.append(
                CallbackDelivery.model_validate(
                    common
                    | {
                        "call_id_sha256": row["call_id_sha256"],
                        "event_id_sha256": row["event_id_sha256"],
                        "delivery_id": UUID(str(row["delivery_id"])),
                        "received_at": _timestamp(row["received_at"]),
                    }
                )
            )
        elif row["operation"] == "askhuman.request.join_pending":
            joins.append(
                PendingJoin.model_validate(common | {"observation_id": row["observation_id"]})
            )
        else:
            raise ValueError("Unknown application observation.")
    return ApplicationEvidence(
        correlations=correlations, deliveries=deliveries, pending_joins=joins
    )


def collect_snapshot(
    client: LogsQueryClient,
    scope: ExportScope,
    *,
    record: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> EvidenceSnapshot:
    if scope.window_end > clock():
        raise ValueError("An export cannot include a future window.")
    provider_query, application_query = build_queries(scope)
    provider_rows = _rows(client, scope, provider_query, PROVIDER_COLUMNS)
    attempts = [
        ProviderAttempt.model_validate(row | {"observed_at": _timestamp(row["observed_at"])})
        for row in provider_rows
    ]
    application = _application_evidence(
        _rows(client, scope, application_query, APPLICATION_COLUMNS)
    )
    return EvidenceSnapshot(
        **scope.model_dump(),
        record=record,
        queried_at=clock(),
        provider_query_sha256=sha256(provider_query.encode()).hexdigest(),
        application_query_sha256=sha256(application_query.encode()).hexdigest(),
        provider=ProviderEvidence(attempts=attempts),
        application=application,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "workspace",
        "revision",
        "acs-resource-id",
        "application-insights-resource-id",
        "window-start",
        "window-end",
        "record",
        "output",
    ):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        scope = ExportScope.model_validate_json(
            json.dumps(
                {
                    "workspace": args.workspace,
                    "revision": args.revision,
                    "acs_resource_id": args.acs_resource_id,
                    "application_insights_resource_id": args.application_insights_resource_id,
                    "window_start": args.window_start,
                    "window_end": args.window_end,
                }
            )
        )
        output = Path(args.output)
        if output.exists():
            raise ValueError("Evidence exports must use a new path.")
        with DefaultAzureCredential() as credential, LogsQueryClient(credential) as client:
            snapshot = collect_snapshot(client, scope, record=args.record)
        encoded = (snapshot.model_dump_json(indent=2) + "\n").encode("utf-8")
        with output.open("xb") as handle:
            handle.write(encoded)
        print(f"Snapshot SHA-256: {sha256(encoded).hexdigest()}")
        print("Exported a bounded snapshot. A separate operator export review is required.")
        return 0
    except Exception:
        print(
            "Evidence export failed; query, correlation, scope, or output checks failed.",
            file=sys.stderr,
        )
        return 1
    finally:
        logging.disable(previous_logging)


if __name__ == "__main__":
    raise SystemExit(main())
