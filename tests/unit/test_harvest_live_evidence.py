"""Offline tests for the fail-closed live evidence harvester."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from scripts.harvest_live_evidence import (
    AppRow,
    EvidenceError,
    ProviderRow,
    build_provider_evidence,
)


def _rows() -> tuple[list[ProviderRow], list[AppRow], datetime, str]:
    observed = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    request_id = str(uuid4())
    provider = [ProviderRow(attempt_id="provider-operation", call_id="opaque-call")]
    app = [
        AppRow(
            observed_at=observed,
            span_id="create-span",
            name="askhuman.acs.create_call",
            request_id=request_id,
            call_id="opaque-call",
            event_id="",
            pending_join=False,
        ),
        AppRow(
            observed_at=observed + timedelta(seconds=1),
            span_id="delivery-one",
            name="askhuman.acs.callback",
            request_id=request_id,
            call_id="opaque-call",
            event_id="cloud-event",
            pending_join=False,
        ),
        AppRow(
            observed_at=observed + timedelta(seconds=2),
            span_id="delivery-two",
            name="askhuman.acs.callback",
            request_id=request_id,
            call_id="opaque-call",
            event_id="cloud-event",
            pending_join=False,
        ),
        AppRow(
            observed_at=observed + timedelta(seconds=1),
            span_id="join-span",
            name="askhuman.request",
            request_id=request_id,
            call_id="",
            event_id="",
            pending_join=True,
        ),
    ]
    return provider, app, observed, request_id


def test_maps_exact_provider_and_content_free_app_correlations() -> None:
    provider, app, observed, request_id = _rows()
    complete = observed + timedelta(minutes=1)

    evidence = build_provider_evidence(
        provider_rows=provider,
        app_rows=app,
        provider_watermark=complete + timedelta(seconds=1),
        app_watermark=complete + timedelta(seconds=2),
        window_start=observed - timedelta(seconds=1),
        required_complete_through=complete,
        revision="revision-1",
        record="operator-export-1",
    )

    assert evidence.attempts[0].request_id == UUID(request_id)
    assert evidence.attempts[0].attempt_id == "provider-operation"
    assert {delivery.delivery_id for delivery in evidence.deliveries} == {
        "delivery-one",
        "delivery-two",
    }
    assert evidence.pending_joins[0].event_id == "join-span"
    assert evidence.attempt_source == "acs-provider"
    assert evidence.delivery_source == "content-free-app-telemetry"


@pytest.mark.parametrize("lagging", ["provider", "app"])
def test_rejects_incomplete_ingestion_window(lagging: str) -> None:
    provider, app, observed, _ = _rows()
    required = observed + timedelta(minutes=1)
    watermarks = {
        "provider": required + timedelta(seconds=1),
        "app": required + timedelta(seconds=1),
    }
    watermarks[lagging] = required - timedelta(microseconds=1)

    with pytest.raises(EvidenceError, match="incomplete"):
        build_provider_evidence(
            provider_rows=provider,
            app_rows=app,
            provider_watermark=watermarks["provider"],
            app_watermark=watermarks["app"],
            window_start=observed - timedelta(seconds=1),
            required_complete_through=required,
            revision="revision-1",
            record="operator-export-1",
        )


def test_rejects_provider_attempt_without_exact_app_call_join() -> None:
    provider, app, observed, _ = _rows()
    provider[0]["call_id"] = "unmatched-call"
    complete = observed + timedelta(minutes=1)

    with pytest.raises(EvidenceError, match="no exact application correlation"):
        build_provider_evidence(
            provider_rows=provider,
            app_rows=app,
            provider_watermark=complete,
            app_watermark=complete,
            window_start=observed - timedelta(seconds=1),
            required_complete_through=complete,
            revision="revision-1",
            record="operator-export-1",
        )


def test_serialized_evidence_excludes_payload_and_secret_fields() -> None:
    provider, app, observed, _ = _rows()
    complete = observed + timedelta(minutes=1)
    evidence = build_provider_evidence(
        provider_rows=provider,
        app_rows=app,
        provider_watermark=complete,
        app_watermark=complete,
        window_start=observed - timedelta(seconds=1),
        required_complete_through=complete,
        revision="revision-1",
        record="operator-export-1",
    )

    output = evidence.model_dump_json()
    for forbidden in ("prompt", "answer", "phone", "credential", "connection_string"):
        assert forbidden not in output.lower()
