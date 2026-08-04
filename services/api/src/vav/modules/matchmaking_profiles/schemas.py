"""Request models for the matchmaking-profile API."""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProfileCreateRequest(BaseModel):
    locale: str | None = Field(default=None, max_length=16)


class ProfileFieldUpdateRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    expected_version: int | None = None


class NarrativeUpdateRequest(BaseModel):
    locale: str = Field(min_length=2, max_length=16)
    self_introduction: str | None = None
    faith_journey: str | None = None
    relationship_values: str | None = None
    marriage_vision: str | None = None
    family_vision: str | None = None
    strengths_and_growth: str | None = None
    interests_and_lifestyle: str | None = None
    hoped_for_relationship: str | None = None
    ai_assisted: bool = False
    ai_content_confirmed: bool = False


class PhotoUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=300)
    mime_type: str = Field(min_length=3, max_length=128)
    content_base64: str = Field(min_length=1)
    photo_role: str = Field(default="gallery")


class PreferenceCriterionRequest(BaseModel):
    criterion_code: str = Field(min_length=1, max_length=128)
    operator: str = Field(min_length=1, max_length=32)
    desired_value: Any
    importance: str = Field(min_length=1, max_length=32)
    hard_constraint: bool = False
    allow_unknown: bool = True
    allow_system_relaxation: bool = False
    relaxation_acknowledged: bool = False
    user_explanation: str | None = Field(default=None, max_length=500)


class PreferenceUpdateRequest(BaseModel):
    criteria: list[PreferenceCriterionRequest] = Field(default_factory=list)
    allow_recommendation_relaxation: bool = False


class FieldVisibilityRequest(BaseModel):
    field_code: str = Field(min_length=1, max_length=128)
    visibility: str = Field(min_length=1, max_length=64)


class PrivacyUpdateRequest(BaseModel):
    rules: list[FieldVisibilityRequest] = Field(default_factory=list)
    visible_in_matchmaking: bool | None = None


class SubmitRequest(BaseModel):
    change_summary: str = Field(default="", max_length=1000)


class ReviewAssignRequest(BaseModel):
    assignee_id: UUID
    expected_version: int | None = None


class ReviewStartRequest(BaseModel):
    expected_version: int | None = None


class ReviewItemRequest(BaseModel):
    item_type: str = Field(pattern="^(field|photo)$")
    field_code: str | None = Field(default=None, max_length=128)
    photo_id: UUID | None = None
    decision: str = Field(min_length=1, max_length=32)
    reason_code: str | None = Field(default=None, max_length=128)
    user_message_safe: str | None = Field(default=None, max_length=2000)
    internal_note: str | None = Field(default=None, max_length=4000)


class ReviewApproveRequest(BaseModel):
    user_message: str | None = Field(default=None, max_length=2000)
    internal_summary: str | None = Field(default=None, max_length=4000)
    expected_version: int | None = None


class ReviewChangesRequest(BaseModel):
    user_message: str = Field(min_length=1, max_length=2000)
    internal_summary: str | None = Field(default=None, max_length=4000)
    expected_version: int | None = None


class ReviewRejectRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    user_message: str = Field(min_length=1, max_length=2000)
    internal_summary: str | None = Field(default=None, max_length=4000)
    expected_version: int | None = None


class ReviewEscalateRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    expected_version: int | None = None


class SuspendRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)


class RestoreRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
