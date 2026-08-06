from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    event_id: UUID
    event_type: str = Field(min_length=3, max_length=255)
    event_version: int = Field(ge=1)
    aggregate_type: str = Field(min_length=1, max_length=128)
    aggregate_id: UUID
    aggregate_version: int = Field(ge=1)
    sequence_number: int = Field(ge=1)
    producer_module: str = Field(min_length=2, max_length=64)
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    subject_user_id: UUID | None = None
    payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class InboxApply(BaseModel):
    consumer_code: str = Field(min_length=3, max_length=128)
    envelope: EventEnvelope
    effect_receipt: dict[str, Any] = Field(default_factory=dict)


class ExternalIdentifierCreate(BaseModel):
    entity_type: str = Field(min_length=2, max_length=128)
    canonical_entity_id: UUID
    provider_code: str = Field(min_length=2, max_length=128)
    external_identifier: str = Field(min_length=1, max_length=500)


class QualityEvaluationCreate(BaseModel):
    rule_code: str = Field(min_length=3, max_length=255)
    evaluated_records: int = Field(ge=0)
    failed_records: int = Field(ge=0)
    sample: dict[str, Any] = Field(default_factory=dict)


class ReconciliationRun(BaseModel):
    reconciliation_code: str = Field(min_length=3, max_length=255)
    comparisons: list[dict[str, Any]] = Field(max_length=10000)


class BackfillStart(BaseModel):
    backfill_code: str = Field(min_length=3, max_length=255)
    environment: Literal["local", "ci", "staging", "production"]
    dry_run: bool = True
    idempotency_key: str = Field(min_length=8, max_length=255)
    stable_candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class BackfillAction(BaseModel):
    action: Literal["approve", "start", "pause", "resume", "complete", "fail", "cancel"]
    cursor_value: str | None = Field(default=None, max_length=500)
    processed_delta: int = Field(default=0, ge=0)
    success_delta: int = Field(default=0, ge=0)
    failure_delta: int = Field(default=0, ge=0)


class ProjectionRebuild(BaseModel):
    asset_code: str = Field(min_length=3, max_length=255)
    scope: Literal["entity", "partition", "full"]
    scope_key: str | None = Field(default=None, max_length=255)
    source_checkpoint: dict[str, Any]
    shadow_build: bool = False


class RepairRequest(BaseModel):
    repair_code: str = Field(min_length=3, max_length=255)
    reconciliation_difference_id: UUID | None = None
    idempotency_key: str = Field(min_length=8, max_length=255)
    input_mapping: dict[str, Any]


class ErasurePlanCreate(BaseModel):
    privacy_request_id: UUID
    subject_user_id: UUID
    lineage_release_version: str = Field(min_length=1, max_length=64)


class ErasureTaskComplete(BaseModel):
    status: Literal["completed", "failed", "retained_legal_hold"]
    execution_receipt: dict[str, Any]
    residual_count: int | None = Field(default=None, ge=0)
    legal_hold_reference: str | None = Field(default=None, max_length=255)


class IntegrityEvaluate(BaseModel):
    business_domain: str = Field(min_length=2, max_length=64)
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    environment: Literal["local", "ci", "staging", "production"]
    evidence_results: dict[str, Literal["pass", "fail", "not_run"]]
    evidence_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IntegrityDecision(BaseModel):
    decision: Literal["certified", "rejected"]
    reason: str = Field(min_length=10, max_length=1000)
