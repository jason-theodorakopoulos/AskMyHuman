"""Content-free OpenTelemetry spans and metrics for Ask My Human."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from threading import Lock
from uuid import UUID, uuid4

from azure.monitor.opentelemetry import configure_azure_monitor
from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Meter, Observation
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ask_my_human.application.ports import TelemetryOperation
from ask_my_human.contracts import Outcome, RequestKind, RequestStatus
from ask_my_human.errors import ErrorCode

INSTRUMENTATION_NAME = "ask_my_human"


class SpanName(StrEnum):
    REQUEST = "askhuman.request"
    JOIN_PENDING = "askhuman.request.join_pending"
    CALL_CREATED = "askhuman.acs.call_created"
    CALLBACK_ACCEPTED = "askhuman.acs.callback_accepted"
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
    TelemetryOperation.JOIN_PENDING: SpanName.JOIN_PENDING,
    TelemetryOperation.CALL_CREATED: SpanName.CALL_CREATED,
    TelemetryOperation.CALLBACK_ACCEPTED: SpanName.CALLBACK_ACCEPTED,
    TelemetryOperation.CALLBACK: SpanName.ACS_CALLBACK,
    TelemetryOperation.REPOSITORY: SpanName.POSTGRES,
    TelemetryOperation.CREATE_CALL: SpanName.ACS_CREATE_CALL,
    TelemetryOperation.RECOGNIZE: SpanName.ACS_RECOGNIZE,
}


class ContentFreeHttpTelemetry:
    def __init__(self, app: ASGIApp, *, tracer: Tracer) -> None:
        self.app = app
        self.tracer = tracer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "OTHER")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            method = "OTHER"
        carrier = {
            key.decode("ascii"): value.decode("ascii", errors="ignore")
            for key, value in scope.get("headers", [])
            if key == b"traceparent"
        }
        with self.tracer.start_as_current_span(
            "askhuman.http",
            kind=SpanKind.SERVER,
            context=TraceContextTextMapPropagator().extract(carrier),
            attributes={"http.request.method": method},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:

            async def send_response(message: Message) -> None:
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                    span.set_attribute("http.response.status_code", status_code)
                    if status_code >= 500:
                        span.set_status(Status(StatusCode.ERROR))
                await send(message)

            try:
                await self.app(scope, receive, send_response)
            except Exception:
                span.set_attribute("http.response.status_code", 500)
                span.set_status(Status(StatusCode.ERROR))
                raise


def instrument_app(app: FastAPI, *, tracer: Tracer | None = None) -> None:
    if not getattr(app.state, "content_free_telemetry", False):
        app.add_middleware(
            ContentFreeHttpTelemetry,
            tracer=tracer or trace.get_tracer(INSTRUMENTATION_NAME),
        )
        app.state.content_free_telemetry = True


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
        call_id: str | None = None,
        event_id: str | None = None,
        delivery_id: UUID | None = None,
        received_at: datetime | None = None,
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
            call_id=call_id,
            event_id=event_id,
            delivery_id=delivery_id,
            received_at=received_at,
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
        operation: TelemetryOperation | SpanName,
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
        call_id: str | None = None,
        event_id: str | None = None,
        delivery_id: UUID | None = None,
        received_at: datetime | None = None,
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
            ("call_id_sha256", sha256(call_id.encode()).hexdigest() if call_id else None),
            ("event_id_sha256", sha256(event_id.encode()).hexdigest() if event_id else None),
            ("delivery_id", str(delivery_id) if delivery_id is not None else None),
            ("received_at", received_at.isoformat() if received_at is not None else None),
        )
        attributes.update(
            (attribute_name, value)
            for attribute_name, value in optional_attributes
            if isinstance(value, (str, int, bool))
        )

        name = (
            _OPERATION_SPANS[operation] if isinstance(operation, TelemetryOperation) else operation
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

    def dependency_failed(
        self,
        operation: TelemetryOperation,
        *,
        acs_code: int | None = None,
        error_code: ErrorCode | None = None,
    ) -> None:
        mapped_operation = {
            TelemetryOperation.REPOSITORY: DependencyOperation.REPLAY_READ,
            TelemetryOperation.CREATE_CALL: DependencyOperation.CREATE_CALL,
            TelemetryOperation.RECOGNIZE: DependencyOperation.RECOGNIZE,
            TelemetryOperation.CALLBACK: DependencyOperation.CALLBACK,
            TelemetryOperation.ASK: DependencyOperation.CALLBACK,
        }.get(operation)
        if mapped_operation is None:
            return
        self.record_dependency_failure(
            dependency=(
                Dependency.POSTGRES
                if operation is TelemetryOperation.REPOSITORY
                else Dependency.ACS
            ),
            operation=mapped_operation,
            acs_code=acs_code,
            error_code=error_code,
        )

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
    """Configure Azure Monitor before the ASGI application begins serving.

    Local development and CI image validation run without an Application
    Insights resource. Skip Azure Monitor wiring when no connection string is
    supplied or configured through the environment so the process still starts
    and records telemetry against the default in-process providers only.
    """
    resolved_connection_string = connection_string or os.environ.get(
        "APPLICATIONINSIGHTS_CONNECTION_STRING"
    )
    if resolved_connection_string:
        resource_attributes = {"service.name": "ask-my-human"}
        revision = os.environ.get("CONTAINER_APP_REVISION")
        if revision:
            resource_attributes["service.version"] = revision
        configure_azure_monitor(
            connection_string=resolved_connection_string,
            sampling_ratio=1.0,
            instrumentation_options={
                name: {"enabled": False}
                for name in (
                    "azure_sdk",
                    "django",
                    "fastapi",
                    "flask",
                    "httpx",
                    "httpx2",
                    "psycopg2",
                    "requests",
                    "urllib",
                    "urllib3",
                )
            },
            disable_azure_core_tracing=True,
            disable_logging=True,
            enable_live_metrics=False,
            enable_performance_counters=False,
            resource=Resource.create(resource_attributes),
        )
    return AzureMonitorTelemetry()
