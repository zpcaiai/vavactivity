"""Diversification stays inside the qualified candidate set."""

from __future__ import annotations

from uuid import uuid4

from vav.modules.recommendations.ranking import (
    RankingCandidate,
    RankingPolicy,
    intra_list_diversity,
    rank_candidates,
)


def _candidate(score: int, city: str, interests: tuple[str, ...] = ()) -> RankingCandidate:
    return RankingCandidate(
        candidate_pair_id=uuid4(),
        candidate_user_id=uuid4(),
        base_score_bps=score,
        minimum_directional_score_bps=score - 500,
        confidence_bps=8_000,
        city_code=city,
        region_code="east",
        interest_codes=interests,
    )


def test_diversification_spaces_out_similar_candidates() -> None:
    candidates = [
        _candidate(7_000, "shanghai", ("reading", "music")),
        _candidate(6_950, "shanghai", ("reading", "music")),
        _candidate(6_900, "hangzhou", ("sports",)),
    ]
    ranked = rank_candidates(candidates, seed="s", limit=3)
    assert ranked[1].candidate_pair_id == candidates[2].candidate_pair_id
    assert ranked[1].diversity_adjustment_bps <= 0


def test_diversification_only_reorders_candidates_it_was_given() -> None:
    candidates = [_candidate(7_000, "shanghai") for _ in range(4)]
    ranked = rank_candidates(candidates, seed="s", limit=4)
    given = {item.candidate_pair_id for item in candidates}
    produced = {item.candidate_pair_id for item in ranked}
    assert produced <= given


def test_city_cap_prevents_one_city_dominating_the_list() -> None:
    candidates = [_candidate(7_000 - index, "shanghai") for index in range(6)]
    candidates.append(_candidate(6_000, "taipei"))
    ranked = rank_candidates(
        candidates, seed="s", limit=6, policy=RankingPolicy(max_same_city_in_top=2)
    )
    assert any(item.diversity_adjustment_bps < 0 for item in ranked)


def test_intra_list_diversity_is_reported_in_basis_points() -> None:
    identical = [_candidate(7_000, "shanghai", ("reading",)) for _ in range(3)]
    varied = [
        _candidate(7_000, "shanghai", ("reading",)),
        _candidate(7_000, "taipei", ("sports",)),
        _candidate(7_000, "hangzhou", ("cooking",)),
    ]
    assert intra_list_diversity(varied) > intra_list_diversity(identical)
    assert 0 <= intra_list_diversity(identical) <= 10_000
    assert intra_list_diversity([identical[0]]) == 10_000
