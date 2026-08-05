"""Stable ranking and separately tracked adjustments."""

from __future__ import annotations

from uuid import uuid4

from vav.modules.recommendations.ranking import (
    RankingCandidate,
    RankingPolicy,
    rank_candidates,
    stable_tiebreak,
)


def _candidate(score: int, **overrides) -> RankingCandidate:
    payload = {
        "candidate_pair_id": uuid4(),
        "candidate_user_id": uuid4(),
        "base_score_bps": score,
        "minimum_directional_score_bps": score - 500,
        "confidence_bps": 8_000,
        "city_code": "shanghai",
    }
    payload.update(overrides)
    return RankingCandidate(**payload)  # type: ignore[arg-type]


def test_the_same_seed_and_candidates_produce_the_same_order() -> None:
    candidates = [_candidate(7_000 + index * 100) for index in range(8)]
    first = rank_candidates(candidates, seed="seed-a", limit=5)
    second = rank_candidates(candidates, seed="seed-a", limit=5)
    assert [item.candidate_pair_id for item in first] == [item.candidate_pair_id for item in second]
    assert [item.final_rank for item in first] == [1, 2, 3, 4, 5]


def test_equal_scores_are_broken_deterministically_not_randomly() -> None:
    candidates = [_candidate(7_000) for _ in range(6)]
    first = rank_candidates(candidates, seed="seed-b", limit=6)
    second = rank_candidates(candidates, seed="seed-b", limit=6)
    assert [item.candidate_pair_id for item in first] == [item.candidate_pair_id for item in second]
    assert stable_tiebreak("seed-b", candidates[0].candidate_pair_id) == stable_tiebreak(
        "seed-b", candidates[0].candidate_pair_id
    )


def test_final_ranks_are_unique_and_contiguous() -> None:
    ranked = rank_candidates([_candidate(6_000 + index) for index in range(10)], seed="s", limit=10)
    positions = [item.final_rank for item in ranked]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)


def test_adjustments_are_recorded_separately_from_the_compatibility_score() -> None:
    ranked = rank_candidates(
        [
            _candidate(7_000, profile_age_days=2, never_exposed=True),
            _candidate(
                7_000, profile_age_days=400, days_since_last_exposure=3, shown_count_today=80
            ),
        ],
        seed="s",
        limit=2,
    )
    fresh, seen = ranked[0], ranked[1]
    assert fresh.base_score_bps == seen.base_score_bps == 7_000
    assert fresh.novelty_adjustment_bps > 0
    assert seen.exposure_adjustment_bps < 0
    assert fresh.adjusted_score_bps > seen.adjusted_score_bps
    assert "policy" in fresh.adjustment_snapshot


def test_ranking_never_returns_more_than_the_requested_limit() -> None:
    ranked = rank_candidates([_candidate(7_000) for _ in range(20)], seed="s", limit=3)
    assert len(ranked) == 3
    assert rank_candidates([], seed="s", limit=5) == []
    assert rank_candidates([_candidate(7_000)], seed="s", limit=0) == []


def test_exploration_slots_are_limited_by_policy() -> None:
    candidates = [_candidate(6_000, never_exposed=True) for _ in range(6)]
    ranked = rank_candidates(
        candidates, seed="s", limit=6, policy=RankingPolicy(exploration_slot_count=2)
    )
    boosted = [item for item in ranked if item.exploration_adjustment_bps > 0]
    assert len(boosted) == 2
