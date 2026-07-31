from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


class ActivityCreateRequest(BaseModel):
    activity_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,127}$")
    internal_name: str = Field(min_length=2, max_length=200)
    activity_format: Literal["in_person", "online", "hybrid"]
    default_locale: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    starts_at: datetime
    ends_at: datetime
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    post_event_choice_opens_at: datetime | None = None
    post_event_choice_closes_at: datetime | None = None
    approval_policy: Literal["automatic", "manual", "rule_assisted"] = "automatic"
    payment_timing_policy: Literal["before_approval", "after_approval", "not_required"] = (
        "before_approval"
    )
    waitlist_enabled: bool = True
    post_event_choice_enabled: bool = False
    minimum_age: int | None = Field(default=None, ge=18, le=120)
    maximum_age: int | None = Field(default=None, ge=18, le=120)

    @model_validator(mode="after")
    def validate_windows(self) -> ActivityCreateRequest:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.registration_closes_at and self.registration_closes_at > self.starts_at:
            raise ValueError("registration must close before the activity starts")
        if (
            self.registration_opens_at
            and self.registration_closes_at
            and self.registration_opens_at >= self.registration_closes_at
        ):
            raise ValueError("registration opens_at must be before closes_at")
        if self.minimum_age and self.maximum_age and self.minimum_age > self.maximum_age:
            raise ValueError("minimum_age must not exceed maximum_age")
        if self.post_event_choice_opens_at and self.post_event_choice_opens_at < self.starts_at:
            raise ValueError("post-event choice cannot open before the activity starts")
        if (
            self.post_event_choice_opens_at
            and self.post_event_choice_closes_at
            and self.post_event_choice_opens_at >= self.post_event_choice_closes_at
        ):
            raise ValueError("post-event choice opens_at must be before closes_at")
        return self


class ActivityUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    internal_name: str | None = Field(default=None, min_length=2, max_length=200)
    visibility: Literal["public", "unlisted", "private"] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    post_event_choice_opens_at: datetime | None = None
    post_event_choice_closes_at: datetime | None = None
    approval_policy: Literal["automatic", "manual", "rule_assisted"] | None = None
    payment_timing_policy: Literal["before_approval", "after_approval", "not_required"] | None = (
        None
    )
    waitlist_enabled: bool | None = None
    post_event_choice_enabled: bool | None = None
    minimum_age: int | None = Field(default=None, ge=18, le=120)
    maximum_age: int | None = Field(default=None, ge=18, le=120)


class LocalizationUpsertRequest(BaseModel):
    locale: str = Field(min_length=2, max_length=16)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,199}$")
    title: str = Field(min_length=2, max_length=300)
    summary: str | None = Field(default=None, max_length=500)
    description_blocks: list[dict[str, Any]] = Field(default_factory=list)
    venue_display_name: str | None = Field(default=None, max_length=300)
    address_display_text: str | None = Field(default=None, max_length=500)
    participation_notes: list[dict[str, Any]] = Field(default_factory=list)
    cancellation_notice: str | None = Field(default=None, max_length=4000)
    translation_status: Literal["draft", "ready"] = "draft"


class TicketLinkRequest(BaseModel):
    ticket_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,127}$")
    internal_name: str = Field(min_length=2, max_length=200)
    catalog_product_id: UUID
    catalog_sku_id: UUID
    status: Literal["draft", "active"] = "draft"
    waitlist_enabled: bool = True
    max_quantity_per_user: int = Field(default=1, ge=1, le=10)
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    approval_policy_override: Literal["automatic", "manual", "rule_assisted"] | None = None
    payment_timing_override: Literal["before_approval", "after_approval", "not_required"] | None = (
        None
    )
    eligibility_rules: dict[str, Any] = Field(default_factory=dict)
    capacity_display_mode: Literal["hidden", "status_only", "exact"] = "status_only"
    sort_order: int = 0


class FormUpsertRequest(BaseModel):
    schema_version: int = Field(ge=1)
    form_schema: dict[str, Any]
    consent_requirements: list[dict[str, Any]] = Field(default_factory=list)


class LocationCreateRequest(BaseModel):
    location_type: Literal["in_person", "online"]
    venue_name: str | None = Field(default=None, max_length=300)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=128)
    city: str | None = Field(default=None, max_length=128)
    address_line_1: str | None = Field(default=None, max_length=500)
    address_line_2: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=32)
    online_provider: str | None = Field(default=None, max_length=64)
    online_join_url: str | None = Field(default=None, max_length=2000)
    public_address_precision: Literal["city_only", "district", "full"] = "city_only"


class SessionCreateRequest(BaseModel):
    session_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,127}$")
    title: str = Field(min_length=2, max_length=300)
    starts_at: datetime
    ends_at: datetime
    location_id: UUID | None = None
    checkin_opens_at: datetime | None = None
    checkin_closes_at: datetime | None = None
    sort_order: int = 0


class ActivityTransitionRequest(BaseModel):
    target_status: Literal[
        "draft",
        "in_review",
        "scheduled",
        "published",
        "registration_open",
        "registration_closed",
        "in_progress",
        "completed",
        "cancelled",
        "archived",
    ]
    reason: str = Field(min_length=2, max_length=2000)


class RegistrationCreateRequest(BaseModel):
    ticket_type_id: UUID
    locale: str = "zh-CN"
    currency_code: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    form_response: dict[str, Any] = Field(default_factory=dict)
    accepted_consents: list[str] = Field(default_factory=list)
    billing_email: EmailStr | None = None


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject", "request_information"]
    reason_code: str = Field(min_length=2, max_length=128)
    user_message: str | None = Field(default=None, max_length=500)
    private_notes: str | None = Field(default=None, max_length=4000)


class CheckinRequest(BaseModel):
    token: str | None = Field(default=None, min_length=20, max_length=1000)
    registration_number: str | None = Field(default=None, max_length=64)
    session_id: UUID | None = None
    action: Literal["check_in", "revoke"] = "check_in"
    reason: str | None = Field(default=None, max_length=1000)
    device_reference: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_credential(self) -> CheckinRequest:
        if not self.token and not self.registration_number:
            raise ValueError("token or registration_number is required")
        if self.action == "revoke" and not self.reason:
            raise ValueError("reason is required when revoking check-in")
        return self


class GroupingRequest(BaseModel):
    plan_name: str = Field(min_length=2, max_length=200)
    target_group_size: int = Field(ge=2, le=100)
    seed: str = Field(min_length=4, max_length=128)
    checked_in_only: bool = True
    publish: bool = False


class ParticipantProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    brief_introduction: str | None = Field(default=None, max_length=500)
    visibility_status: Literal["visible", "hidden"] = "visible"
    consent: bool


class PostEventChoiceRequest(BaseModel):
    chosen_user_id: UUID
    choice: Literal["interested", "pass"] = "interested"


class RestrictionRequest(BaseModel):
    target_user_id: UUID
    reason_code: str = Field(min_length=2, max_length=128)


class ReasonRequest(BaseModel):
    reason_code: str = Field(min_length=2, max_length=128)
    reason: str = Field(min_length=2, max_length=2000)


class ActivityCancelRequest(ReasonRequest):
    refund_policy_action: Literal["manual_review", "request_refunds"] = "manual_review"
    notify_participants: bool = True


class WaitlistReorderRequest(ReasonRequest):
    manual_order_override: int = Field(ge=1)


class GroupingStatusRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)


class GroupMemberMoveRequest(BaseModel):
    registration_id: UUID
    reason: str = Field(min_length=2, max_length=1000)
