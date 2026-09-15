"""Content-free OpenTelemetry spans and metrics for Ask My Human."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from threading import Lock
from uuid import UUID, uuid4

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Meter, Observation
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from ask_my_human.application.ports import TelemetryOperation
from ask_my_human.contracts import Outcome, RequestKind, RequestStatus
from ask_my_human.errors import ErrorCode

INSTRUMENTATION_NAME = "ask_my_human"


class SpanName(StrEnum):
    REQUEST = "askhuman.request"
    POSTGRES = "askhuman.postgres"
    ACS_CREATE_CALL = "askhuman.acs.create_call"
    ACS_CALLBACK = "askhuman.acs.callback"
    ACS_RECOGNIZE = "askhuman.acs.recognize"


class Dependency(StrEnum):
    POSTGRES = "postgres"
    ACS = "acs"


class DependencyOperation(StrEnum):
    INSERT = "insert"
    TERMINAL_UPDATE = "terminal_update"
    REPLAY_READ = "replay_read"
    CREATE_CALL = "create_call"
    CALLBACK = "callback"
    RECOGNIZE = "recognize"


_OPERATION_SPANS = {
    TelemetryOperation.ASK: SpanName.REQUEST,
    TelemetryOperation.CALLBACK: SpanName.ACS_CALLBACK,
    TelemetryOperation.REPOSITORY: SpanName.POSTGRES,
}


class AzureMonitorTelemetry:
    """Telemetry port implementation with an explicit attribute allowlist."""

    def __init__(self, *, tracer: Tracer | None = None, meter: Meter | None = None) -> None:
        self._tracer = tracer or trace.get_tracer(INSTRUMENTATION_NAME)
        selected_meter = meter or metrics.get_meter(INSTRUMENTATION_NAME)
        self._request_count = selected_meter.create_counter(
            "askhuman_requests_total",
            description="Completed Ask My Human requests",
        )
        self._duration = selected_meter.create_histogram(
            "askhuman_duration_ms",
            unit="ms",
            description="Completed request duration",
        )
        self._dependency_failures = selected_meter.create_counter(
            "askhuman_dependency_failures_total",
            description="Dependency failures",
        )
        self._pending = 0
        self._pending_lock = Lock()
        self._pending_gauge = selected_meter.create_observable_gauge(
            "askhuman_pending",
            callbacks=[self._observe_pending],
            description="Whether this replica has a pending request",
        )

    @staticmethod
    def new_request_id() -> UUID:
        """Return an opaque correlation identifier unrelated to request content."""
        return uuid4()

    def record(
        self,
        *,
        operation: TelemetryOperation,
        request_id: UUID,
        kind: RequestKind | None = None,
        status: RequestStatus | None = None,
        outcome: Outcome | None = None,
        acs_code: int | None = None,
        elapsed_ms: int | None = None,
        replay: bool | None = None,
    ) -> None:
        with self.span(
            _OPERATION_SPANS[operation],
            request_id=request_id,
            kind=kind,
            status=status,
            outcome=outcome,
            acs_code=acs_code,
            elapsed_ms=elapsed_ms,
            replay=replay,
        ):
            pass

        if (
            operation is not TelemetryOperation.ASK
            or kind is None
            or status is None
            or outcome is None
        ):
            return

        metric_attributes = {
            "kind": kind.value,
            "status": status.value,
            "outcome": outcome.value,
        }
        self._request_count.add(1, metric_attributes)
        if elapsed_ms is not None:
            self._duration.record(elapsed_ms, metric_attributes)

    @contextmanager
    def span(
        self,
        name: SpanName,
        *,
        request_id: UUID,
        kind: RequestKind | None = None,
        status: RequestStatus | None = None,
        outcome: Outcome | None = None,
        elapsed_ms: int | None = None,
        acs_event_type: str | None = None,
        acs_code: int | None = None,
        acs_subcode: int | None = None,
        replay: bool | None = None,
    ) -> Iterator[Span]:
        attributes: dict[str, str | int | bool] = {"request_id": str(request_id)}
        optional_attributes: tuple[tuple[str, object | None], ...] = (
            ("kind", kind.value if kind is not None else None),
            ("status", status.value if status is not None else None),
            ("outcome", outcome.value if outcome is not None else None),
            ("elapsed_ms", elapsed_ms),
            ("acs_event_type", acs_event_type),
            ("acs_code", acs_code),
            ("acs_subcode", acs_subcode),
            ("replay", replay),
        )
        attributes.update(
            (attribute_name, value)
            for attribute_name, value in optional_attributes
            if isinstance(value, (str, int, bool))
        )

        with self._tracer.start_as_current_span(
            name.value,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as current_span:
            try:
                yield current_span
            except Exception:
                current_span.set_status(Status(StatusCode.ERROR))
                raise

    def record_dependency_failure(
        self,
        *,
        dependency: Dependency,
        operation: DependencyOperation,
        acs_code: int | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        attributes: dict[str, str | int] = {
            "dependency": dependency.value,
            "operation": operation.value,
        }
        if acs_code is not None:
            attributes["acs_code"] = acs_code
        if error_code is not None:
            attributes["error_code"] = error_code.value
        self._dependency_failures.add(1, attributes)

    def set_pending(self, pending: bool) -> None:
        with self._pending_lock:
            self._pending = int(pending)

    def _observe_pending(self, options: CallbackOptions) -> Iterator[Observation]:
        del options
        with self._pending_lock:
            pending = self._pending
        yield Observation(pending)


def configure_observability(*, connection_string: str | None = None) -> AzureMonitorTelemetry:
    """Configure Azure Monitor before the ASGI application begins serving."""
    options: dict[str, object] = {
        "instrumentation_options": {
            "fastapi": {"enabled": True},
            "psycopg2": {"enabled": False},
        },
        "resource": Resource.create({"service.name": "ask-my-human"}),
    }
    if connection_string is not None:
        options["connection_string"] = connection_string
    configure_azure_monitor(**options)
    return AzureMonitorTelemetry()
