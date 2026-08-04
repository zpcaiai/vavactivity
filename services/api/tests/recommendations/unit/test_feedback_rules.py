"""Feedback effects and bounded personalisation."""

# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime

from vav.modules.recommendations import feedback
from vav.modules.recommendations.domain import (
    SAFETY_FEEDBACK_TYPES,
    RecommendationFeedbackType,
)

NOW = datetime(2026, 8, 4, tzinfo=UTC)


def test_a_skip_starts_a_cooldown_rather_than_a_permanent_rejection() -> None:
    effects = feedback.effects_for(RecommendationFeedbackType.SKIPPED.value)
    assert effects["starts_cooldown"] is True
    assert effects["removes_candidate"] is False
    until = feedback.cooldown_until(
        RecommendationFeedbackType.SKIPPED.value, cooldown_days=90, now=NOW
    )
    assert until is not None and until > NOW


def test_passive_signals_do_not_start_a_cooldown() -> None:
    assert (
        feedback.cooldown_until(RecommendationFeedbackType.VIEWED.value, cooldown_days=90, now=NOW)
        is None
    )


def test_not_relevant_may_nudge_a_weight_but_never_creates_a_hard_constraint() -> None:
    effects = feedback.effects_for(RecommendationFeedbackType.NOT_RELEVANT.value)
    assert effects["may_create_hard_constraint"] is False
    updated = feedback.apply_learning(
        {},
        feedback_type=RecommendationFeedbackType.NOT_RELEVANT.value,
        reason_code="location_not_suitable",
        personalization_enabled=True,
    )
    assert updated["geographic_compatibility"] == -feedback.ADJUSTMENT_STEP


def test_repeated_negative_feedback_is_clamped_well_short_of_exclusion() -> None:
    adjustments: dict[str, int] = {}
    for _ in range(100):
        adjustments = feedback.apply_learning(
            adjustments,
            feedback_type=RecommendationFeedbackType.NOT_RELEVANT.value,
            reason_code="faith_expectations_differ",
            personalization_enabled=True,
        )
    assert adjustments["faith_status_alignment"] == -feedback.MAX_ADJUSTMENT
    assert abs(adjustments["faith_status_alignment"]) <= feedback.MAX_ADJUSTMENT


def test_repeated_positive_feedback_is_clamped_too() -> None:
    adjustments: dict[str, int] = {}
    for _ in range(100):
        adjustments = feedback.apply_learning(
            adjustments,
            feedback_type=RecommendationFeedbackType.LIKED.value,
            reason_code=None,
            personalization_enabled=True,
        )
    assert adjustments["faith_status_alignment"] == feedback.MAX_ADJUSTMENT


def test_safety_feedback_is_never_recycled_as_taste_data() -> None:
    assert set(SAFETY_FEEDBACK_TYPES) == {"blocked", "reported"}
    for kind in SAFETY_FEEDBACK_TYPES:
        assert feedback.is_safety_feedback(kind)
        assert feedback.effects_for(kind)["learning"] is False
        assert feedback.effects_for(kind)["removes_candidate"] is True
        assert feedback.effects_for(kind)["notifies_safety"] is True
        assert feedback.apply_learning(
            {"geographic_compatibility": -5},
            feedback_type=kind,
            reason_code="location_not_suitable",
            personalization_enabled=True,
        ) == {"geographic_compatibility": -5}


def test_turning_personalisation_off_stops_all_learning() -> None:
    before = {"geographic_compatibility": -10}
    after = feedback.apply_learning(
        before,
        feedback_type=RecommendationFeedbackType.NOT_RELEVANT.value,
        reason_code="location_not_suitable",
        personalization_enabled=False,
    )
    assert after == before
    assert after is not before  # returned as a copy, never mutated in place


def test_an_unknown_reason_code_changes_nothing() -> None:
    assert (
        feedback.apply_learning(
            {},
            feedback_type=RecommendationFeedbackType.NOT_RELEVANT.value,
            reason_code="something_unmapped",
            personalization_enabled=True,
        )
        == {}
    )


def test_a_concluded_relationship_removes_the_pair_from_candidacy() -> None:
    for kind in (
        RecommendationFeedbackType.MUTUAL_MATCHED.value,
        RecommendationFeedbackType.INTRODUCTION_ACCEPTED.value,
        RecommendationFeedbackType.RELATIONSHIP_STARTED.value,
    ):
        assert feedback.effects_for(kind)["removes_candidate"] is True


def test_an_ended_relationship_does_not_quietly_retrain_anything() -> None:
    effects = feedback.effects_for(RecommendationFeedbackType.RELATIONSHIP_ENDED.value)
    assert effects["learning"] is False
    assert effects["removes_candidate"] is False


def test_an_unrecognised_feedback_type_defaults_to_doing_nothing() -> None:
    effects = feedback.effects_for("something_invented")
    assert effects == {"learning": False, "removes_candidate": False}


def test_the_first_release_learns_by_reviewed_rules_not_an_online_model() -> None:
    summary = feedback.learning_stage_summary()
    assert summary["online_model_updates_user_logic"] is False
    assert {"feature_allow_list", "fairness_evaluation", "rollback_path"} <= set(
        summary["requires_before_any_model_stage"]
    )
