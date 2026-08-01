from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class PrivacyMode(StrEnum):
    STRICT = "strict"
    BALANCED = "balanced"
    CUSTOM = "custom"


class FieldVisibility(StrEnum):
    PRIVATE = "private"
    PLATFORM_OPERATIONS = "platform_operations"
    ASSIGNED_MENTOR = "assigned_mentor"
    ACTIVITY_PARTICIPANTS = "activity_participants"
    MUTUAL_MATCHES = "mutual_matches"
    VERIFIED_MEMBERS = "verified_members"
    PUBLIC = "public"


class DataSensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    HIGHLY_RESTRICTED = "highly_restricted"


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    legal_name: str | None = Field(default=None, max_length=200)
    date_of_birth: date | None = None
    gender_code: str | None = Field(default=None, max_length=64)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=128)
    city: str | None = Field(default=None, max_length=128)
    preferred_locale: Literal["zh-CN", "zh-TW", "en"] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    public_bio: str | None = Field(default=None, max_length=500)
    version: int = Field(ge=1)


class ContactPointCreateRequest(BaseModel):
    contact_type: Literal["email", "phone", "wechat", "whatsapp", "telegram", "other"]
    value: str = Field(min_length=3, max_length=320)


class ContactPointUpdateRequest(BaseModel):
    is_primary: bool | None = None
    visibility: FieldVisibility | None = None
    version_reason: str = Field(min_length=8, max_length=500)


class FieldVisibilityRuleRequest(BaseModel):
    data_domain: str = Field(min_length=2, max_length=64)
    field_code: str = Field(min_length=2, max_length=128)
    visibility: FieldVisibility
    allowed_purposes: list[str] = Field(default_factory=list, max_length=20)
    allowed_recipient_types: list[str] = Field(default_factory=list, max_length=20)
    valid_until: datetime | None = None


class PrivacySettingsUpdateRequest(BaseModel):
    privacy_mode: PrivacyMode
    searchable_by_platform_users: bool
    visible_in_activity_directory: bool
    visible_in_matchmaking: bool
    allow_contact_exchange_after_mutual_confirmation: bool
    allow_profile_use_by_ai: bool
    allow_service_history_use_by_ai: bool
    settings_version: int = Field(ge=1)
    field_rules: list[FieldVisibilityRuleRequest] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def strict_is_restrictive(self) -> PrivacySettingsUpdateRequest:
        if self.privacy_mode == PrivacyMode.STRICT and any(
            (
                self.searchable_by_platform_users,
                self.visible_in_activity_directory,
                self.visible_in_matchmaking,
                self.allow_contact_exchange_after_mutual_confirmation,
                self.allow_profile_use_by_ai,
                self.allow_service_history_use_by_ai,
            )
        ):
            raise ValueError("strict privacy mode cannot enable broad visibility")
        return self


class ConsentActionRequest(BaseModel):
    release_id: UUID
    evidence: dict[str, Any] = Field(default_factory=dict)


class ReauthenticatedRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class ExportRequest(ReauthenticatedRequest):
    requested_format: Literal["json", "csv", "html"] = "json"
    modules: list[str] = Field(default_factory=list, max_length=20)


class CorrectionItemRequest(BaseModel):
    module_code: str = Field(min_length=2, max_length=64)
    entity_reference_type: str = Field(min_length=2, max_length=64)
    entity_reference_id: UUID | None = None
    field_path: str = Field(min_length=2, max_length=500)
    requested_value: Any
    reason: str = Field(min_length=8, max_length=2000)


class CorrectionRequest(BaseModel):
    items: list[CorrectionItemRequest] = Field(min_length=1, max_length=20)


class ErasureRequest(ReauthenticatedRequest):
    requested_scope: list[str] = Field(default_factory=lambda: ["all"], max_length=20)
    confirmation: Literal["REQUEST_ACCOUNT_ERASURE"]


class ErasureConfirmationRequest(ReauthenticatedRequest):
    confirmation: Literal["CONFIRM_ACCOUNT_ERASURE"]


class StatusReasonRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class AiMemoryPreferencesRequest(BaseModel):
    long_term_memory_enabled: bool
    allow_profile_facts: bool = False
    allow_service_history: bool = False
    allow_relationship_context: bool = False
    allow_cross_conversation_use: bool = False
    delete_existing_when_disabled: bool = False
    settings_version: int = Field(ge=1)


class AiMemoryCandidateRequest(BaseModel):
    memory_type: Literal[
        "user_preference",
        "stated_goal",
        "relationship_context",
        "service_preference",
        "communication_preference",
        "user_confirmed_fact",
        "model_inference",
    ]
    content: str = Field(min_length=1, max_length=2000)
    source_type: str = Field(min_length=2, max_length=64)
    source_reference_id: UUID | None = None
    certainty: Literal["user_confirmed", "user_stated", "inferred_low", "inferred_medium"]
    allowed_purposes: list[str] = Field(min_length=1, max_length=10)
    allowed_agent_profiles: list[str] = Field(min_length=1, max_length=10)


class AiMemoryUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class AdminDecisionRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)
    user_visible_message: str = Field(min_length=3, max_length=1000)


class LegalHoldRequest(BaseModel):
    hold_type: Literal[
        "legal", "security_investigation", "fraud_investigation", "safety_case", "payment_dispute"
    ]
    subject_user_id: UUID
    module_codes: list[str] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=12, max_length=2000)
    authorized_by: UUID
    ends_at: datetime


class BreakGlassRequest(BaseModel):
    subject_user_id: UUID
    data_scope: list[str] = Field(min_length=1, max_length=20)
    purpose: Literal[
        "security_incident",
        "approved_safety_referral",
        "account_takeover_investigation",
        "payment_fraud_investigation",
    ]
    reason: str = Field(min_length=12, max_length=2000)
