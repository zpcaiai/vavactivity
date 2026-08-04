"""Exposure budgets, cold start and exploration."""

# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from vav.modules.recommendations import coldstart, exposure
from vav.modules.recommendations.domain import ColdStartType, RecommendationExposureType
from vav.modules.recommendations.strategy import COLD_START_POLICY, EXPOSURE_POLICY

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
MINIMUM_VISIBLE_MS = int(EXPOSURE_POLICY["visible_minimum_ms"])


# --- exposure -------------------------------------------------------------


def test_a_rendered_card_is_not_an_exposure() -> None:
    assert not exposure.counts_as_visible(
        RecommendationExposureType.CARD_IMPRESSION.value,
        99999,
        minimum_visible_ms=MINIMUM_VISIBLE_MS,
    )
    assert EXPOSURE_POLICY["count_impression_as_exposure"] is False


def test_a_card_must_be_visible_long_enough_to_count() -> None:
    assert not exposure.counts_as_visible(
        RecommendationExposureType.CARD_VISIBLE.value, 200, minimum_visible_ms=MINIMUM_VISIBLE_MS
    )
    assert exposure.counts_as_visible(
        RecommendationExposureType.CARD_VISIBLE.value,
        MINIMUM_VISIBLE_MS,
        minimum_visible_ms=MINIMUM_VISIBLE_MS,
    )
    assert not exposure.counts_as_visible(
        RecommendationExposureType.CARD_VISIBLE.value, None, minimum_visible_ms=MINIMUM_VISIBLE_MS
    )


def test_opening_a_profile_or_photo_always_counts() -> None:
    for kind in (
        RecommendationExposureType.PROFILE_OPENED.value,
        RecommendationExposureType.PHOTO_VIEWED.value,
    ):
        assert exposure.counts_as_visible(kind, None, minimum_visible_ms=MINIMUM_VISIBLE_MS)


def test_receiving_and_being_shown_are_two_separate_budgets() -> None:
    budget = {
        "daily_received_limit": 5,
        "current_received_count": 5,
        "daily_shown_limit": 50,
        "current_shown_count": 3,
    }
    assert exposure.remaining_received(budget, 5) == 0
    # Their own inbox is full, but they may still be shown to other people.
    assert exposure.can_show_profile(budget, 50)


def test_a_missing_budget_row_falls_back_to_the_configured_limit() -> None:
    assert exposure.remaining_received(None, 7) == 7
    assert exposure.can_show_profile(None, 7)


def test_the_shown_budget_stops_at_its_limit() -> None:
    budget = {
        "daily_received_limit": 5,
        "current_received_count": 0,
        "daily_shown_limit": 4,
        "current_shown_count": 4,
    }
    assert not exposure.can_show_profile(budget, 4)


def test_the_repeat_cooldown_expires_on_its_own() -> None:
    cooldown = int(EXPOSURE_POLICY["repeat_cooldown_days"])
    assert exposure.in_repeat_cooldown(NOW - timedelta(days=1), cooldown_days=cooldown, now=NOW)
    assert not exposure.in_repeat_cooldown(
        NOW - timedelta(days=cooldown + 1), cooldown_days=cooldown, now=NOW
    )
    assert not exposure.in_repeat_cooldown(None, cooldown_days=cooldown, now=NOW)


def test_membership_may_never_change_another_persons_rules() -> None:
    never = set(EXPOSURE_POLICY["membership_may_never_affect"])
    assert {"other_party_hard_constraints", "safety_restrictions", "privacy_settings"} <= never
    assert not never & set(EXPOSURE_POLICY["membership_may_affect"])


def test_fairness_is_measured_among_qualified_profiles_only() -> None:
    even = exposure.exposure_fairness({"a": 5, "b": 5, "c": 5}, 3)
    skewed = exposure.exposure_fairness({"a": 15, "b": 0, "c": 0}, 3)
    assert even["measured_within_qualified_candidates_only"] is True
    assert even["coverage_bps"] == 10000
    assert skewed["never_exposed_count"] == 2
    assert skewed["gini_bps"] > even["gini_bps"]
    assert skewed["max_exposure_share_bps"] == 10000


def test_fairness_on_an_empty_pool_is_reported_not_divided_by_zero() -> None:
    assert exposure.exposure_fairness({}, 0)["eligible_profiles"] == 0


def test_popularity_suppression_is_a_threshold_not_a_removal() -> None:
    assert exposure.popularity_suppressed(30, 30)
    assert not exposure.popularity_suppressed(29, 30)


# --- cold start -----------------------------------------------------------


def test_a_brand_new_member_is_recognised_across_every_dimension() -> None:
    types = coldstart.classify(
        account_created_at=NOW - timedelta(days=1),
        profile_approved_at=NOW - timedelta(hours=2),
        criteria_count=0,
        pool_size_in_region=3,
        interaction_count=0,
        now=NOW,
    )
    assert set(types) == {
        ColdStartType.NEW_USER.value,
        ColdStartType.NEW_PROFILE.value,
        ColdStartType.SPARSE_PREFERENCES.value,
        ColdStartType.SPARSE_REGION.value,
        ColdStartType.NO_INTERACTION_HISTORY.value,
    }


def test_an_established_member_is_not_treated_as_cold() -> None:
    assert (
        coldstart.classify(
            account_created_at=NOW - timedelta(days=400),
            profile_approved_at=NOW - timedelta(days=300),
            criteria_count=6,
            pool_size_in_region=500,
            interaction_count=40,
            now=NOW,
        )
        == []
    )


def test_exploration_intensity_follows_the_members_own_setting() -> None:
    base = coldstart.exploration_slot_count([], "balanced")
    assert coldstart.exploration_slot_count([], "focused") < base
    assert coldstart.exploration_slot_count([], "open") > base
    assert (
        coldstart.exploration_slot_count([ColdStartType.SPARSE_PREFERENCES.value], "balanced")
        > base
    )


def test_exploration_picks_only_from_qualified_candidates() -> None:
    qualified: list[dict[str, Any]] = [
        {
            "candidate_pair_id": "ok",
            "bidirectional_score_bps": 6000,
            "never_exposed": True,
            "hard_constraints_passed": True,
            "safety_allowed": True,
        },
        {
            "candidate_pair_id": "too-low",
            "bidirectional_score_bps": 1000,
            "never_exposed": True,
            "hard_constraints_passed": True,
            "safety_allowed": True,
        },
        {
            "candidate_pair_id": "constraint-failed",
            "bidirectional_score_bps": 9000,
            "never_exposed": True,
            "hard_constraints_passed": False,
            "safety_allowed": True,
        },
        {
            "candidate_pair_id": "unsafe",
            "bidirectional_score_bps": 9500,
            "never_exposed": True,
            "hard_constraints_passed": True,
            "safety_allowed": False,
        },
    ]
    chosen = coldstart.select_exploration_candidates(
        qualified, already_selected_ids=set(), slots=3, minimum_bidirectional_bps=3000
    )
    assert [item["candidate_pair_id"] for item in chosen] == ["ok"]
    assert chosen[0]["is_exploration_slot"] is True
    assert chosen[0]["exploration_adjustment_bps"] > 0
    assert COLD_START_POLICY["exploration_must_pass_hard_constraints"] is True
    assert COLD_START_POLICY["exploration_must_meet_minimum_bidirectional_score"] is True


def test_exploration_never_duplicates_an_already_selected_candidate() -> None:
    pool = [
        {
            "candidate_pair_id": "already",
            "bidirectional_score_bps": 9000,
            "hard_constraints_passed": True,
            "safety_allowed": True,
        }
    ]
    assert (
        coldstart.select_exploration_candidates(
            pool, already_selected_ids={"already"}, slots=2, minimum_bidirectional_bps=3000
        )
        == []
    )
    assert (
        coldstart.select_exploration_candidates(
            pool, already_selected_ids=set(), slots=0, minimum_bidirectional_bps=3000
        )
        == []
    )


def test_a_new_profile_gets_a_floor_of_exposure_then_stops_being_special() -> None:
    assert coldstart.new_profile_needs_exposure(
        profile_approved_at=NOW - timedelta(days=1), exposure_count=0, now=NOW
    )
    assert not coldstart.new_profile_needs_exposure(
        profile_approved_at=NOW - timedelta(days=1),
        exposure_count=int(COLD_START_POLICY["new_profile_minimum_exposures"]),
        now=NOW,
    )
    assert not coldstart.new_profile_needs_exposure(
        profile_approved_at=NOW - timedelta(days=90), exposure_count=0, now=NOW
    )
    assert not coldstart.new_profile_needs_exposure(
        profile_approved_at=None, exposure_count=0, now=NOW
    )


def test_sparse_preference_guidance_is_advice_never_a_requirement() -> None:
    guidance = coldstart.preference_guidance(0)
    assert guidance["needed"]
    assert guidance["mandatory_fields"] == []
    assert not coldstart.preference_guidance(9)["needed"]


def test_an_empty_batch_is_explained_honestly() -> None:
    guidance = coldstart.empty_result_guidance(
        {"blocking_criteria": {"age_range": 40, "city_code": 12, "faith_status_code": 3}}
    )
    assert guidance["largest_reductions"][0]["criterion_code"] == "age_range"
    assert len(guidance["largest_reductions"]) <= 3
    assert "静默绕过硬性条件" in guidance["never_done"]
    assert "制造虚假推荐" in guidance["never_done"]
    assert guidance["options"]
