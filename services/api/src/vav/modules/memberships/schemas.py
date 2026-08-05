from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AccessDecisionRequest(BaseModel):
    user_id: UUID
    capability_code: str = Field(min_length=3, max_length=128)
    resource_type: str | None = Field(default=None, max_length=64)
    resource_id: UUID | None = None
    requested_quantity: int = Field(default=1, ge=1, le=1_000_000)
    purpose: str = Field(min_length=3, max_length=128)
    request_context: dict[str, Any] = Field(default_factory=dict)


class QuotaReserveRequest(BaseModel):
    user_id: UUID
    benefit_code: str = Field(min_length=3, max_length=128)
    quantity: int = Field(default=1, ge=1, le=1_000_000)
    source_module: str = Field(min_length=2, max_length=64)
    source_reference_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=128)


class QuotaMutationRequest(BaseModel):
    reservation_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=128)


class ChangePreviewRequest(BaseModel):
    to_plan_code: str = Field(min_length=2, max_length=128)
    change_type: str = Field(
        pattern="^(upgrade|downgrade|billing_period_change|cancel|reactivate)$"
    )


class ChangeCreateRequest(ChangePreviewRequest):
    idempotency_key: str = Field(min_length=8, max_length=128)


class ChangeDecisionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class PlanCreateRequest(BaseModel):
    plan_code: str = Field(pattern="^[a-z0-9][a-z0-9._-]{1,127}$")
    internal_name: str = Field(min_length=2, max_length=200)
    plan_type: str = Field(pattern="^(free|paid|trial|internal_grant)$")
    default_locale: str = Field(default="en", min_length=2, max_length=16)
    display_order: int = 0
    featured: bool = False


class PlanUpdateRequest(BaseModel):
    internal_name: str | None = Field(default=None, min_length=2, max_length=200)
    display_order: int | None = None
    featured: bool | None = None


class PlanVersionCreateRequest(BaseModel):
    semantic_version: str = Field(min_length=1, max_length=64)
    localizations: list[dict[str, Any]] = Field(min_length=1)
    benefits: list[dict[str, Any]] = Field(default_factory=list)
    access_policy_snapshot: dict[str, Any] = Field(default_factory=dict)
    quota_policy_snapshot: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self) -> PlanVersionCreateRequest:
        if self.valid_until is not None and self.valid_from >= self.valid_until:
            raise ValueError("valid_until must be later than valid_from")
        return self


class ManualGrantRequest(BaseModel):
    user_id: UUID
    membership_plan_version_id: UUID
    grant_type: str = Field(
        pattern="^(customer_support|service_compensation|promotional|staff|migration)$"
    )
    reason_code: str = Field(min_length=3, max_length=128)
    reason: str | None = Field(default=None, max_length=2000)
    starts_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> ManualGrantRequest:
        if self.starts_at >= self.expires_at:
            raise ValueError("expires_at must be later than starts_at")
        return self


class QuotaAdjustmentRequest(BaseModel):
    quantity: int
    adjustment_type: str = Field(pattern="^(credit|debit|compensation|correction)$")
    reason_code: str = Field(min_length=3, max_length=128)
    reason: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_quantity(self) -> QuotaAdjustmentRequest:
        if self.quantity == 0:
            raise ValueError("quantity must not be zero")
        return self


class ReconciliationResolveRequest(BaseModel):
    resolution_summary: str = Field(min_length=3, max_length=1000)


class BenefitCreateRequest(BaseModel):
    benefit_code: str = Field(min_length=3, max_length=128)
    semantic_version: str = Field(min_length=1, max_length=64)
    benefit_type: str = Field(
        pattern="^(capability|resource_scope|quota|limit_override|price_benefit|priority_access)$"
    )
    value_schema: dict[str, Any]
    owning_module: str = Field(min_length=2, max_length=64)
    sensitivity: str = Field(default="internal", pattern="^(public|internal|sensitive)$")


class SkuMappingRequest(BaseModel):
    catalog_sku_id: UUID
    membership_plan_id: UUID
    membership_plan_version_id: UUID
    billing_period: str = Field(pattern="^(monthly|yearly|custom|none)$")
    trial_policy: dict[str, Any] | None = None
    grace_period_policy: dict[str, Any] | None = None
    valid_from: datetime
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self) -> SkuMappingRequest:
        if self.valid_until is not None and self.valid_from >= self.valid_until:
            raise ValueError("valid_until must be later than valid_from")
        return self


class ProjectionEventRequest(BaseModel):
    source_module: str = Field(min_length=2, max_length=64)
    source_event_id: UUID
    event_type: str = Field(min_length=3, max_length=128)
    event_version: int = Field(default=1, ge=1)
    payload: dict[str, Any]


class TrialPolicyRequest(BaseModel):
    policy_code: str = Field(pattern="^[a-z0-9][a-z0-9._-]{1,127}$")
    semantic_version: str = Field(min_length=1, max_length=64)
    membership_plan_version_id: UUID
    duration_days: int = Field(ge=1, le=365)
    eligibility_policy: dict[str, Any]
    requires_payment_method: bool = False
    auto_converts: bool = False
