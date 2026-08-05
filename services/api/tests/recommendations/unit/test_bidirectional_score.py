"""Bidirectional composition, minimum thresholds and balance."""

from __future__ import annotations

from uuid import uuid4

from vav.modules.recommendations.bidirectional import balance_score, combine
from vav.modules.recommendations.scoring import DirectionalCompatibilityScore, FeatureScore


def _direction(total: int, confidence: int = 8_000, *, features=None, missing=None):
    return DirectionalCompatibilityScore(
        source_user_id=uuid4(),
        target_user_id=uuid4(),
        total_score_bps=total,
        confidence_bps=confidence,
        feature_scores=features or [],
        missing_information=missing or [],
        unknown_feature_count=len(missing or []),
    )


def _feature(code: str, raw: int, *, available: bool = True) -> FeatureScore:
    return FeatureScore(
        feature_code=code,
        raw_match_bps=raw,
        importance_weight=70,
        weighted_score=raw * 70,
        confidence_bps=10_000 if available else 0,
        information_available=available,
    )


def test_a_strong_one_sided_score_cannot_hide_a_weak_reverse_score() -> None:
    symmetric = combine(
        _direction(6_000),
        _direction(6_000),
        minimum_directional_bps=4_000,
        minimum_bidirectional_bps=5_000,
    )
    asymmetric = combine(
        _direction(9_500),
        _direction(2_500),
        minimum_directional_bps=4_000,
        minimum_bidirectional_bps=5_000,
    )
    assert asymmetric.combined_score_bps < symmetric.combined_score_bps
    assert not asymmetric.meets_minimum_directional
    # A plain average would have produced 6000 and hidden the mismatch.
    assert asymmetric.combined_score_bps < 6_000


def test_minimum_directional_and_bidirectional_thresholds_are_reported() -> None:
    result = combine(
        _direction(4_500),
        _direction(3_000),
        minimum_directional_bps=4_000,
        minimum_bidirectional_bps=5_000,
    )
    assert result.minimum_directional_score_bps == 3_000
    assert not result.meets_minimum_directional
    assert not result.meets_minimum_bidirectional


def test_balance_score_measures_symmetry() -> None:
    assert balance_score(5_000, 5_000) == 10_000
    assert balance_score(10_000, 0) == 0
    assert 0 < balance_score(8_000, 5_000) < 10_000


def test_confidence_is_the_weaker_of_the_two_directions() -> None:
    result = combine(
        _direction(7_000, 9_000),
        _direction(7_000, 4_000),
        minimum_directional_bps=4_000,
        minimum_bidirectional_bps=5_000,
    )
    assert result.confidence_bps == 4_000


def test_mutual_strengths_require_both_directions_to_agree() -> None:
    left = _direction(
        8_000, features=[_feature("interest_overlap", 9_000), _feature("language_overlap", 2_000)]
    )
    right = _direction(
        8_000, features=[_feature("interest_overlap", 9_500), _feature("language_overlap", 9_000)]
    )
    result = combine(left, right, minimum_directional_bps=4_000, minimum_bidirectional_bps=5_000)
    assert result.mutual_strengths == ["interest_overlap"]
    assert "language_overlap" in result.asymmetric_features


def test_mutual_unknowns_are_the_intersection_of_both_gaps() -> None:
    left = _direction(7_000, missing=["desire_children_alignment", "education_alignment"])
    right = _direction(7_000, missing=["desire_children_alignment"])
    result = combine(left, right, minimum_directional_bps=4_000, minimum_bidirectional_bps=5_000)
    assert result.mutual_unknowns == ["desire_children_alignment"]


def test_composition_is_symmetric_in_the_score_it_produces() -> None:
    forward = combine(
        _direction(7_000), _direction(5_000), minimum_directional_bps=0, minimum_bidirectional_bps=0
    )
    reverse = combine(
        _direction(5_000), _direction(7_000), minimum_directional_bps=0, minimum_bidirectional_bps=0
    )
    assert forward.combined_score_bps == reverse.combined_score_bps
    assert forward.policy_version == reverse.policy_version
