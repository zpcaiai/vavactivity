"""Bidirectional score combination."""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from vav.modules.recommendations import bidirectional


def direction(
    score: int,
    *,
    confidence: int = 8000,
    features: dict[str, int | None] | None = None,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "total_score_bps": score,
        "confidence_bps": confidence,
        "feature_scores": [
            {"feature_code": code, "raw_match_bps": raw} for code, raw in (features or {}).items()
        ],
        "missing_information": missing or [],
    }


def test_two_strong_directions_combine_into_a_strong_score() -> None:
    result = bidirectional.combine(a_to_b=direction(9000), b_to_a=direction(9000))
    assert result["combined_score_bps"] >= 8500
    assert result["balance_score_bps"] == 10000


def test_a_lopsided_pair_never_presents_as_comfortably_average() -> None:
    lopsided = bidirectional.combine(a_to_b=direction(9500), b_to_a=direction(2500))
    arithmetic_mean = (9500 + 2500) // 2
    assert lopsided["combined_score_bps"] < arithmetic_mean
    assert lopsided["minimum_directional_score_bps"] == 2500
    assert lopsided["balance_score_bps"] < 4000


def test_the_combination_is_symmetric() -> None:
    forward = bidirectional.combine(a_to_b=direction(8000), b_to_a=direction(4000))
    reverse = bidirectional.combine(a_to_b=direction(4000), b_to_a=direction(8000))
    assert forward["combined_score_bps"] == reverse["combined_score_bps"]
    assert forward["balance_score_bps"] == reverse["balance_score_bps"]


def test_one_dead_direction_kills_the_pair() -> None:
    result = bidirectional.combine(a_to_b=direction(10000), b_to_a=direction(0))
    assert result["combined_score_bps"] == 0


def test_the_combined_score_stays_inside_the_two_directions() -> None:
    result = bidirectional.combine(a_to_b=direction(8000), b_to_a=direction(6000))
    assert result["combined_score_bps"] <= 8000
    assert 0 <= result["combined_score_bps"] <= 10000


def test_confidence_is_the_weaker_of_the_two_directions() -> None:
    result = bidirectional.combine(
        a_to_b=direction(8000, confidence=9500), b_to_a=direction(8000, confidence=3000)
    )
    assert result["confidence_bps"] == 3000


def test_mutual_strengths_need_both_sides_to_agree() -> None:
    result = bidirectional.combine(
        a_to_b=direction(8000, features={"shared": 9000, "onesided": 9500, "weak": 1000}),
        b_to_a=direction(8000, features={"shared": 8000, "onesided": 1000, "weak": 2000}),
    )
    assert result["mutual_strengths"] == ["shared"]
    assert result["asymmetric_features"] == ["onesided"]


def test_an_unknown_on_either_side_is_neither_a_strength_nor_a_difference() -> None:
    result = bidirectional.combine(
        a_to_b=direction(8000, features={"quiet": None}),
        b_to_a=direction(8000, features={"quiet": 9000}),
    )
    assert result["mutual_strengths"] == []
    assert result["asymmetric_features"] == []


def test_mutual_unknowns_are_the_intersection_not_the_union() -> None:
    result = bidirectional.combine(
        a_to_b=direction(8000, missing=["a", "b"]),
        b_to_a=direction(8000, missing=["b", "c"]),
    )
    assert result["mutual_unknowns"] == ["b"]


def test_both_directions_must_clear_their_own_floor() -> None:
    result = bidirectional.combine(a_to_b=direction(9500), b_to_a=direction(2000))
    passed, reasons = bidirectional.meets_thresholds(
        result,
        minimum_directional_bps=3000,
        minimum_bidirectional_bps=3000,
        minimum_confidence_bps=2000,
    )
    assert not passed
    assert "directional_score_below_minimum" in reasons


def test_low_confidence_alone_can_hold_a_pair_back() -> None:
    result = bidirectional.combine(
        a_to_b=direction(9000, confidence=800), b_to_a=direction(9000, confidence=800)
    )
    passed, reasons = bidirectional.meets_thresholds(
        result,
        minimum_directional_bps=3000,
        minimum_bidirectional_bps=3000,
        minimum_confidence_bps=2000,
    )
    assert not passed
    assert reasons == ["confidence_below_minimum"]


def test_a_balanced_qualified_pair_passes_every_threshold() -> None:
    result = bidirectional.combine(a_to_b=direction(8200), b_to_a=direction(7900))
    passed, reasons = bidirectional.meets_thresholds(
        result,
        minimum_directional_bps=3000,
        minimum_bidirectional_bps=3000,
        minimum_confidence_bps=2000,
    )
    assert passed
    assert reasons == []


def test_harmonic_mean_and_balance_helpers_behave() -> None:
    assert bidirectional.harmonic_mean(0, 9000) == 0
    assert bidirectional.harmonic_mean(6000, 6000) == 6000
    assert bidirectional.harmonic_mean(9000, 3000) < 6000
    assert bidirectional.balance_score(0, 0) == 10000
    assert bidirectional.balance_score(10000, 0) == 0
