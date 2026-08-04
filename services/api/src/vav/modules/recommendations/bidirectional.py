"""Combine two directional scores into one bidirectional recommendation score.

A finds B suitable does not mean B wants to meet A. The combination is a
harmonic mean floored by the weaker direction, so a 95/25 split can never
present as a comfortable 60.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from vav.modules.recommendations.strategy import BIDIRECTIONAL_POLICY


def balance_score(a_to_b: int, b_to_a: int) -> int:
    """10000 when both directions agree, falling as the gap widens."""
    if a_to_b == 0 and b_to_a == 0:
        return 10000
    gap = abs(a_to_b - b_to_a)
    return max(0, 10000 - gap)


def harmonic_mean(a_to_b: int, b_to_a: int) -> int:
    if a_to_b <= 0 or b_to_a <= 0:
        return 0
    return round(2 * a_to_b * b_to_a / (a_to_b + b_to_a))


def combine(
    *,
    a_to_b: dict[str, Any],
    b_to_a: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce the combined score plus the symmetric explanation inputs."""
    settings = policy or BIDIRECTIONAL_POLICY
    a_score = int(a_to_b["total_score_bps"])
    b_score = int(b_to_a["total_score_bps"])
    minimum = min(a_score, b_score)
    balance = balance_score(a_score, b_score)

    mean = harmonic_mean(a_score, b_score)
    minimum_weight = int(settings["minimum_directional_weight_bps"])
    combined = round((mean * (10000 - minimum_weight) + minimum * minimum_weight) / 10000)

    # A large asymmetry is a warning, not something to average away.
    penalty_per_step = int(settings["balance_penalty_bps_per_10_percent_gap"])
    gap_steps = abs(a_score - b_score) // 1000
    combined = max(0, combined - gap_steps * penalty_per_step)

    a_features = {item["feature_code"]: item for item in a_to_b["feature_scores"]}
    b_features = {item["feature_code"]: item for item in b_to_a["feature_scores"]}
    mutual_strengths: list[str] = []
    asymmetric: list[str] = []
    for code, a_feature in a_features.items():
        b_feature = b_features.get(code)
        if b_feature is None:
            continue
        a_raw = a_feature["raw_match_bps"]
        b_raw = b_feature["raw_match_bps"]
        if a_raw is None or b_raw is None:
            continue
        if a_raw >= 6000 and b_raw >= 6000:
            mutual_strengths.append(code)
        elif abs(a_raw - b_raw) >= 4000:
            asymmetric.append(code)

    mutual_unknowns = sorted(
        set(a_to_b["missing_information"]) & set(b_to_a["missing_information"])
    )
    confidence = min(int(a_to_b["confidence_bps"]), int(b_to_a["confidence_bps"]))

    return {
        "user_a_to_b_score_bps": a_score,
        "user_b_to_a_score_bps": b_score,
        "combined_score_bps": combined,
        "minimum_directional_score_bps": minimum,
        "balance_score_bps": balance,
        "confidence_bps": confidence,
        "asymmetric_features": sorted(asymmetric),
        "mutual_strengths": sorted(mutual_strengths),
        "mutual_unknowns": mutual_unknowns,
        "policy_version": str(settings["policy_version"]),
    }


def meets_thresholds(
    result: dict[str, Any],
    *,
    minimum_directional_bps: int,
    minimum_bidirectional_bps: int,
    minimum_confidence_bps: int,
) -> tuple[bool, list[str]]:
    """Both directions must clear their floor, not just the combined score."""
    reasons: list[str] = []
    if result["minimum_directional_score_bps"] < minimum_directional_bps:
        reasons.append("directional_score_below_minimum")
    if result["combined_score_bps"] < minimum_bidirectional_bps:
        reasons.append("bidirectional_score_below_minimum")
    if result["confidence_bps"] < minimum_confidence_bps:
        reasons.append("confidence_below_minimum")
    return (not reasons, reasons)
