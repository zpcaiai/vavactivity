from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class HandoffCreate(BaseModel):
    handoff_code: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    source_entity_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    source_entity_id: UUID
    user_intent: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    context: dict[str, UUID | str] = Field(default_factory=dict)
    source_route_code: str = Field(pattern=r"^[a-z][a-z0-9.-]{2,127}$")

    @field_validator("context")
    @classmethod
    def context_values_are_identifiers(cls, value: dict[str, UUID | str]) -> dict[str, UUID | str]:
        for item in value.values():
            if isinstance(item, str) and (len(item) > 128 or "@" in item or "+" in item):
                raise ValueError("handoff context accepts identifiers only")
        return value


class JourneyStart(BaseModel):
    journey_code: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    source_module: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    source_entity_type: str | None = Field(default=None, max_length=64)
    source_entity_id: UUID | None = None
    authoritative_state_version: str = Field(min_length=1, max_length=128)


class JourneyReconcile(BaseModel):
    current_step_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,127}$")
    state: Literal[
        "active", "blocked", "waiting", "completed", "cancelled", "expired", "invalidated"
    ]
    block_reason_code: str | None = Field(default=None, max_length=128)
    authoritative_state_version: str = Field(min_length=1, max_length=128)


class SupportRequestCreate(BaseModel):
    source_route_code: str = Field(pattern=r"^[a-z][a-z0-9.-]{2,127}$")
    source_entity_type: str | None = Field(default=None, max_length=64)
    source_entity_id: UUID | None = None
    category: Literal[
        "general", "safety", "privacy", "payment_dispute", "broken_link", "unclear_status"
    ]
    description: str = Field(min_length=10, max_length=5000)


class FeedbackCreate(BaseModel):
    route_code: str = Field(pattern=r"^[a-z][a-z0-9.-]{2,127}$")
    feedback_type: Literal[
        "cannot_find_next_step",
        "unclear_explanation",
        "broken_page",
        "incorrect_status",
        "broken_link",
        "unhelpful_help",
    ]
    context: dict[str, str | int | bool] = Field(default_factory=dict)


class DeepLinkCreate(BaseModel):
    purpose: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    user_id: UUID
    entity_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    entity_id: UUID
    target_route_code: str = Field(pattern=r"^[a-z][a-z0-9.-]{2,127}$")
    fallback_route_code: str = Field(pattern=r"^[a-z][a-z0-9.-]{2,127}$")
    route_parameters: dict[str, UUID | str] = Field(default_factory=dict)
    permission_codes: list[str] = Field(default_factory=list)
    ttl_seconds: int = Field(default=900, ge=60, le=86400)
    single_use: bool = True


class SearchReindex(BaseModel):
    scope: Literal["public", "personal", "admin", "all"] = "all"
    source_module: str | None = Field(default=None, max_length=64)


class DeadEndResolution(BaseModel):
    resolution: Literal["resolved", "false_positive"]
    reason: str = Field(min_length=10, max_length=5000)


class ClosureEvaluation(BaseModel):
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    environment: Literal["test", "ci", "staging", "production"]
    capability_codes: list[str] = Field(min_length=1)
    evidence_reference: str = Field(min_length=3, max_length=2000)


class ClosureCertification(BaseModel):
    decision: Literal["certify", "reject"]
    reason: str = Field(min_length=10, max_length=5000)
    evidence_manifest: dict[str, Any]
