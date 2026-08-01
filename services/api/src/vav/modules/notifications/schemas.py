from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationCategory(StrEnum):
    SECURITY = "security"
    ACCOUNT = "account"
    ORDER = "order"
    PAYMENT = "payment"
    SUBSCRIPTION = "subscription"
    ACTIVITY = "activity"
    COURSE = "course"
    COUNSELING = "counseling"
    AI_ASSISTANT = "ai_assistant"
    MATCHMAKING = "matchmaking"
    MODERATION = "moderation"
    PLATFORM = "platform"
    MARKETING = "marketing"


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationFrequency(StrEnum):
    IMMEDIATE = "immediate"
    DAILY_DIGEST = "daily_digest"
    WEEKLY_DIGEST = "weekly_digest"
    DISABLED = "disabled"


class PreferencePolicy(StrEnum):
    MANDATORY_SECURITY = "mandatory_security"
    TRANSACTIONAL_REQUIRED = "transactional_required"
    SERVICE_REQUIRED = "service_required"
    SERVICE_OPTIONAL = "service_optional"
    MARKETING_OPT_IN = "marketing_opt_in"


class DeliveryFailureClass(StrEnum):
    RATE_LIMIT = "rate_limit"
    PROVIDER_TEMPORARY = "provider_temporary"
    NETWORK = "network"
    INVALID_DESTINATION = "invalid_destination"
    PERMANENT_BOUNCE = "permanent_bounce"
    TEMPLATE_ERROR = "template_error"
    AUTHENTICATION_ERROR = "authentication_error"
    POLICY_SUPPRESSION = "policy_suppression"
    UNKNOWN = "unknown"


class IngestNotificationEventRequest(BaseModel):
    source_event_id: UUID
    source_module: str = Field(min_length=2, max_length=64)
    event_type: str = Field(min_length=3, max_length=128)
    event_version: int = Field(ge=1, le=100)
    subject_type: str | None = Field(default=None, max_length=64)
    subject_id: UUID | None = None
    payload: dict[str, Any]
    occurred_at: datetime


class NotificationPreferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: NotificationCategory
    channel: Literal["in_app", "email"]
    enabled: bool
    frequency: NotificationFrequency = NotificationFrequency.IMMEDIATE
    quiet_hours_enabled: bool = False
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    quiet_hours_timezone: str | None = Field(default=None, max_length=64)

    @field_validator("quiet_hours_timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is not None and ("/" not in value or len(value) > 64):
            raise ValueError("quiet_hours_timezone must be an IANA timezone")
        return value


class UpdateNotificationPreferencesRequest(BaseModel):
    items: list[NotificationPreferenceItem] = Field(min_length=1, max_length=40)


class ConsentRequest(BaseModel):
    consent_version: str = Field(min_length=1, max_length=32)
    evidence: dict[str, Any] = Field(default_factory=dict)


class TemplateDefinitionRequest(BaseModel):
    template_code: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    internal_name: str = Field(min_length=3, max_length=200)
    category: NotificationCategory
    purpose: Literal["security", "transactional", "service", "marketing"]
    variable_schema: dict[str, Any]
    required_channels: list[Literal["in_app", "email"]] = Field(default_factory=list)
    supported_channels: list[Literal["in_app", "email"]]


class TemplateReleaseRequest(BaseModel):
    semantic_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    locale: Literal["zh-CN", "zh-TW", "en"]
    channel: Literal["in_app", "email"]
    subject_template: str | None = Field(default=None, max_length=300)
    title_template: str | None = Field(default=None, max_length=300)
    body_html_template: str | None = Field(default=None, max_length=50_000)
    body_text_template: str = Field(min_length=1, max_length=50_000)
    action_label_template: str | None = Field(default=None, max_length=100)
    action_url_template: str | None = Field(default=None, max_length=1000)


class TemplatePreviewRequest(BaseModel):
    variables: dict[str, Any]


class StatusReasonRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=1000)


class SuppressionRequest(BaseModel):
    destination: str = Field(min_length=3, max_length=320)
    channel: Literal["email"] = "email"
    reason: Literal[
        "hard_bounce",
        "repeated_soft_bounce",
        "spam_complaint",
        "user_unsubscribed",
        "admin_blocked",
        "invalid_address",
        "security_hold",
    ]
    explanation: str = Field(min_length=8, max_length=1000)


class ReminderRequest(BaseModel):
    reminder_type: str = Field(min_length=3, max_length=128)
    subject_type: str = Field(min_length=2, max_length=64)
    subject_id: UUID
    recipient_user_id: UUID
    template_code: str = Field(min_length=3, max_length=128)
    category: NotificationCategory
    trigger_at: datetime
    timezone: str = Field(min_length=3, max_length=64)
    trigger_reference_version: int = Field(ge=1)
    deduplication_key: str = Field(min_length=8, max_length=255)


class CampaignRequest(BaseModel):
    campaign_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{4,127}$")
    internal_name: str = Field(min_length=3, max_length=300)
    campaign_type: Literal[
        "service_announcement",
        "product_update",
        "activity_promotion",
        "course_promotion",
        "educational_newsletter",
        "operational_notice",
    ]
    category: NotificationCategory
    template_code: str = Field(min_length=3, max_length=128)
    audience_definition: dict[str, Any]
    channel_policy: dict[str, Any]
    scheduled_at: datetime | None = None
    rate_limit_per_minute: int = Field(default=500, ge=1, le=10_000)
    batch_size: int = Field(default=100, ge=1, le=1000)


class CampaignActionRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=1000)
    confirmation_code: str | None = Field(default=None, max_length=128)


class ProviderWebhookEnvelope(BaseModel):
    event_id: str = Field(min_length=3, max_length=255)
    event_type: Literal["delivered", "deferred", "hard_bounce", "soft_bounce", "complaint"]
    provider_message_id: str | None = Field(default=None, max_length=255)
    destination: str | None = Field(default=None, max_length=320)
