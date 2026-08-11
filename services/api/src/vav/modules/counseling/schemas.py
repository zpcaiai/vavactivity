from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


class MentorCreateRequest(BaseModel):
    mentor_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,127}$")
    display_name: str = Field(min_length=2, max_length=200)
    timezone: str = Field(min_length=3, max_length=64)
    linked_user_id: UUID | None = None
    service_languages: list[str] = Field(default_factory=list)
    specialty_topics: list[str] = Field(default_factory=list)


class MentorLocalizationRequest(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,199}$")
    public_name: str = Field(min_length=2, max_length=200)
    headline: str | None = Field(default=None, max_length=500)
    biography_blocks: list[dict[str, Any]] = Field(default_factory=list)
    scope_statement: str = Field(min_length=20, max_length=4000)
    translation_status: Literal["draft", "ready"] = "draft"


class ServiceCreateRequest(BaseModel):
    service_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,127}$")
    internal_name: str = Field(min_length=2, max_length=200)
    delivery_mode: Literal["online", "in_person", "hybrid"]
    participant_mode: Literal["individual", "couple"] = "individual"
    duration_minutes: int = Field(gt=0, le=480)
    buffer_before_minutes: int = Field(default=0, ge=0, le=240)
    buffer_after_minutes: int = Field(default=0, ge=0, le=240)
    booking_mode: Literal["request_and_confirm", "direct_booking"] = "request_and_confirm"
    payment_policy: Literal["free", "pay_before_confirm", "pay_after_approval", "credit"]
    free_access: bool = False
    catalog_product_id: UUID | None = None
    catalog_sku_id: UUID | None = None
    min_notice_minutes: int = Field(default=1440, ge=0)
    max_advance_days: int = Field(default=90, gt=0, le=730)


class ServiceLocalizationRequest(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,199}$")
    name: str = Field(min_length=2, max_length=300)
    summary: str | None = Field(default=None, max_length=4000)
    description_blocks: list[dict[str, Any]] = Field(default_factory=list)
    scope_notice: str = Field(min_length=20, max_length=4000)
    translation_status: Literal["draft", "ready"] = "draft"


class AvailabilityRuleRequest(BaseModel):
    mentor_id: UUID
    service_id: UUID | None = None
    timezone: str
    weekday: int = Field(ge=0, le=6)
    local_start_time: time
    local_end_time: time
    valid_from: date
    valid_until: date | None = None
    daily_limit: int | None = Field(default=None, gt=0)
    weekly_limit: int | None = Field(default=None, gt=0)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be a valid IANA timezone") from error
        return value

    @model_validator(mode="after")
    def valid_window(self) -> "AvailabilityRuleRequest":
        if self.local_end_time <= self.local_start_time:
            raise ValueError("local_end_time must follow local_start_time")
        return self


class SlotHoldRequest(BaseModel):
    mentor_id: UUID
    service_id: UUID
    starts_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=128)


class AppointmentRequest(BaseModel):
    mentor_id: UUID | None = None
    service_id: UUID
    slot_hold_id: UUID | None = None
    user_timezone: str = Field(min_length=3, max_length=64)
    intake_schema_version: int = Field(default=1, gt=0)
    intake_response: dict[str, Any]
    idempotency_key: str = Field(min_length=8, max_length=128)


class TransitionRequest(BaseModel):
    target_status: str
    reason: str = Field(min_length=2, max_length=2000)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


class ProposalRequest(BaseModel):
    starts_at: datetime
    mentor_id: UUID
    expected_proposal_version: int = Field(ge=0)
    reason: str = Field(min_length=2, max_length=2000)


class RecordCreateRequest(BaseModel):
    record_type: Literal["client_summary", "mentor_note", "operations_note"]
    content: dict[str, Any]
    publish: bool = False


class FollowUpCreateRequest(BaseModel):
    follow_up_type: Literal["action_item", "course", "activity", "counseling", "external_support"]
    content: dict[str, Any]
    due_at: datetime | None = None


class FollowUpTransitionRequest(BaseModel):
    status: Literal["open", "completed", "cancelled"]
    reason: str = Field(min_length=2, max_length=2000)


class SafetyReferralRequest(BaseModel):
    risk_level: Literal["low", "moderate", "high", "immediate"]
    category: str = Field(min_length=2, max_length=64)
    details: dict[str, Any]
