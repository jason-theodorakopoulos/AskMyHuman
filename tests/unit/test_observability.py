from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from uuid import UUID, uuid4

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from ask_my_human import observability
from ask_my_human.application.ports import TelemetryOperation
from ask_my_human.contracts import Outcome, RequestKind, RequestStatus
from ask_my_human.errors import ErrorCode
from ask_my_human.observability import (
    AzureMonitorTelemetry,
    Dependency,
    DependencyOperation,
    SpanName,
    configure_observability,
)

SENTINELS = (
    "prompt-SENSITIVE",
    "answer-SENSITIVE",
    "+15551234567",
    "idempotency-SENSITIVE",
    "token-SENSITIVE",
    '{"rawCallback":"SENSITIVE"}',
)


class CapturingSpanExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS


@pytest.fixture
def captured_telemetry() -> Iterator[
    tuple[AzureMonitorTelemetry, CapturingSpanExporter, InMemoryMetricReader]
]:
    span_exporter = CapturingSpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    telemetry = AzureMonitorTelemetry(
        tracer=tracer_provider.get_tracer("test"),
        meter=meter_provider.get_meter("test"),
    )
    yield telemetry, span_exporter, metric_reader
    tracer_provider.shutdown()
    meter_provider.shutdown()


def serialized_capture(exporter: CapturingSpanExporter, metric_reader: InMemoryMetricReader) -> str:
    spans = [
        {
            "name": span.name,
            "attributes": dict(span.attributes or {}),
            "events": [
                {"name": event.name, "attributes": dict(event.attributes or {})}
                for event in span.events
            ],
            "status": span.status.description,
        }
        for span in exporter.spans
    ]
    metrics = metric_reader.get_metrics_data()
    return json.dumps({"spans": spans, "metrics": str(metrics)}, sort_keys=True)


def test_record_emits_approved_request_span_and_low_cardinality_metrics(
    captured_telemetry: tuple[AzureMonitorTelemetry, CapturingSpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, exporter, metric_reader = captured_telemetry
    request_id = uuid4()

    telemetry.record(
        operation=TelemetryOperation.ASK,
        request_id=request_id,
        kind=RequestKind.APPROVAL,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.APPROVED,
        elapsed_ms=42,
        replay=False,
    )

    assert exporter.spans[0].name == SpanName.REQUEST.value
    assert exporter.spans[0].attributes == {
        "request_id": str(request_id),
        "kind": "approval",
        "status": "responded",
        "outcome": "approved",
        "elapsed_ms": 42,
        "replay": False,
    }
    capture = serialized_capture(exporter, metric_reader)
    assert "askhuman_requests_total" in capture
    assert "askhuman_duration_ms" in capture
    assert str(request_id) not in str(metric_reader.get_metrics_data())


def test_all_approved_spans_share_a_random_request_correlation_id(
    captured_telemetry: tuple[AzureMonitorTelemetry, CapturingSpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, exporter, _ = captured_telemetry
    first_request_id = telemetry.new_request_id()
    second_request_id = telemetry.new_request_id()

    for span_name in SpanName:
        with telemetry.span(span_name, request_id=first_request_id):
            pass

    assert isinstance(first_request_id, UUID)
    assert first_request_id != second_request_id
    assert {span.name for span in exporter.spans} == {span.value for span in SpanName}
    request_ids = set[object]()
    for span in exporter.spans:
        assert span.attributes is not None
        request_ids.add(span.attributes["request_id"])
    assert request_ids == {str(first_request_id)}


def test_dependency_failure_and_pending_gauge_use_only_approved_dimensions(
    captured_telemetry: tuple[AzureMonitorTelemetry, CapturingSpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, _, metric_reader = captured_telemetry
    telemetry.record_dependency_failure(
        dependency=Dependency.ACS,
        operation=DependencyOperation.CREATE_CALL,
        acs_code=500,
        error_code=ErrorCode.DEPENDENCY_FAILURE,
    )
    telemetry.set_pending(True)

    capture = str(metric_reader.get_metrics_data())
    assert "askhuman_dependency_failures_total" in capture
    assert "askhuman_pending" in capture
    assert "value=1" in capture
    assert "dependency" in capture
    assert "operation" in capture
    assert "acs_code" in capture
    assert "error_code" in capture


def test_sensitive_values_never_enter_spans_metrics_or_exception_telemetry(
    captured_telemetry: tuple[AzureMonitorTelemetry, CapturingSpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, exporter, metric_reader = captured_telemetry
    request_id = telemetry.new_request_id()

    telemetry.record(
        operation=TelemetryOperation.CALLBACK,
        request_id=request_id,
        kind=RequestKind.INPUT,
        status=RequestStatus.RESPONDED,
        outcome=Outcome.ANSWERED,
        acs_code=200,
        elapsed_ms=11,
        replay=True,
    )
    telemetry.record_dependency_failure(
        dependency=Dependency.POSTGRES,
        operation=DependencyOperation.REPLAY_READ,
        error_code=ErrorCode.INTERNAL,
    )
    with (
        pytest.raises(RuntimeError),
        telemetry.span(SpanName.ACS_RECOGNIZE, request_id=request_id),
    ):
        raise RuntimeError(" ".join(SENTINELS))

    capture = serialized_capture(exporter, metric_reader)
    for sentinel in SENTINELS:
        assert sentinel not in capture
    failed_span = exporter.spans[-1]
    assert failed_span.status.status_code.name == "ERROR"
    assert failed_span.status.description is None
    assert failed_span.events == ()


def test_setup_enables_asgi_and_excludes_psycopg2_instrumentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_options: dict[str, object] = {}

    def capture_configuration(**options: object) -> None:
        configured_options.update(options)

    monkeypatch.setattr(observability, "configure_azure_monitor", capture_configuration)

    telemetry = configure_observability(connection_string="InstrumentationKey=not-a-secret")

    assert isinstance(telemetry, AzureMonitorTelemetry)
    assert configured_options["instrumentation_options"] == {
        "fastapi": {"enabled": True},
        "psycopg2": {"enabled": False},
    }
