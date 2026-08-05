"""New profiles receive qualified exposure without bypassing any rule."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import uuid4

from vav.modules.recommendations.cold_start import assess
from vav.modules.recommendations.ranking import RankingCandidate, RankingPolicy, rank_candidates


def _candidate(score: int, **overrides) -> RankingCandidate:
    payload = {
        "candidate_pair_id": uuid4(),
        "candidate_user_id": uuid4(),
        "base_score_bps": score,
        "minimum_directional_score_bps": score - 300,
        "confidence_bps": 7_000,
        "city_code": "shanghai",
    }
    payload.update(overrides)
    return RankingCandidate(**payload)  # type: ignore[arg-type]


def test_a_never_exposed_profile_is_lifted_above_an_equal_established_one() -> None:
    fresh = _candidate(7_000, never_exposed=True, profile_age_days=1)
    established = _candidate(7_000, profile_age_days=500)
    ranked = rank_candidates([established, fresh], seed="fair", limit=2)
    assert ranked[0].candidate_pair_id == fresh.candidate_pair_id
    assert ranked[0].novelty_adjustment_bps > 0


def test_a_new_profile_cannot_outrank_a_much_better_match() -> None:
    fresh = _candidate(5_000, never_exposed=True, profile_age_days=1)
    strong = _candidate(9_500, profile_age_days=500)
    ranked = rank_candidates([fresh, strong], seed="fair", limit=2)
    assert ranked[0].candidate_pair_id == strong.candidate_pair_id


def test_cold_start_members_still_receive_exploration_slots() -> None:
    assessment = assess(
        account_age_days=1,
        profile_approved_days=1,
        stated_criteria_count=1,
        eligible_profiles_in_region=5,
        interaction_count=0,
        base_exploration_slots=2,
    )
    assert assessment.exploration_slots >= 3
    ranked = rank_candidates(
        [_candidate(6_000, never_exposed=True) for _ in range(5)],
        seed="fair",
        limit=5,
        policy=RankingPolicy(exploration_slot_count=assessment.exploration_slots),
    )
    assert (
        sum(1 for item in ranked if item.exploration_adjustment_bps > 0)
        == assessment.exploration_slots
    )
