"""The baseline recommendation strategy and its versioned policy documents.

Every tunable number lives inside a strategy version: nothing that changes a
recommendation may be hard-coded in more than one service, and a rollback is
simply re-activating a previous version.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from vav.core.config import Settings, get_settings
from vav.modules.recommendations.bidirectional import (
    BIDIRECTIONAL_POLICY_VERSION,
    DEFAULT_GEOMETRIC_WEIGHT,
    DEFAULT_MINIMUM_WEIGHT,
)
from vav.modules.recommendations.cold_start import COLD_START_POLICY_VERSION
from vav.modules.recommendations.constraints import HARD_CONSTRAINT_POLICY_VERSION
from vav.modules.recommendations.domain import SUPPORTED_HARD_CONSTRAINTS
from vav.modules.recommendations.explanations import EXPLANATION_POLICY_VERSION
from vav.modules.recommendations.exposure import ExposurePolicy
from vav.modules.recommendations.features import FEATURE_REGISTRY_VERSION, feature_manifest
from vav.modules.recommendations.ranking import RankingPolicy
from vav.modules.recommendations.scoring import IMPORTANCE_WEIGHTS, SCORING_POLICY_VERSION

BASELINE_STRATEGY_CODE = "baseline-bidirectional-v1"
BASELINE_STRATEGY_VERSION = "1.0.0"


def ranking_policy(settings: Settings | None = None) -> RankingPolicy:
    active = settings or get_settings()
    return RankingPolicy(exploration_slot_count=active.recommendation_exploration_slot_count)


def exposure_policy(settings: Settings | None = None) -> ExposurePolicy:
    active = settings or get_settings()
    return ExposurePolicy(
        daily_received_limit=active.recommendation_max_daily_received,
        daily_batch_size=active.recommendation_daily_batch_size,
        daily_shown_limit_per_profile=active.recommendation_max_daily_shown_per_profile,
        repeat_exposure_cooldown_days=active.recommendation_repeat_exposure_cooldown_days,
        visible_min_ms=active.recommendation_exposure_visible_min_ms,
        cold_start_minimum_exposures=active.recommendation_cold_start_min_exposures,
    )


def hard_constraint_policy(settings: Settings | None = None) -> dict[str, Any]:
    active = settings or get_settings()
    return {
        "policy_version": HARD_CONSTRAINT_POLICY_VERSION,
        "supported_criteria": list(SUPPORTED_HARD_CONSTRAINTS),
        "platform_rules": ["adult_eligibility", "relationship_eligibility"],
        "auto_relax": active.recommendation_hard_constraint_auto_relax,
        "allow_user_relaxation": active.recommendation_allow_user_relaxation,
        "unknown_value_policy": active.recommendation_unknown_value_policy,
        "minimum_age": active.dating_minimum_age,
    }


def scoring_policy(settings: Settings | None = None) -> dict[str, Any]:
    active = settings or get_settings()
    return {
        "policy_version": SCORING_POLICY_VERSION,
        "feature_registry_version": FEATURE_REGISTRY_VERSION,
        "importance_weights": dict(IMPORTANCE_WEIGHTS),
        "missingness_policy": active.recommendation_missingness_policy,
        "missing_penalty_bps": active.recommendation_missing_penalty_bps,
        "minimum_confidence_bps": active.recommendation_min_confidence_bps,
    }


def bidirectional_policy(settings: Settings | None = None) -> dict[str, Any]:
    active = settings or get_settings()
    return {
        "policy_version": BIDIRECTIONAL_POLICY_VERSION,
        "geometric_weight": DEFAULT_GEOMETRIC_WEIGHT,
        "minimum_weight": DEFAULT_MINIMUM_WEIGHT,
        "minimum_directional_score_bps": active.recommendation_min_directional_score_bps,
        "minimum_bidirectional_score_bps": active.recommendation_min_bidirectional_score_bps,
        "asymmetry_penalty_threshold_bps": 3_000,
    }


def explanation_policy() -> dict[str, Any]:
    return {
        "policy_version": EXPLANATION_POLICY_VERSION,
        "generator": "deterministic_template",
        "ai_rewrite_enabled": False,
        "max_items_per_section": 4,
        "shows_numeric_score": False,
        "shows_other_member_preferences": False,
    }


def cold_start_policy(settings: Settings | None = None) -> dict[str, Any]:
    active = settings or get_settings()
    return {
        "policy_version": COLD_START_POLICY_VERSION,
        "exploration_slot_count": active.recommendation_exploration_slot_count,
        "cold_start_minimum_exposures": active.recommendation_cold_start_min_exposures,
        "feedback_personalization_default": active.recommendation_feedback_personalization_default,
    }


def baseline_strategy_payload(settings: Settings | None = None) -> dict[str, Any]:
    """The full, serialisable baseline strategy stored as one version row."""
    active = settings or get_settings()
    ranking = ranking_policy(active)
    return {
        "strategy_code": BASELINE_STRATEGY_CODE,
        "semantic_version": BASELINE_STRATEGY_VERSION,
        "hard_constraint_policy": hard_constraint_policy(active),
        "feature_manifest": {
            "feature_registry_version": FEATURE_REGISTRY_VERSION,
            "features": feature_manifest(),
        },
        "scoring_policy": scoring_policy(active),
        "bidirectional_policy": bidirectional_policy(active),
        "ranking_policy": ranking.as_dict(),
        "diversification_policy": {
            "policy_version": ranking.as_dict()["diversification_policy_version"],
            "dimensions": ["city", "region", "interests", "lifestyle", "profile_novelty"],
            "max_same_city_in_top": ranking.max_same_city_in_top,
            "diversity_penalty_bps": ranking.diversity_penalty_bps,
            "bypasses_hard_constraints": False,
        },
        "exposure_policy": exposure_policy(active).as_dict(),
        "explanation_policy": explanation_policy(),
        "cold_start_policy": cold_start_policy(active),
        "applicable_regions": [],
        "applicable_segments": [],
    }
