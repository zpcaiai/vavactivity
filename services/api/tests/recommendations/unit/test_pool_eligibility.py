"""Pool eligibility, exclusion codes and empty-result reporting."""

from __future__ import annotations

from vav.modules.recommendations.cold_start import (
    EMPTY_RESULT_ACTIONS,
    GUIDANCE_CODES,
    assess,
    empty_result_report,
    exploration_slots_for,
)
from vav.modules.recommendations.domain import (
    NON_RELAXABLE_CRITERIA,
    PAIR_EXCLUSION_CODES,
    POOL_INELIGIBILITY_CODES,
    ColdStartType,
)


def test_pool_reason_codes_cover_every_documented_exclusion() -> None:
    for code in (
        "account_not_active",
        "profile_not_active",
        "no_approved_version",
        "below_minimum_age",
        "recommendation_paused_by_user",
        "security_suspension",
        "deletion_in_progress",
    ):
        assert code in POOL_INELIGIBILITY_CODES


def test_pair_exclusions_cover_block_relationship_and_cooldown() -> None:
    for code in (
        "same_user",
        "blocked_pair",
        "safety_restriction",
        "existing_relationship",
        "active_invitation",
        "skip_cooldown",
        "privacy_not_allowed",
    ):
        assert code in PAIR_EXCLUSION_CODES


def test_safety_rules_are_never_relaxable() -> None:
    for code in ("adult_eligibility", "relationship_eligibility", "safety_block"):
        assert code in NON_RELAXABLE_CRITERIA


def test_new_member_without_history_is_classified_as_cold_start() -> None:
    assessment = assess(
        account_age_days=1,
        profile_approved_days=1,
        stated_criteria_count=1,
        eligible_profiles_in_region=4,
        interaction_count=0,
    )
    assert assessment.is_cold_start
    assert ColdStartType.NEW_USER.value in assessment.types
    assert ColdStartType.SPARSE_PREFERENCES.value in assessment.types
    assert ColdStartType.SPARSE_REGION.value in assessment.types
    assert assessment.uses_platform_defaults
    assert assessment.guidance_codes == list(GUIDANCE_CODES)


def test_established_member_is_not_cold_start() -> None:
    assessment = assess(
        account_age_days=400,
        profile_approved_days=200,
        stated_criteria_count=8,
        eligible_profiles_in_region=500,
        interaction_count=25,
    )
    assert not assessment.is_cold_start
    assert assessment.guidance_codes == []


def test_exploration_level_changes_slot_count_within_bounds() -> None:
    assert exploration_slots_for("conservative", 2) == 1
    assert exploration_slots_for("balanced", 2) == 2
    assert exploration_slots_for("adventurous", 2) == 4
    assert exploration_slots_for("conservative", 0) == 0


def test_empty_result_report_is_aggregate_and_actionable() -> None:
    report = empty_result_report(
        pool_size=120,
        recalled=40,
        hard_constraint_failures={"age_range": 22, "city_code": 9, "faith_status_code": 3},
        safety_excluded=1,
        cooldown_excluded=4,
    )
    assert report["most_restrictive_criteria"][0]["criterion_code"] == "age_range"
    assert report["available_actions"] == list(EMPTY_RESULT_ACTIONS)
    # The report counts criteria; it never identifies another member.
    serialised = str(report)
    assert "user" not in serialised.lower()
