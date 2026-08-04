"""Stable ranking, diversification and exposure adjustments.

Ranking is deterministic for a fixed (strategy, candidate snapshot, seed), so
refreshing a page never reshuffles a batch. Adjusted scores are reported
separately from the raw compatibility score — an exposure penalty must never
masquerade as a lower match.
"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
from typing import Any

from vav.modules.recommendations.strategy import DIVERSIFICATION_POLICY, RANKING_POLICY


def deterministic_jitter(seed: str, candidate_pair_id: str, span_bps: int = 40) -> int:
    """A tiny reproducible tie-breaker; identical inputs always give the same value."""
    digest = hashlib.sha256(f"{seed}:{candidate_pair_id}".encode()).hexdigest()
    return int(digest[:8], 16) % (span_bps + 1)


def _dimension_values(candidate: dict[str, Any], dimension: str) -> set[str]:
    value = candidate.get(dimension)
    if value is None:
        return set()
    if isinstance(value, list):
        return {str(item) for item in value}
    return {str(value)}


def similarity(a: dict[str, Any], b: dict[str, Any], dimensions: list[str]) -> float:
    """Overlap between two already-qualified candidates, for diversification only."""
    scores: list[float] = []
    for dimension in dimensions:
        left = _dimension_values(a, dimension)
        right = _dimension_values(b, dimension)
        if not left and not right:
            continue
        union = left | right
        scores.append(len(left & right) / len(union) if union else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def apply_adjustments(
    candidates: list[dict[str, Any]],
    *,
    seed: str,
    policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Attach novelty, repeat-exposure and popularity adjustments to each candidate."""
    settings = policy or RANKING_POLICY
    adjusted: list[dict[str, Any]] = []
    for candidate in candidates:
        base = int(candidate["bidirectional_score_bps"])
        novelty = int(settings["novelty_bonus_bps"]) if candidate.get("never_exposed") else 0
        repeat = (
            -int(settings["repeat_exposure_penalty_bps"])
            if candidate.get("recently_exposed")
            else 0
        )
        popularity = (
            -int(settings["popular_profile_penalty_bps"])
            if int(candidate.get("recent_exposure_count", 0))
            >= int(settings["popular_profile_exposure_threshold"])
            else 0
        )
        exploration = int(candidate.get("exploration_adjustment_bps", 0))
        jitter = deterministic_jitter(seed, str(candidate["candidate_pair_id"]))
        total = max(0, min(10000, base + novelty + repeat + popularity + exploration + jitter))
        adjusted.append(
            {
                **candidate,
                "base_score_bps": base,
                "novelty_adjustment_bps": novelty,
                "exposure_adjustment_bps": repeat + popularity,
                "exploration_adjustment_bps": exploration,
                "diversity_adjustment_bps": 0,
                "adjusted_score_bps": total,
                "adjustment_snapshot": {
                    "novelty": novelty,
                    "repeat_exposure": repeat,
                    "popularity_suppression": popularity,
                    "exploration": exploration,
                    "deterministic_jitter": jitter,
                    "seed": seed,
                    # Adjustments never pretend to be compatibility.
                    "raw_compatibility_preserved": True,
                },
            }
        )
    return adjusted


def stable_sort(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic ordering: score, then confidence, then candidate-pair id."""
    return sorted(
        candidates,
        key=lambda item: (
            -int(item["adjusted_score_bps"]),
            -int(item.get("confidence_bps", 0)),
            str(item["candidate_pair_id"]),
        ),
    )


def diversify(
    candidates: list[dict[str, Any]],
    *,
    size: int,
    policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Maximal-marginal-relevance selection over already-qualified candidates.

    Diversification only reorders candidates that already passed eligibility,
    hard constraints and the score floors. It can never admit one that did not.
    """
    settings = policy or DIVERSIFICATION_POLICY
    if settings.get("may_bypass_hard_constraints"):
        raise ValueError("diversification may never bypass hard constraints")

    ordered = stable_sort(candidates)
    if size <= 0 or not ordered:
        return []

    lambda_weight = int(settings["lambda_bps"]) / 10000
    dimensions = list(settings["dimensions"])
    max_per_city = int(settings.get("max_per_city", 0)) or None

    selected: list[dict[str, Any]] = []
    remaining = list(ordered)
    city_counts: dict[str, int] = {}

    while remaining and len(selected) < size:
        best_index = 0
        best_value = float("-inf")
        for index, candidate in enumerate(remaining):
            city = str(candidate.get("city_code") or "")
            if max_per_city and city and city_counts.get(city, 0) >= max_per_city:
                continue
            relevance = int(candidate["adjusted_score_bps"]) / 10000
            redundancy = max(
                (similarity(candidate, chosen, dimensions) for chosen in selected),
                default=0.0,
            )
            value = lambda_weight * relevance - (1 - lambda_weight) * redundancy
            if value > best_value:
                best_value = value
                best_index = index
        if best_value == float("-inf"):
            # Every remaining candidate hit the per-city cap; relax the cap
            # rather than returning an under-filled batch.
            max_per_city = None
            continue
        chosen = remaining.pop(best_index)
        city = str(chosen.get("city_code") or "")
        if city:
            city_counts[city] = city_counts.get(city, 0) + 1
        original_rank = ordered.index(chosen)
        chosen["diversity_adjustment_bps"] = (original_rank - len(selected)) * 10
        selected.append(chosen)

    for position, candidate in enumerate(selected, start=1):
        candidate["final_rank"] = position
    return selected


def intra_list_diversity(
    selected: list[dict[str, Any]], dimensions: list[str] | None = None
) -> int:
    """Average pairwise dissimilarity of a produced list, in basis points."""
    dims = dimensions or list(DIVERSIFICATION_POLICY["dimensions"])
    if len(selected) < 2:
        return 10000
    pairs = 0
    total = 0.0
    for index, left in enumerate(selected):
        for right in selected[index + 1 :]:
            total += 1 - similarity(left, right, dims)
            pairs += 1
    return round(total / pairs * 10000) if pairs else 10000
