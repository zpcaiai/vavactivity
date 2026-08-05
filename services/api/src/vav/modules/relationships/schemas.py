"""Relationship API request bodies."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class StageProposalRequest(BaseModel):
    to_stage_code: str = Field(max_length=64)
    message: str | None = Field(default=None, max_length=2000)


class ProposalDecisionRequest(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    reason_code: str | None = Field(default=None, max_length=128)


class PauseRequest(BaseModel):
    private_reason: str | None = Field(default=None, max_length=4000)
    visible_message: str | None = Field(default=None, max_length=2000)


class ResumeRequest(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)


class EndingRequest(BaseModel):
    confirmed: bool
    reason_code: str | None = Field(default=None, max_length=128)
    private_reason: str | None = Field(default=None, max_length=4000)
    visible_message: str | None = Field(default=None, max_length=2000)


class MilestoneRequest(BaseModel):
    milestone_type: str = Field(default="personal", max_length=64)
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    visibility: Literal["private", "shared"] = "shared"
    occurred_on: date | None = None


class MilestoneUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    visibility: Literal["private", "shared"] | None = None
    occurred_on: date | None = None
    expected_version: int | None = Field(default=None, ge=1)


class CheckinRequest(BaseModel):
    visibility: Literal["private", "shared"] = "private"
    responses: dict[str, Any] = Field(default_factory=dict)


class ReflectionRequest(BaseModel):
    reflection: str = Field(min_length=1, max_length=10_000)
    ai_processing_consent_id: str | None = Field(default=None, max_length=64)


class ActionItemRequest(BaseModel):
    assigned_to_user_id: UUID
    title: str = Field(min_length=1, max_length=200)
    details: str | None = Field(default=None, max_length=4000)


class ReminderPlanRequest(BaseModel):
    reminder_type: str = Field(max_length=64)
    cadence_days: int = Field(default=30, ge=1, le=365)
    opted_in: bool


class AdminSafetyRequest(BaseModel):
    reason_code: str = Field(min_length=3, max_length=128)
    purpose: str = Field(min_length=4, max_length=128)


class AdminSensitiveReadRequest(BaseModel):
    purpose: str = Field(min_length=4, max_length=128)
