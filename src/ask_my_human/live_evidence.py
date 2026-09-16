"""Content-free, separately attributed evidence for operator-reviewed live tests."""

from datetime import datetime
from hashlib import sha256
from re import fullmatch
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProviderAttempt(EvidenceModel):
    call_id_sha256: Digest
    correlation_id_sha256: Digest
    observed_at: AwareDatetime
    result_code: int = Field(ge=0)


class CallCorrelation(EvidenceModel):
    request_id: UUID
    call_id_sha256: Digest
    observed_at: AwareDatetime


class CallbackDelivery(EvidenceModel):
    request_id: UUID
    call_id_sha256: Digest
    event_id_sha256: Digest
    delivery_id: UUID
    received_at: AwareDatetime
    observed_at: AwareDatetime


class PendingJoin(EvidenceModel):
    request_id: UUID
    observation_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}/[0-9a-f]{16}$")]
    observed_at: AwareDatetime


class ProviderEvidence(EvidenceModel):
    source: Literal["acs-provider"] = "acs-provider"
    table: Literal["ACSCallAutomationIncomingOperations"] = "ACSCallAutomationIncomingOperations"
    attempts: list[ProviderAttempt]


class ApplicationEvidence(EvidenceModel):
    source: Literal["application-observations"] = "application-observations"
    table: Literal["AppDependencies"] = "AppDependencies"
    correlations: list[CallCorrelation]
    deliveries: list[CallbackDelivery]
    pending_joins: list[PendingJoin]


class ExportScope(EvidenceModel):
    revision: NonBlank
    workspace: UUID
    acs_resource_id: NonBlank
    application_insights_resource_id: NonBlank
    window_start: AwareDatetime
    window_end: AwareDatetime

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        prefix = r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/\r\n]+/providers/"
        targets = (
            (self.acs_resource_id, r"(?i:Microsoft\.Communication/communicationServices)"),
            (self.application_insights_resource_id, r"(?i:Microsoft\.Insights/components)"),
        )
        if any(
            fullmatch(prefix + provider + r"/[^/\r\n]+", target) is None
            for target, provider in targets
        ):
            raise ValueError("Explicit ACS and Application Insights resource IDs are required.")
        if not self.window_start < self.window_end:
            raise ValueError("The export window must be increasing.")
        return self


class EvidenceSnapshot(ExportScope):
    source: Literal["log-analytics-snapshot"] = "log-analytics-snapshot"
    record: NonBlank
    queried_at: AwareDatetime
    provider_query_sha256: Digest
    application_query_sha256: Digest
    provider: ProviderEvidence
    application: ApplicationEvidence

    @model_validator(mode="after")
    def validate_correlations_and_window(self) -> Self:
        if not self.window_start < self.window_end <= self.queried_at:
            raise ValueError("Invalid evidence observation window.")
        correlations = self.application.correlations
        by_call: dict[str, UUID] = {}
        for item in correlations:
            previous = by_call.setdefault(item.call_id_sha256, item.request_id)
            if previous != item.request_id:
                raise ValueError("A provider call has conflicting request correlations.")
        provider_calls = {item.call_id_sha256 for item in self.provider.attempts}
        if provider_calls != set(by_call):
            raise ValueError("Provider rows and application call correlations must reconcile.")
        for delivery in self.application.deliveries:
            if by_call.get(delivery.call_id_sha256) != delivery.request_id:
                raise ValueError("A callback delivery lacks a matching call correlation.")
            if not self.window_start <= delivery.received_at <= delivery.observed_at:
                raise ValueError("A callback receipt is outside the observation window.")
        observed_times = (
            [attempt.observed_at for attempt in self.provider.attempts]
            + [correlation.observed_at for correlation in correlations]
            + [delivery.observed_at for delivery in self.application.deliveries]
            + [join.observed_at for join in self.application.pending_joins]
        )
        for observed_at in observed_times:
            if not self.window_start <= observed_at <= self.window_end:
                raise ValueError("An evidence row is outside the observation window.")
        return self


class EvidenceReview(EvidenceModel):
    source: Literal["operator-export-review"]
    record: NonBlank
    reviewer: NonBlank
    snapshot_sha256: Digest
    reviewed_at: AwareDatetime
    diagnostics_verified: Literal[True]
    sampling_disabled: Literal[True]
    ingestion_checked: Literal[True]
    late_arrival_risk_accepted: Literal[True]

    @field_validator(
        "diagnostics_verified",
        "sampling_disabled",
        "ingestion_checked",
        "late_arrival_risk_accepted",
        mode="before",
    )
    @classmethod
    def validate_review_flags(cls, value: object) -> bool:
        if value is not True:
            raise ValueError("Evidence review requires explicit JSON true flags.")
        return True


def read_reviewed_snapshot(
    snapshot_json: bytes,
    review_json: bytes,
    *,
    revision: str,
    workspace: UUID,
    acs_resource_id: str,
    application_insights_resource_id: str,
    reviewer: str,
    now: datetime,
) -> EvidenceSnapshot:
    """Validate an operator's bounded snapshot, not a global ingestion watermark."""
    snapshot = EvidenceSnapshot.model_validate_json(snapshot_json)
    review = EvidenceReview.model_validate_json(review_json)
    if (
        snapshot.revision != revision
        or snapshot.workspace != workspace
        or snapshot.acs_resource_id.casefold() != acs_resource_id.casefold()
        or snapshot.application_insights_resource_id.casefold()
        != application_insights_resource_id.casefold()
        or review.reviewer != reviewer
        or review.snapshot_sha256 != sha256(snapshot_json).hexdigest()
        or not snapshot.queried_at <= review.reviewed_at <= now
    ):
        raise ValueError("Export review is stale, mismatched, or unbound.")
    return snapshot
