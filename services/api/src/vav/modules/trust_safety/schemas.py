from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from vav.modules.trust_safety.domain import (
    AccountRestrictionType,
    ModerationTargetType,
    SafetyReportCategory,
)


class ReportCreateRequest(BaseModel):
    target_type: str = Field(min_length=2, max_length=64)
    target_reference_id: UUID | None = None
    reported_user_id: UUID | None = None
    category: SafetyReportCategory
    severity_claim: str | None = Field(default=None, pattern="^(low|moderate|high|critical)$")
    description: str | None = Field(default=None, max_length=5000)
    block_user: bool = False
    immediate_danger: bool = False
    idempotency_key: str = Field(min_length=8, max_length=128)
    source_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_block_target(self) -> ReportCreateRequest:
        if self.block_user and self.reported_user_id is None:
            raise ValueError("reported_user_id is required when block_user is true")
        return self


class BlockCreateRequest(BaseModel):
    reason_code: str | None = Field(default=None, max_length=128)
    private_reason: str | None = Field(default=None, max_length=2000)


class DecisionRequest(BaseModel):
    subject_user_id: UUID
    counterpart_user_id: UUID | None = None
    target_type: str | None = Field(default=None, max_length=64)
    target_reference_id: UUID | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ModerationCreateRequest(BaseModel):
    target_type: ModerationTargetType
    target_reference_id: UUID
    target_version: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=20000)
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent|critical)$")


class ModerationDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject|limit|remove|escalate)$")
    category_codes: list[str] = Field(default_factory=list)
    reason_code: str | None = Field(default=None, max_length=128)
    user_message: str | None = Field(default=None, max_length=1000)
    internal_note: str | None = Field(default=None, max_length=5000)


class RestrictionCreateRequest(BaseModel):
    user_id: UUID
    restriction_type: AccountRestrictionType
    scope_definition: dict[str, Any] = Field(default_factory=dict)
    source_type: str = Field(pattern="^(case|rule|moderation|manual)$")
    source_reference_id: UUID | None = None
    reason_code: str = Field(min_length=3, max_length=128)
    user_message: str | None = Field(default=None, max_length=1000)
    internal_reason: str | None = Field(default=None, max_length=5000)
    starts_at: datetime
    ends_at: datetime | None = None
    appeal_allowed: bool = True

    @model_validator(mode="after")
    def validate_window(self) -> RestrictionCreateRequest:
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self


class AppealCreateRequest(BaseModel):
    restriction_id: UUID | None = None
    decision_id: UUID | None = None
    reason: str = Field(min_length=10, max_length=5000)
    evidence_manifest: list[dict[str, Any]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_target(self) -> AppealCreateRequest:
        if self.restriction_id is None and self.decision_id is None:
            raise ValueError("restriction_id or decision_id is required")
        return self


class AppealDecisionRequest(BaseModel):
    outcome: str = Field(pattern="^(upheld|modified|overturned|ineligible)$")
    outcome_message: str = Field(min_length=3, max_length=1000)
    internal_review: str = Field(min_length=3, max_length=5000)
    modified_scope_definition: dict[str, Any] | None = None
    modified_ends_at: datetime | None = None

    @model_validator(mode="after")
    def validate_modification(self) -> AppealDecisionRequest:
        has_modification = (
            self.modified_scope_definition is not None or self.modified_ends_at is not None
        )
        if self.outcome == "modified" and not has_modification:
            raise ValueError("a modified appeal requires a restriction modification")
        if self.outcome != "modified" and has_modification:
            raise ValueError("restriction modifications require the modified outcome")
        if self.modified_ends_at is not None and self.modified_ends_at <= datetime.now(
            self.modified_ends_at.tzinfo
        ):
            raise ValueError("modified_ends_at must be in the future")
        return self


class RuleCreateRequest(BaseModel):
    rule_code: str = Field(pattern="^[a-z0-9][a-z0-9._-]{2,127}$")
    semantic_version: str = Field(min_length=1, max_length=64)
    category: str = Field(min_length=2, max_length=64)
    rule_type: str = Field(
        pattern="^(deterministic|rate|sequence|content_classifier|aggregate|manual_flag)$"
    )
    condition_definition: dict[str, Any]
    action_definition: dict[str, Any]
    severity: str = Field(pattern="^(low|moderate|high|critical)$")
    score_delta: int = Field(default=0, ge=-10000, le=10000)
    applicable_modules: list[str] = Field(min_length=1)
    rollout_basis_points: int = Field(default=10000, ge=0, le=10000)


class AdminReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=5000)
    expected_version: int | None = Field(default=None, ge=1)


class CaseTransitionRequest(BaseModel):
    target_status: str = Field(
        pattern="^(triaged|assigned|investigating|pending_action|resolved|closed|reopened)$"
    )


class CaseAssignmentRequest(BaseModel):
    assigned_to: UUID
    assigned_team: str = Field(min_length=2, max_length=128)
    expected_version: int = Field(ge=1)


class UserEvidenceUploadRequest(BaseModel):
    evidence_type: str = Field(pattern="^(text|image_metadata|document_metadata|link)$")
    content: str = Field(min_length=1, max_length=20_000)
    filename: str | None = Field(default=None, max_length=255)
    media_type: str | None = Field(default=None, max_length=128)
    collection_reason: str = Field(default="reporter_submission", max_length=128)


class EvidenceAccessRequest(BaseModel):
    purpose_code: str = Field(min_length=3, max_length=128)
    access_type: str = Field(default="view", pattern="^(view|download|verify)$")


class CaseDecisionRequest(BaseModel):
    decision_type: str = Field(min_length=3, max_length=64)
    decision_scope: dict[str, Any] = Field(default_factory=dict)
    reason_codes: list[str] = Field(min_length=1, max_length=20)
    evidence_item_ids: list[UUID] = Field(default_factory=list, max_length=100)
    user_message: str | None = Field(default=None, max_length=1000)
    internal_rationale: str = Field(min_length=3, max_length=5000)
    restriction_manifest: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    appeal_allowed: bool = True


class BehaviorAggregateRequest(BaseModel):
    user_id: UUID
    metric_code: str = Field(
        pattern="^(like_rate|invitation_rate|repeated_contact|post_decline_contact|post_ending_contact|block_evasion|bulk_contact)$"
    )
    window_type: str = Field(pattern="^(minute|hour|day|rolling_24h)$")
    window_starts_at: datetime
    window_ends_at: datetime
    event_count: int = Field(ge=0)
    distinct_target_count: int = Field(default=0, ge=0)
    aggregation_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_window(self) -> BehaviorAggregateRequest:
        if self.window_ends_at <= self.window_starts_at:
            raise ValueError("window_ends_at must be later than window_starts_at")
        return self


class FraudSignalRequest(BaseModel):
    subject_user_id: UUID
    signal_code: str = Field(
        pattern="^(money_request|gift_card|crypto_investment|emergency_loan|external_payment|staff_impersonation|mentor_impersonation|duplicate_narrative|duplicate_photo_hash|bulk_contact|contact_change|account_takeover|payment_dispute)$"
    )
    signal_source: str = Field(pattern="^(moderation|interaction|identity|commerce|manual_review)$")
    severity: str = Field(pattern="^(low|moderate|high|critical)$")
    confidence_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    source_reference_type: str | None = Field(default=None, max_length=64)
    source_reference_id: UUID | None = None
    safe_signal_context: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


class RedTeamRunCreateRequest(BaseModel):
    policy_version: str = Field(min_length=1, max_length=64)
    fixture_manifest: dict[str, Any]


class RedTeamRunCompleteRequest(BaseModel):
    result_manifest: dict[str, Any]
    block_bypass_count: int = Field(ge=0)
    contact_leakage_count: int = Field(ge=0)
