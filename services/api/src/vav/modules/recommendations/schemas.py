"""Request models for the recommendation API."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BatchRequest(BaseModel):
    batch_type: Literal["daily", "supplemental"] = "daily"
    requested_size: int | None = Field(default=None, ge=1, le=50)


class ExposureRequest(BaseModel):
    exposure_type: Literal["card_impression", "card_visible", "profile_opened", "photo_viewed"]
    duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    source: str = Field(default="recommendation_list", max_length=32)


class FeedbackRequest(BaseModel):
    feedback_type: Literal["impression", "viewed", "profile_opened", "not_relevant"]
    reason_code: str | None = Field(default=None, max_length=128)
    reason_details: str | None = Field(default=None, max_length=2_000)


class RecommendationSettingsRequest(BaseModel):
    recommendations_paused: bool | None = None
    daily_received_limit: int | None = Field(default=None, ge=0, le=50)
    delivery_frequency: Literal["daily", "weekly", "manual"] | None = None
    extended_recommendations_enabled: bool | None = None
    relaxable_criteria: list[str] | None = None
    preferred_locale: str | None = Field(default=None, max_length=16)


class TuningRequest(BaseModel):
    feedback_personalization_enabled: bool | None = None
    exploration_level: Literal["conservative", "balanced", "adventurous"] | None = None


class StrategyCreateRequest(BaseModel):
    strategy_code: str = Field(max_length=128)
    semantic_version: str = Field(max_length=64)
    hard_constraint_policy: dict[str, Any]
    feature_manifest: dict[str, Any]
    scoring_policy: dict[str, Any]
    bidirectional_policy: dict[str, Any]
    ranking_policy: dict[str, Any]
    diversification_policy: dict[str, Any]
    exposure_policy: dict[str, Any]
    explanation_policy: dict[str, Any]
    cold_start_policy: dict[str, Any] = Field(default_factory=dict)
    applicable_regions: list[str] = Field(default_factory=list)
    applicable_segments: list[str] = Field(default_factory=list)


class StrategyTransitionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class EvaluationRunRequest(BaseModel):
    dataset_code: str = Field(max_length=128)
    strategy_id: UUID
    metrics: dict[str, int] = Field(default_factory=dict)
    guardrail_thresholds: dict[str, int] | None = None


class ExperimentCreateRequest(BaseModel):
    experiment_code: str = Field(max_length=128)
    name: str = Field(max_length=300)
    hypothesis: str
    control_strategy_id: UUID
    treatment_strategy_ids: list[UUID] = Field(default_factory=list)
    eligibility_definition: dict[str, Any] = Field(default_factory=dict)
    allocation_policy: dict[str, Any] = Field(default_factory=dict)
    primary_metrics: list[str] = Field(default_factory=list)
    guardrail_metrics: list[str] = Field(default_factory=list)
    guardrail_thresholds: dict[str, int] = Field(default_factory=dict)


class ExperimentTransitionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ExperimentGuardrailRequest(BaseModel):
    metrics: dict[str, int] = Field(default_factory=dict)


class BatchRebuildRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    batch_type: Literal["daily", "supplemental", "manual_rebuild"] = "manual_rebuild"


class BatchInvalidateRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
