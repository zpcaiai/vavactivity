"""Bidirectional compatibility composition.

A strong one-sided score must never hide an unacceptable reverse score, so the
composition uses the minimum direction and a geometric mean rather than a plain
average, and records the balance between the two directions.
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

from vav.modules.recommendations.domain import clamp_bps
from vav.modules.recommendations.scoring import DirectionalCompatibilityScore

BIDIRECTIONAL_POLICY_VERSION = "1.0.0"

#: Weights of the geometric mean and the weaker direction in the combination.
DEFAULT_GEOMETRIC_WEIGHT = 0.6
DEFAULT_MINIMUM_WEIGHT = 0.4


@dataclass(frozen=True)
class BidirectionalCompatibilityResult:
    user_a_to_b_score_bps: int
    user_b_to_a_score_bps: int
    combined_score_bps: int
    minimum_directional_score_bps: int
    balance_score_bps: int
    confidence_bps: int
    asymmetric_features: list[str]
    mutual_strengths: list[str]
    mutual_unknowns: list[str]
    meets_minimum_directional: bool
    meets_minimum_bidirectional: bool
    policy_version: str = BIDIRECTIONAL_POLICY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_a_to_b_score_bps": self.user_a_to_b_score_bps,
            "user_b_to_a_score_bps": self.user_b_to_a_score_bps,
            "combined_score_bps": self.combined_score_bps,
            "minimum_directional_score_bps": self.minimum_directional_score_bps,
            "balance_score_bps": self.balance_score_bps,
            "confidence_bps": self.confidence_bps,
            "asymmetric_features": self.asymmetric_features,
            "mutual_strengths": self.mutual_strengths,
            "mutual_unknowns": self.mutual_unknowns,
            "meets_minimum_directional": self.meets_minimum_directional,
            "meets_minimum_bidirectional": self.meets_minimum_bidirectional,
            "policy_version": self.policy_version,
        }


def balance_score(left: int, right: int) -> int:
    """10000 when both directions agree, 0 when they are maximally apart."""
    if left == 0 and right == 0:
        return 0
    return clamp_bps((1 - abs(left - right) / 10_000) * 10_000)


def combine(
    a_to_b: DirectionalCompatibilityScore,
    b_to_a: DirectionalCompatibilityScore,
    *,
    minimum_directional_bps: int,
    minimum_bidirectional_bps: int,
    geometric_weight: float = DEFAULT_GEOMETRIC_WEIGHT,
    minimum_weight: float = DEFAULT_MINIMUM_WEIGHT,
    asymmetry_penalty_threshold_bps: int = 3_000,
) -> BidirectionalCompatibilityResult:
    """Compose two directional scores into one bidirectional recommendation score."""
    left = clamp_bps(a_to_b.total_score_bps)
    right = clamp_bps(b_to_a.total_score_bps)
    weakest = min(left, right)
    geometric = int(round(sqrt(left * right)))
    balance = balance_score(left, right)

    combined = geometric_weight * geometric + minimum_weight * weakest
    if abs(left - right) > asymmetry_penalty_threshold_bps:
        # Strongly asymmetric pairs are suppressed rather than averaged away.
        combined *= 1 - min(0.3, (abs(left - right) - asymmetry_penalty_threshold_bps) / 20_000)

    combined_bps = clamp_bps(combined)
    confidence = clamp_bps(min(a_to_b.confidence_bps, b_to_a.confidence_bps))

    left_features = {score.feature_code: score for score in a_to_b.feature_scores}
    right_features = {score.feature_code: score for score in b_to_a.feature_scores}

    asymmetric = sorted(
        code
        for code, score in left_features.items()
        if code in right_features
        and score.information_available
        and right_features[code].information_available
        and abs(score.raw_match_bps - right_features[code].raw_match_bps) > 4_000
    )
    strengths = sorted(
        code
        for code, score in left_features.items()
        if code in right_features
        and score.information_available
        and right_features[code].information_available
        and score.raw_match_bps >= 7_000
        and right_features[code].raw_match_bps >= 7_000
    )
    unknowns = sorted(set(a_to_b.missing_information) & set(b_to_a.missing_information))

    return BidirectionalCompatibilityResult(
        user_a_to_b_score_bps=left,
        user_b_to_a_score_bps=right,
        combined_score_bps=combined_bps,
        minimum_directional_score_bps=weakest,
        balance_score_bps=balance,
        confidence_bps=confidence,
        asymmetric_features=asymmetric,
        mutual_strengths=strengths,
        mutual_unknowns=unknowns,
        meets_minimum_directional=weakest >= minimum_directional_bps,
        meets_minimum_bidirectional=combined_bps >= minimum_bidirectional_bps,
    )
