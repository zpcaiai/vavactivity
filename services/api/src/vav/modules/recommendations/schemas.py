"""Request models for the recommendation API."""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class BatchRequest(BaseModel):
    batch_type: str = Field(default="daily", pattern="^(daily|supplemental)$")
    requested_size: int | None = Field(default=None, ge=1, le=50)


class ExposureRequest(BaseModel):
    exposure_type: str = Field(
        pattern="^(card_impression|card_visible|profile_opened|photo_viewed)$"
    )
    duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    source: str = Field(default="user_web", max_length=32)


class FeedbackRequest(BaseModel):
    recommended_user_id: UUID
    feedback_type: str = Field(min_length=1, max_length=64)
    reason_code: str | None = Field(default=None, max_length=128)
    reason_details: str | None = Field(default=None, max_length=2000)
    recommendation_item_id: UUID | None = None
    idempotency_key: str = Field(min_length=8, max_length=128)


class TuningRequest(BaseModel):
    exploration_level: str | None = Field(default=None, max_length=32)
    feedback_personalization_enabled: bool | None = None
    daily_received_limit: int | None = Field(default=None, ge=1, le=100)
    allow_relaxed_recommendations: bool | None = None
    recommendations_paused: bool | None = None


class StrategyCreateRequest(BaseModel):
    strategy_code: str = Field(min_length=1, max_length=128)
    semantic_version: str = Field(min_length=1, max_length=64)
    hard_constraint_policy: dict[str, Any]
    feature_manifest: list[dict[str, Any]]
    scoring_policy: dict[str, Any]
    bidirectional_policy: dict[str, Any]
    ranking_policy: dict[str, Any]
    diversification_policy: dict[str, Any]
    exposure_policy: dict[str, Any]
    explanation_policy: dict[str, Any]
    cold_start_policy: dict[str, Any] = Field(default_factory=dict)


class StrategyDecisionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class EvaluationRunRequest(BaseModel):
    dataset_id: UUID
    strategy_id: UUID


class RebuildRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ExperimentCreateRequest(BaseModel):
    experiment_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=300)
    hypothesis: str = Field(min_length=1)
    control_strategy_id: UUID
    treatment_strategy_ids: list[UUID] = Field(min_length=1)
    eligibility_definition: dict[str, Any] = Field(default_factory=dict)
    allocation_policy: dict[str, Any] = Field(default_factory=dict)
    primary_metrics: list[str] = Field(default_factory=list)
    guardrail_metrics: list[str] = Field(default_factory=list)


class ExperimentDecisionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
