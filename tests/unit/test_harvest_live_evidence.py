"""Offline evidence-contract and Log Analytics export regressions."""

import json
import logging
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from azure.monitor.query import LogsQueryClient, LogsQueryPartialResult, LogsQueryResult, LogsTable

from ask_my_human.live_evidence import EvidenceSnapshot, ExportScope, read_reviewed_snapshot
from scripts import harvest_live_evidence as harvester

WORKSPACE = UUID("11111111-1111-4111-8111-111111111111")
REVISION = "reviewed-app--bbbbbbbbbbbb-aaaaaaaaaaaa"
RESOURCE_PREFIX = "/subscriptions/22222222-2222-4222-8222-222222222222/resourceGroups/reviewed"
ACS_RESOURCE = RESOURCE_PREFIX + "/providers/Microsoft.Communication/communicationServices/calls"
APP_RESOURCE = RESOURCE_PREFIX + "/providers/Microsoft.Insights/components/telemetry"
CALL_HASH = sha256(b"provider-call").hexdigest()
NOW = datetime(2026, 9, 16, 10, tzinfo=UTC)


def snapshot_payload() -> dict[str, object]:
    request_id = str(uuid4())
    observed_at = (NOW - timedelta(minutes=2)).isoformat()
    return {
        "source": "log-analytics-snapshot",
        "record": "export-record",
        "revision": REVISION,
        "workspace": str(WORKSPACE),
        "acs_resource_id": ACS_RESOURCE,
        "application_insights_resource_id": APP_RESOURCE,
        "window_start": (NOW - timedelta(minutes=5)).isoformat(),
        "window_end": (NOW - timedelta(minutes=1)).isoformat(),
        "queried_at": NOW.isoformat(),
        "provider_query_sha256": "a" * 64,
        "application_query_sha256": "b" * 64,
        "provider": {
            "source": "acs-provider",
            "table": "ACSCallAutomationIncomingOperations",
            "attempts": [
                {
                    "call_id_sha256": CALL_HASH,
                    "correlation_id_sha256": sha256(b"provider-correlation").hexdigest(),
                    "observed_at": observed_at,
                    "result_code": 201,
                }
            ],
        },
        "application": {
            "source": "application-observations",
            "table": "AppDependencies",
            "correlations": [
                {
                    "request_id": request_id,
                    "call_id_sha256": CALL_HASH,
                    "observed_at": observed_at,
                }
            ],
            "deliveries": [],
            "pending_joins": [],
        },
    }


def review_payload(snapshot: bytes) -> dict[str, object]:
    return {
        "source": "operator-export-review",
        "record": "review-record",
        "reviewer": "approved-reviewer",
        "snapshot_sha256": sha256(snapshot).hexdigest(),
        "reviewed_at": NOW.isoformat(),
        "diagnostics_verified": True,
        "sampling_disabled": True,
        "ingestion_checked": True,
        "late_arrival_risk_accepted": True,
    }


def read_review(snapshot: bytes, review: dict[str, object]) -> EvidenceSnapshot:
    return read_reviewed_snapshot(
        snapshot,
        json.dumps(review).encode(),
        revision=REVISION,
        workspace=WORKSPACE,
        acs_resource_id=ACS_RESOURCE,
        application_insights_resource_id=APP_RESOURCE,
        reviewer="approved-reviewer",
        now=NOW,
    )


def test_review_binds_exact_snapshot_without_claiming_ingestion_completeness() -> None:
    raw = json.dumps(snapshot_payload()).encode()
    evidence = read_review(raw, review_payload(raw))
    assert evidence.provider.source == "acs-provider"
    assert evidence.application.source == "application-observations"
    assert "complete_through" not in evidence.model_dump_json()
    assert "request_id" not in evidence.provider.model_dump_json()
    assert evidence.provider.attempts[0].call_id_sha256 == CALL_HASH


@pytest.mark.parametrize(
    "field",
    [
        "diagnostics_verified",
        "sampling_disabled",
        "ingestion_checked",
        "late_arrival_risk_accepted",
    ],
)
@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_review_rejects_missing_or_coerced_proof(field: str, value: object) -> None:
    raw = json.dumps(snapshot_payload()).encode()
    review = review_payload(raw)
    review[field] = value
    with pytest.raises(ValueError):
        read_review(raw, review)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("snapshot_sha256", "0" * 64),
        ("reviewer", "other-reviewer"),
        ("reviewed_at", (NOW - timedelta(seconds=1)).isoformat()),
        ("reviewed_at", (NOW + timedelta(seconds=1)).isoformat()),
        ("source", "log-analytics-export"),
    ],
)
def test_review_rejects_stale_unbound_or_automated_attestations(field: str, value: object) -> None:
    raw = json.dumps(snapshot_payload()).encode()
    review = review_payload(raw)
    review[field] = value
    with pytest.raises(ValueError):
        read_review(raw, review)


def test_review_rejects_even_whitespace_changes_to_an_export() -> None:
    raw = json.dumps(snapshot_payload()).encode()
    with pytest.raises(ValueError):
        read_review(raw + b"\n", review_payload(raw))


@pytest.mark.parametrize(
    "field", ["revision", "acs_resource_id", "application_insights_resource_id"]
)
def test_review_rejects_wrong_deployment_scope(field: str) -> None:
    payload = snapshot_payload()
    payload[field] = "other-target"
    raw = json.dumps(payload).encode()
    with pytest.raises(ValueError):
        read_review(raw, review_payload(raw))


@pytest.mark.parametrize("section", ["provider", "application"])
def test_unreconciled_provider_calls_are_not_silently_discarded(section: str) -> None:
    payload = snapshot_payload()
    values = payload[section]
    assert isinstance(values, dict)
    values["attempts" if section == "provider" else "correlations"] = []
    with pytest.raises(ValueError, match="reconcile"):
        EvidenceSnapshot.model_validate_json(json.dumps(payload))


def test_provider_rows_are_preserved_even_when_identifiers_repeat() -> None:
    payload = snapshot_payload()
    provider = payload["provider"]
    assert isinstance(provider, dict)
    provider["attempts"] *= 2
    evidence = EvidenceSnapshot.model_validate_json(json.dumps(payload))
    assert len(evidence.provider.attempts) == 2


@pytest.mark.parametrize("value", ["2026-09-16T10:00:00", "2026-09-17T10:00:00Z"])
def test_snapshot_rejects_naive_or_inverted_windows(value: str) -> None:
    payload = snapshot_payload()
    payload["window_start"] = value
    with pytest.raises(ValueError):
        EvidenceSnapshot.model_validate_json(json.dumps(payload))


def query_result(columns: list[str], rows: list[list[object]]) -> LogsQueryResult:
    column_types = [
        "datetime"
        if column in {"observed_at", "received_at"}
        else "long"
        if column in {"result_code", "item_count"}
        else "string"
        for column in columns
    ]
    return LogsQueryResult(
        tables=[LogsTable(columns=columns, columns_types=column_types, rows=rows)]
    )


def export_setup() -> tuple[MagicMock, ExportScope]:
    snapshot = EvidenceSnapshot.model_validate_json(json.dumps(snapshot_payload()))
    scope = ExportScope.model_validate(
        {name: getattr(snapshot, name) for name in ExportScope.model_fields}
    )
    correlation = snapshot.application.correlations[0]
    client = MagicMock()
    client.query_workspace.side_effect = [
        query_result(
            harvester.PROVIDER_COLUMNS,
            [
                [
                    CALL_HASH,
                    "c" * 64,
                    correlation.observed_at,
                    201,
                ]
            ],
        ),
        query_result(
            harvester.APPLICATION_COLUMNS,
            [
                [
                    "askhuman.acs.call_created",
                    correlation.observed_at,
                    str(correlation.request_id),
                    CALL_HASH,
                    "",
                    "",
                    None,
                    "d" * 32 + "/" + "e" * 16,
                    1,
                ]
            ],
        ),
    ]
    return client, scope


def test_harvester_uses_bounded_scoped_allowlisted_queries() -> None:
    client, scope = export_setup()
    snapshot = harvester.collect_snapshot(client, scope, record="export-record", clock=lambda: NOW)
    assert len(snapshot.provider.attempts) == 1
    assert len(snapshot.application.correlations) == 1
    assert snapshot.queried_at == NOW
    assert client.query_workspace.call_count == 2
    provider, application = harvester.build_queries(scope)
    assert 'OperationName =~ "CreateCall"' in provider
    assert "OperationId" not in provider
    assert "distinct" not in provider and "summarize" not in provider
    assert "hash_sha256(CallConnectionId)" in provider
    assert json.dumps(ACS_RESOURCE) in provider
    assert json.dumps(APP_RESOURCE) in application
    assert f"AppVersion == {json.dumps(REVISION)}" in application
    assert "TimeGenerated between" in provider and "TimeGenerated between" in application
    assert "ingestion_time" not in provider + application
    for call in client.query_workspace.call_args_list:
        assert call.args[0] == str(WORKSPACE)
        assert call.kwargs["timespan"] == (scope.window_start, scope.window_end)
    assert snapshot.provider_query_sha256 == sha256(provider.encode()).hexdigest()


@pytest.mark.parametrize(
    "response",
    [
        LogsQueryPartialResult(),
        LogsQueryResult(tables=[]),
        query_result(["unexpected"], [["prompt-SENSITIVE"]]),
    ],
)
def test_harvester_rejects_partial_and_unexpected_results(response: object) -> None:
    client, scope = export_setup()
    client.query_workspace.side_effect = [response]
    with pytest.raises(ValueError):
        harvester.collect_snapshot(client, scope, record="export-record", clock=lambda: NOW)


def test_harvester_rejects_oversized_windows_without_silent_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, scope = export_setup()
    monkeypatch.setattr(harvester, "MAX_ROWS", 0)
    with pytest.raises(ValueError, match="truncated"):
        harvester.collect_snapshot(client, scope, record="export-record", clock=lambda: NOW)


def test_harvester_preserves_duplicate_receipts_and_pending_joins() -> None:
    client, scope = export_setup()
    results = list(client.query_workspace.side_effect)
    row = list(results[1].tables[0].rows[0])
    callback = row.copy()
    callback[0] = "askhuman.acs.callback_accepted"
    callback[4:7] = ["f" * 64, str(uuid4()), row[1]]
    duplicate = callback.copy()
    duplicate[5] = str(uuid4())
    join = row.copy()
    join[0], join[3] = "askhuman.request.join_pending", ""
    results[1] = query_result(harvester.APPLICATION_COLUMNS, [row, callback, duplicate, join])
    client.query_workspace.side_effect = results
    snapshot = harvester.collect_snapshot(client, scope, record="export-record", clock=lambda: NOW)
    deliveries = snapshot.application.deliveries
    assert len(deliveries) == 2
    assert deliveries[0].event_id_sha256 == deliveries[1].event_id_sha256
    assert deliveries[0].delivery_id != deliveries[1].delivery_id
    assert len(snapshot.application.pending_joins) == 1


@pytest.mark.parametrize("count", [0, 2, None, True, "1"])
def test_harvester_rejects_sampled_or_unknown_sample_counts(count: object) -> None:
    client, scope = export_setup()
    results = list(client.query_workspace.side_effect)
    row = list(results[1].tables[0].rows[0])
    row[-1] = count
    results[1] = query_result(harvester.APPLICATION_COLUMNS, [row])
    client.query_workspace.side_effect = results
    with pytest.raises(ValueError, match="Sampled"):
        harvester.collect_snapshot(client, scope, record="export-record", clock=lambda: NOW)


@pytest.mark.parametrize("value", [None, 123, "2026-09-16T10:00:00", "not-a-date"])
def test_harvester_rejects_missing_or_naive_row_times(value: object) -> None:
    with pytest.raises(ValueError):
        harvester._timestamp(value)


def test_harvester_accepts_explicit_offset_timestamps() -> None:
    assert harvester._timestamp(NOW.isoformat()) == NOW


def test_harvester_rejects_future_windows_before_querying() -> None:
    client, scope = export_setup()
    with pytest.raises(ValueError, match="future"):
        harvester.collect_snapshot(
            client,
            scope,
            record="export-record",
            clock=lambda: scope.window_start,
        )
    client.query_workspace.assert_not_called()


def test_harvester_rejects_unknown_observation_names() -> None:
    client, scope = export_setup()
    results = list(client.query_workspace.side_effect)
    row = list(results[1].tables[0].rows[0])
    row[0] = "askhuman.request"
    results[1] = query_result(harvester.APPLICATION_COLUMNS, [row])
    client.query_workspace.side_effect = results
    with pytest.raises(ValueError, match="Unknown"):
        harvester.collect_snapshot(client, scope, record="export-record", clock=lambda: NOW)


@pytest.mark.parametrize("case", ["conflict", "unmapped_delivery", "early_receipt", "late_row"])
def test_snapshot_rejects_inconsistent_application_observations(case: str) -> None:
    payload = snapshot_payload()
    application = payload["application"]
    assert isinstance(application, dict)
    correlation = application["correlations"][0]
    if case == "conflict":
        application["correlations"].append(correlation | {"request_id": str(uuid4())})
    elif case == "late_row":
        application["pending_joins"] = [
            {
                "request_id": correlation["request_id"],
                "observation_id": "d" * 32 + "/" + "e" * 16,
                "observed_at": NOW.isoformat(),
            }
        ]
    else:
        application["deliveries"] = [
            {
                "request_id": str(uuid4())
                if case == "unmapped_delivery"
                else correlation["request_id"],
                "call_id_sha256": CALL_HASH,
                "event_id_sha256": "f" * 64,
                "delivery_id": str(uuid4()),
                "observed_at": correlation["observed_at"],
                "received_at": (NOW - timedelta(hours=1)).isoformat(),
            }
        ]
    with pytest.raises(ValueError):
        EvidenceSnapshot.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("failure", [False, True])
def test_cli_exports_only_snapshot_and_suppresses_failed_query_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure: bool,
) -> None:
    client, scope = export_setup()
    client.__enter__.return_value = client
    monkeypatch.setattr(harvester, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(harvester, "LogsQueryClient", MagicMock(return_value=client))
    collect = harvester.collect_snapshot

    def collect_at_fixed_time(
        client: LogsQueryClient,
        scope: ExportScope,
        *,
        record: str,
    ) -> EvidenceSnapshot:
        return collect(client, scope, record=record, clock=lambda: NOW)

    monkeypatch.setattr(harvester, "collect_snapshot", collect_at_fixed_time)
    if failure:
        client.query_workspace.side_effect = RuntimeError("token-SENSITIVE +15551234567")
    output = tmp_path / "evidence.json"
    arguments = ["--record", "export-record", "--output", str(output)]
    for key, value in scope.model_dump(mode="json").items():
        arguments.extend(["--" + key.replace("_", "-"), str(value)])
    previous_logging = logging.root.manager.disable
    assert harvester.main(arguments) == (1 if failure else 0)
    assert logging.root.manager.disable == previous_logging
    captured = capsys.readouterr()
    assert "SENSITIVE" not in captured.out + captured.err
    assert "+15551234567" not in captured.out + captured.err
    if failure:
        assert not output.exists()
        assert "failed" in captured.err
    else:
        raw = output.read_bytes()
        snapshot = EvidenceSnapshot.model_validate_json(raw)
        assert snapshot.provider.source == "acs-provider"
        assert sha256(raw).hexdigest() in captured.out
        assert "separate operator export review" in captured.out
        assert list(tmp_path.iterdir()) == [output]
        assert b"provider-call" not in raw


def test_cli_never_overwrites_existing_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, scope = export_setup()
    credential = MagicMock()
    monkeypatch.setattr(harvester, "DefaultAzureCredential", credential)
    output = tmp_path / "evidence.json"
    output.write_bytes(b"reviewed existing export")
    arguments = ["--record", "export-record", "--output", str(output)]
    for key, value in scope.model_dump(mode="json").items():
        arguments.extend(["--" + key.replace("_", "-"), str(value)])
    assert harvester.main(arguments) == 1
    assert output.read_bytes() == b"reviewed existing export"
    credential.assert_not_called()
