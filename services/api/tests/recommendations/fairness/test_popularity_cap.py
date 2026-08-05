"""Popular profiles are capped without penalising them out of existence."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import uuid4

from vav.modules.recommendations.exposure import ExposurePolicy, can_show_profile
from vav.modules.recommendations.ranking import RankingCandidate, RankingPolicy, rank_candidates

POLICY = ExposurePolicy()


def _candidate(score: int, shown: int) -> RankingCandidate:
    return RankingCandidate(
        candidate_pair_id=uuid4(),
        candidate_user_id=uuid4(),
        base_score_bps=score,
        minimum_directional_score_bps=score - 300,
        confidence_bps=8_000,
        shown_count_today=shown,
        city_code="shanghai",
    )


def test_a_profile_at_the_daily_cap_stops_receiving_new_exposure() -> None:
    assert can_show_profile(policy=POLICY, shown_count_today=49).allowed
    assert not can_show_profile(policy=POLICY, shown_count_today=50).allowed


def test_a_heavily_shown_profile_is_suppressed_not_removed() -> None:
    popular = _candidate(8_000, shown=80)
    quiet = _candidate(7_800, shown=0)
    ranked = rank_candidates(
        [popular, quiet], seed="fair", limit=2, policy=RankingPolicy(popularity_threshold=30)
    )
    assert ranked[0].candidate_pair_id == quiet.candidate_pair_id
    # Still present, still traceable.
    assert ranked[1].candidate_pair_id == popular.candidate_pair_id
    assert ranked[1].exposure_adjustment_bps < 0


def test_suppression_is_recorded_in_the_adjustment_snapshot() -> None:
    ranked = rank_candidates([_candidate(8_000, shown=80)], seed="fair", limit=1)
    assert ranked[0].adjustment_snapshot["shown_count_today"] == 80
