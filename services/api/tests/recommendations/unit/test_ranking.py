"""Stable ranking, adjustments and diversification."""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any

import pytest

from vav.modules.recommendations import ranking
from vav.modules.recommendations.strategy import DIVERSIFICATION_POLICY


def candidate(pair_id: str, score: int, **overrides: Any) -> dict[str, Any]:
    return {
        "candidate_pair_id": pair_id,
        "bidirectional_score_bps": score,
        "confidence_bps": 8000,
        "city_code": "shanghai",
        "faith_codes": ["reformed"],
        "lifestyle_codes": ["reading"],
        **overrides,
    }


def test_the_jitter_is_reproducible_and_tiny() -> None:
    first = ranking.deterministic_jitter("seed-a", "pair-1")
    assert first == ranking.deterministic_jitter("seed-a", "pair-1")
    assert first != ranking.deterministic_jitter("seed-b", "pair-1")
    assert 0 <= first <= 40


def test_ranking_a_batch_twice_gives_the_identical_order() -> None:
    pool = [candidate(f"pair-{index}", 5000 + index * 100) for index in range(10)]
    first = ranking.stable_sort(ranking.apply_adjustments(pool, seed="batch-seed"))
    second = ranking.stable_sort(ranking.apply_adjustments(pool, seed="batch-seed"))
    assert [item["candidate_pair_id"] for item in first] == [
        item["candidate_pair_id"] for item in second
    ]


def test_ties_break_on_confidence_then_on_a_stable_identifier() -> None:
    pool = [
        {**candidate("pair-b", 6000), "adjusted_score_bps": 6000, "confidence_bps": 5000},
        {**candidate("pair-a", 6000), "adjusted_score_bps": 6000, "confidence_bps": 5000},
        {**candidate("pair-c", 6000), "adjusted_score_bps": 6000, "confidence_bps": 9000},
    ]
    ordered = ranking.stable_sort(pool)
    assert [item["candidate_pair_id"] for item in ordered] == ["pair-c", "pair-a", "pair-b"]


def test_adjustments_are_reported_separately_from_the_match_score() -> None:
    adjusted = ranking.apply_adjustments(
        [candidate("pair-1", 7000, recently_exposed=True)], seed="s"
    )[0]
    assert adjusted["base_score_bps"] == 7000
    assert adjusted["exposure_adjustment_bps"] < 0
    assert adjusted["adjusted_score_bps"] != adjusted["base_score_bps"]
    assert adjusted["adjustment_snapshot"]["raw_compatibility_preserved"] is True


def test_a_never_seen_profile_gets_a_novelty_bonus() -> None:
    fresh = ranking.apply_adjustments([candidate("p", 7000, never_exposed=True)], seed="s")[0]
    seen = ranking.apply_adjustments([candidate("p", 7000)], seed="s")[0]
    assert fresh["novelty_adjustment_bps"] > 0
    assert fresh["adjusted_score_bps"] > seen["adjusted_score_bps"]


def test_a_heavily_shown_profile_is_suppressed_not_removed() -> None:
    popular = ranking.apply_adjustments(
        [candidate("p", 7000, recent_exposure_count=500)], seed="s"
    )[0]
    assert popular["exposure_adjustment_bps"] < 0
    assert popular["adjusted_score_bps"] > 0
    assert popular["base_score_bps"] == 7000


def test_adjusted_scores_stay_within_basis_point_bounds() -> None:
    adjusted = ranking.apply_adjustments(
        [
            candidate("high", 9990, never_exposed=True, exploration_adjustment_bps=5000),
            candidate("low", 100, recently_exposed=True, recent_exposure_count=999),
        ],
        seed="s",
    )
    for item in adjusted:
        assert 0 <= item["adjusted_score_bps"] <= 10000


def test_diversification_never_admits_an_unqualified_candidate() -> None:
    pool = ranking.apply_adjustments(
        [candidate(f"pair-{index}", 6000 + index) for index in range(6)], seed="s"
    )
    selected = ranking.diversify(pool, size=4)
    assert len(selected) == 4
    admitted = {item["candidate_pair_id"] for item in selected}
    assert admitted <= {item["candidate_pair_id"] for item in pool}


def test_a_policy_that_claims_to_bypass_hard_constraints_is_refused() -> None:
    with pytest.raises(ValueError):
        ranking.diversify(
            ranking.apply_adjustments([candidate("p", 7000)], seed="s"),
            size=1,
            policy={**DIVERSIFICATION_POLICY, "may_bypass_hard_constraints": True},
        )


def test_diversification_breaks_up_a_monoculture() -> None:
    pool = ranking.apply_adjustments(
        [candidate(f"sh-{index}", 9000 - index) for index in range(8)]
        + [candidate("bj-1", 8000, city_code="beijing", faith_codes=["anglican"])],
        seed="s",
    )
    selected = ranking.diversify(pool, size=5)
    cities = [item["city_code"] for item in selected]
    assert "beijing" in cities
    assert cities.count("shanghai") <= int(DIVERSIFICATION_POLICY["max_per_city"])


def test_a_city_cap_never_produces_an_under_filled_batch() -> None:
    pool = ranking.apply_adjustments(
        [candidate(f"sh-{index}", 9000 - index) for index in range(8)], seed="s"
    )
    selected = ranking.diversify(pool, size=6)
    assert len(selected) == 6


def test_the_top_result_stays_relevant_after_diversification() -> None:
    pool = ranking.apply_adjustments(
        [candidate("best", 9800)] + [candidate(f"rest-{i}", 5000 + i) for i in range(6)],
        seed="s",
    )
    selected = ranking.diversify(pool, size=4)
    assert selected[0]["candidate_pair_id"] == "best"
    assert [item["final_rank"] for item in selected] == [1, 2, 3, 4]


def test_diversification_is_deterministic() -> None:
    def build() -> list[dict[str, Any]]:
        return ranking.apply_adjustments(
            [
                candidate("a", 8000),
                candidate("b", 7900, city_code="beijing"),
                candidate("c", 7800, city_code="chengdu"),
                candidate("d", 7700),
            ],
            seed="fixed",
        )

    first = [item["candidate_pair_id"] for item in ranking.diversify(build(), size=3)]
    second = [item["candidate_pair_id"] for item in ranking.diversify(build(), size=3)]
    assert first == second


def test_an_empty_or_zero_sized_request_returns_nothing() -> None:
    assert ranking.diversify([], size=5) == []
    assert ranking.diversify(ranking.apply_adjustments([candidate("p", 1)], seed="s"), size=0) == []


def test_intra_list_diversity_rewards_a_varied_list() -> None:
    same = [candidate(f"p{i}", 7000) for i in range(4)]
    varied = [
        candidate("a", 7000),
        candidate(
            "b", 7000, city_code="beijing", faith_codes=["anglican"], lifestyle_codes=["hiking"]
        ),
        candidate(
            "c", 7000, city_code="chengdu", faith_codes=["baptist"], lifestyle_codes=["cooking"]
        ),
    ]
    assert ranking.intra_list_diversity(varied) > ranking.intra_list_diversity(same)
    assert ranking.intra_list_diversity([candidate("only", 7000)]) == 10000
