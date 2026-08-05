"""Cold-start inputs, exploration and honest empty results."""

from __future__ import annotations

from vav.modules.recommendations.cold_start import (
    COLD_START_POLICY_VERSION,
    SPARSE_PREFERENCE_THRESHOLD,
    SPARSE_REGION_THRESHOLD,
    assess,
    empty_result_report,
)
from vav.modules.recommendations.domain import ColdStartType


def test_cold_start_only_uses_declared_profile_signals() -> None:
    assessment = assess(
        account_age_days=3,
        profile_approved_days=3,
        stated_criteria_count=0,
        eligible_profiles_in_region=100,
        interaction_count=0,
    )
    serialised = str(assessment.as_dict())
    for forbidden in ("ai_", "counseling", "payment", "photo"):
        assert forbidden not in serialised


def test_sparse_region_grants_an_extra_exploration_slot() -> None:
    dense = assess(
        account_age_days=100,
        profile_approved_days=100,
        stated_criteria_count=6,
        eligible_profiles_in_region=SPARSE_REGION_THRESHOLD + 1,
        interaction_count=10,
        base_exploration_slots=2,
    )
    sparse = assess(
        account_age_days=100,
        profile_approved_days=100,
        stated_criteria_count=6,
        eligible_profiles_in_region=SPARSE_REGION_THRESHOLD - 1,
        interaction_count=10,
        base_exploration_slots=2,
    )
    assert sparse.exploration_slots == dense.exploration_slots + 1
    assert ColdStartType.SPARSE_REGION.value in sparse.types


def test_sparse_preferences_switch_on_transparent_defaults() -> None:
    assessment = assess(
        account_age_days=100,
        profile_approved_days=100,
        stated_criteria_count=SPARSE_PREFERENCE_THRESHOLD - 1,
        eligible_profiles_in_region=200,
        interaction_count=5,
    )
    assert assessment.uses_platform_defaults
    assert assessment.guidance_codes


def test_no_interaction_history_still_yields_recommendations() -> None:
    assessment = assess(
        account_age_days=100,
        profile_approved_days=100,
        stated_criteria_count=6,
        eligible_profiles_in_region=200,
        interaction_count=0,
    )
    assert assessment.types == [ColdStartType.NO_INTERACTION_HISTORY.value]
    assert assessment.exploration_slots >= 0


def test_empty_result_report_names_no_member_and_offers_actions() -> None:
    report = empty_result_report(
        pool_size=10,
        recalled=0,
        hard_constraint_failures={},
        safety_excluded=0,
        cooldown_excluded=0,
    )
    assert report["most_restrictive_criteria"] == []
    assert "pause_recommendations" in report["available_actions"]
    assert report["policy_version"] == COLD_START_POLICY_VERSION
