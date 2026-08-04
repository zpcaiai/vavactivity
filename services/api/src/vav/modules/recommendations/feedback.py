"""Feedback handling and bounded, reversible personalisation.

Safety feedback is routed to the safety module and removed from candidacy; it
is never recycled as taste data. A skip starts a cooldown, not a permanent
rejection, and "not relevant" may nudge a weight but can never create a new
hard constraint.
"""

# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from vav.modules.recommendations.domain import (
    SAFETY_FEEDBACK_TYPES,
    RecommendationFeedbackType,
)

#: How each feedback type is allowed to affect future recommendations.
FEEDBACK_EFFECTS: dict[str, dict[str, Any]] = {
    RecommendationFeedbackType.IMPRESSION.value: {"learning": False, "removes_candidate": False},
    RecommendationFeedbackType.VIEWED.value: {"learning": False, "removes_candidate": False},
    RecommendationFeedbackType.PROFILE_OPENED.value: {"learning": True, "removes_candidate": False},
    RecommendationFeedbackType.LIKED.value: {"learning": True, "removes_candidate": False},
    RecommendationFeedbackType.SKIPPED.value: {
        "learning": True,
        "removes_candidate": False,
        "starts_cooldown": True,
    },
    RecommendationFeedbackType.NOT_RELEVANT.value: {
        "learning": True,
        "removes_candidate": False,
        "starts_cooldown": True,
        "may_create_hard_constraint": False,
    },
    RecommendationFeedbackType.WITHDRAWN.value: {"learning": False, "removes_candidate": False},
    RecommendationFeedbackType.MUTUAL_MATCHED.value: {"learning": True, "removes_candidate": True},
    RecommendationFeedbackType.INTRODUCTION_ACCEPTED.value: {
        "learning": True,
        "removes_candidate": True,
    },
    RecommendationFeedbackType.INTRODUCTION_DECLINED.value: {
        "learning": True,
        "removes_candidate": False,
        "starts_cooldown": True,
    },
    RecommendationFeedbackType.RELATIONSHIP_STARTED.value: {
        "learning": True,
        "removes_candidate": True,
    },
    RecommendationFeedbackType.RELATIONSHIP_ENDED.value: {
        "learning": False,
        "removes_candidate": False,
    },
    RecommendationFeedbackType.REPORTED.value: {
        "learning": False,
        "removes_candidate": True,
        "notifies_safety": True,
    },
    RecommendationFeedbackType.BLOCKED.value: {
        "learning": False,
        "removes_candidate": True,
        "notifies_safety": True,
    },
}

#: Reason code to the feature whose weight it may adjust.
REASON_TO_FEATURE: dict[str, str] = {
    "location_not_suitable": "geographic_compatibility",
    "faith_expectations_differ": "faith_status_alignment",
    "relationship_goal_differs": "relationship_intent_alignment",
    "family_or_children_expectations_differ": "children_expectation_alignment",
    "lifestyle_not_suitable": "daily_schedule_alignment",
    "profile_too_sparse": "profile_readiness",
}

MAX_ADJUSTMENT = 40
ADJUSTMENT_STEP = 5


def effects_for(feedback_type: str) -> dict[str, Any]:
    return FEEDBACK_EFFECTS.get(feedback_type, {"learning": False, "removes_candidate": False})


def is_safety_feedback(feedback_type: str) -> bool:
    return feedback_type in SAFETY_FEEDBACK_TYPES


def cooldown_until(
    feedback_type: str, *, cooldown_days: int, now: datetime | None = None
) -> datetime | None:
    if not effects_for(feedback_type).get("starts_cooldown"):
        return None
    return (now or datetime.now(UTC)) + timedelta(days=cooldown_days)


def apply_learning(
    current_adjustments: dict[str, int],
    *,
    feedback_type: str,
    reason_code: str | None,
    personalization_enabled: bool,
) -> dict[str, int]:
    """Return the updated, bounded weight adjustments.

    Safety feedback never becomes taste data, and no adjustment can turn into
    a hard exclusion — the magnitude is clamped well below that.
    """
    if not personalization_enabled:
        return dict(current_adjustments)
    if is_safety_feedback(feedback_type):
        return dict(current_adjustments)
    if not effects_for(feedback_type).get("learning"):
        return dict(current_adjustments)

    updated = dict(current_adjustments)
    if feedback_type in {
        RecommendationFeedbackType.NOT_RELEVANT.value,
        RecommendationFeedbackType.SKIPPED.value,
    }:
        feature = REASON_TO_FEATURE.get(str(reason_code))
        if feature:
            updated[feature] = max(-MAX_ADJUSTMENT, updated.get(feature, 0) - ADJUSTMENT_STEP)
    elif feedback_type in {
        RecommendationFeedbackType.LIKED.value,
        RecommendationFeedbackType.MUTUAL_MATCHED.value,
        RecommendationFeedbackType.INTRODUCTION_ACCEPTED.value,
        RecommendationFeedbackType.RELATIONSHIP_STARTED.value,
    }:
        for feature in ("faith_status_alignment", "relationship_intent_alignment"):
            updated[feature] = min(MAX_ADJUSTMENT, updated.get(feature, 0) + ADJUSTMENT_STEP)
    return updated


def learning_stage_summary() -> dict[str, Any]:
    """The first release learns by reviewed rules, not by an online model."""
    return {
        "stage": "explicit_rules_and_offline_re_estimation",
        "online_model_updates_user_logic": False,
        "requires_before_any_model_stage": [
            "feature_allow_list",
            "offline_evaluation",
            "fairness_evaluation",
            "privacy_approval",
            "versioned_strategy",
            "rollback_path",
        ],
    }
