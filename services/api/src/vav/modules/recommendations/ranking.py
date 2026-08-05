"""Stable ranking, novelty, exposure adjustment and diversification.

Ranking never changes compatibility: adjustments are stored separately from the
bidirectional score so an adjusted position can always be explained, and the
whole procedure is deterministic for a fixed seed and candidate snapshot.
"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from vav.modules.recommendations.domain import clamp_bps

RANKING_POLICY_VERSION = "1.0.0"
DIVERSIFICATION_POLICY_VERSION = "1.0.0"


@dataclass(frozen=True)
class RankingCandidate:
    candidate_pair_id: UUID
    candidate_user_id: UUID
    base_score_bps: int
    minimum_directional_score_bps: int
    confidence_bps: int
    #: Days since the candidate profile was approved; ``None`` when unknown.
    profile_age_days: int | None = None
    #: Days since this viewer last saw the candidate; ``None`` when never.
    days_since_last_exposure: int | None = None
    #: How many viewers saw this profile today.
    shown_count_today: int = 0
    #: Whether the profile has never been exposed to anybody.
    never_exposed: bool = False
    city_code: str | None = None
    region_code: str | None = None
    interest_codes: tuple[str, ...] = ()
    lifestyle_codes: tuple[str, ...] = ()

    def diversity_signature(self) -> dict[str, Any]:
        return {
            "city_code": self.city_code,
            "region_code": self.region_code,
            "interest_codes": set(self.interest_codes),
            "lifestyle_codes": set(self.lifestyle_codes),
        }


@dataclass(frozen=True)
class RankedCandidate:
    candidate_pair_id: UUID
    candidate_user_id: UUID
    base_score_bps: int
    adjusted_score_bps: int
    novelty_adjustment_bps: int
    diversity_adjustment_bps: int
    exposure_adjustment_bps: int
    exploration_adjustment_bps: int
    final_rank: int
    adjustment_snapshot: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_pair_id": str(self.candidate_pair_id),
            "candidate_user_id": str(self.candidate_user_id),
            "base_score_bps": self.base_score_bps,
            "adjusted_score_bps": self.adjusted_score_bps,
            "novelty_adjustment_bps": self.novelty_adjustment_bps,
            "diversity_adjustment_bps": self.diversity_adjustment_bps,
            "exposure_adjustment_bps": self.exposure_adjustment_bps,
            "exploration_adjustment_bps": self.exploration_adjustment_bps,
            "final_rank": self.final_rank,
            "adjustment_snapshot": self.adjustment_snapshot,
        }


@dataclass(frozen=True)
class RankingPolicy:
    novelty_bonus_bps: int = 400
    never_exposed_bonus_bps: int = 300
    repeat_exposure_penalty_bps: int = 600
    popularity_penalty_bps: int = 500
    popularity_threshold: int = 30
    diversity_penalty_bps: int = 700
    exploration_slot_count: int = 2
    exploration_bonus_bps: int = 250
    new_profile_days: int = 14
    max_same_city_in_top: int = 4

    def as_dict(self) -> dict[str, Any]:
        return {
            "novelty_bonus_bps": self.novelty_bonus_bps,
            "never_exposed_bonus_bps": self.never_exposed_bonus_bps,
            "repeat_exposure_penalty_bps": self.repeat_exposure_penalty_bps,
            "popularity_penalty_bps": self.popularity_penalty_bps,
            "popularity_threshold": self.popularity_threshold,
            "diversity_penalty_bps": self.diversity_penalty_bps,
            "exploration_slot_count": self.exploration_slot_count,
            "exploration_bonus_bps": self.exploration_bonus_bps,
            "new_profile_days": self.new_profile_days,
            "max_same_city_in_top": self.max_same_city_in_top,
            "policy_version": RANKING_POLICY_VERSION,
            "diversification_policy_version": DIVERSIFICATION_POLICY_VERSION,
        }


def stable_tiebreak(seed: str, candidate_pair_id: UUID) -> str:
    """Deterministic tiebreaker so a refresh cannot reshuffle a batch."""
    material = f"{seed}:{candidate_pair_id}".encode()
    return hashlib.sha256(material).hexdigest()


def _novelty_adjustment(candidate: RankingCandidate, policy: RankingPolicy) -> int:
    bonus = 0
    if (
        candidate.profile_age_days is not None
        and candidate.profile_age_days <= policy.new_profile_days
    ):
        bonus += policy.novelty_bonus_bps
    if candidate.never_exposed:
        bonus += policy.never_exposed_bonus_bps
    return bonus


def _exposure_adjustment(candidate: RankingCandidate, policy: RankingPolicy) -> int:
    penalty = 0
    if candidate.days_since_last_exposure is not None:
        penalty -= policy.repeat_exposure_penalty_bps
    if candidate.shown_count_today >= policy.popularity_threshold:
        penalty -= policy.popularity_penalty_bps
    return penalty


def _similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    """Similarity between two already-qualified candidates, used only for spacing."""
    score = 0.0
    if left["city_code"] and left["city_code"] == right["city_code"]:
        score += 0.4
    elif left["region_code"] and left["region_code"] == right["region_code"]:
        score += 0.2
    for key, weight in (("interest_codes", 0.35), ("lifestyle_codes", 0.25)):
        first: set[str] = left[key]
        second: set[str] = right[key]
        if first and second:
            score += weight * len(first & second) / len(first | second)
    return min(1.0, score)


def rank_candidates(
    candidates: list[RankingCandidate],
    *,
    seed: str,
    limit: int,
    policy: RankingPolicy | None = None,
) -> list[RankedCandidate]:
    """Rank qualified candidates deterministically.

    Every candidate handed to this function has already passed eligibility,
    safety, privacy and both directions of the hard-constraint engine, so no
    adjustment here can ever create an ineligible recommendation.
    """
    active_policy = policy or RankingPolicy()
    if limit <= 0 or not candidates:
        return []

    prepared: list[tuple[RankingCandidate, int, int, int]] = []
    for candidate in candidates:
        novelty = _novelty_adjustment(candidate, active_policy)
        exposure = _exposure_adjustment(candidate, active_policy)
        pre_score = clamp_bps(candidate.base_score_bps + novelty + exposure)
        prepared.append((candidate, novelty, exposure, pre_score))

    remaining = sorted(
        prepared,
        key=lambda entry: (
            -entry[3],
            -entry[0].minimum_directional_score_bps,
            -entry[0].confidence_bps,
            stable_tiebreak(seed, entry[0].candidate_pair_id),
        ),
    )

    selected: list[RankedCandidate] = []
    chosen_signatures: list[dict[str, Any]] = []
    city_counts: dict[str, int] = {}
    exploration_used = 0

    while remaining and len(selected) < limit:
        best_index = 0
        best_value: float | None = None
        best_diversity = 0
        best_exploration = 0
        for index, (candidate, _novelty, _exposure, pre_score) in enumerate(remaining):
            diversity_penalty = 0
            if chosen_signatures:
                signature = candidate.diversity_signature()
                similarity = max(_similarity(signature, other) for other in chosen_signatures)
                diversity_penalty = -int(round(active_policy.diversity_penalty_bps * similarity))
                if (
                    candidate.city_code
                    and city_counts.get(candidate.city_code, 0)
                    >= active_policy.max_same_city_in_top
                ):
                    diversity_penalty -= active_policy.diversity_penalty_bps
            exploration_bonus = 0
            if exploration_used < active_policy.exploration_slot_count and (
                candidate.never_exposed or candidate.profile_age_days == 0
            ):
                exploration_bonus = active_policy.exploration_bonus_bps
            value = pre_score + diversity_penalty + exploration_bonus
            if best_value is None or value > best_value:
                best_value = value
                best_index = index
                best_diversity = diversity_penalty
                best_exploration = exploration_bonus

        candidate, novelty, exposure, pre_score = remaining.pop(best_index)
        if best_exploration:
            exploration_used += 1
        adjusted = clamp_bps(pre_score + best_diversity + best_exploration)
        selected.append(
            RankedCandidate(
                candidate_pair_id=candidate.candidate_pair_id,
                candidate_user_id=candidate.candidate_user_id,
                base_score_bps=candidate.base_score_bps,
                adjusted_score_bps=adjusted,
                novelty_adjustment_bps=novelty,
                diversity_adjustment_bps=best_diversity,
                exposure_adjustment_bps=exposure,
                exploration_adjustment_bps=best_exploration,
                final_rank=len(selected) + 1,
                adjustment_snapshot={
                    "pre_adjustment_score_bps": pre_score,
                    "seed": seed,
                    "policy": active_policy.as_dict(),
                    "shown_count_today": candidate.shown_count_today,
                    "days_since_last_exposure": candidate.days_since_last_exposure,
                    "profile_age_days": candidate.profile_age_days,
                },
            )
        )
        chosen_signatures.append(candidate.diversity_signature())
        if candidate.city_code:
            city_counts[candidate.city_code] = city_counts.get(candidate.city_code, 0) + 1

    return selected


def intra_list_diversity(ranked: list[RankingCandidate]) -> int:
    """Average pairwise dissimilarity of a produced list, in basis points."""
    if len(ranked) < 2:
        return 10_000
    signatures = [candidate.diversity_signature() for candidate in ranked]
    total = 0.0
    pairs = 0
    for index, left in enumerate(signatures):
        for right in signatures[index + 1 :]:
            total += 1 - _similarity(left, right)
            pairs += 1
    return clamp_bps(total / pairs * 10_000)
