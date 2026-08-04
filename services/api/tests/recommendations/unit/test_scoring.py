"""Directional soft scoring."""

# ruff: noqa: E501
from __future__ import annotations

import pytest

from vav.common.exceptions import VavError
from vav.modules.recommendations import scoring
from vav.modules.recommendations.strategy import IMPORTANCE_WEIGHTS

from ..helpers import criterion, projection


def _score(**kwargs):  # type: ignore[no-untyped-def]
    defaults = {
        "source_projection": projection(),
        "target_projection": projection(
            gender_code="male", eligible_partner_gender_codes=["female"]
        ),
        "source_criteria": [],
    }
    return scoring.score_direction(**{**defaults, **kwargs})


# --- scoring functions ----------------------------------------------------


def test_exact_match_handles_scalars_and_accepted_lists() -> None:
    assert scoring.exact_match("a", "a") == 10000
    assert scoring.exact_match("a", "b") == 0
    assert scoring.exact_match(["a", "b"], "b") == 10000
    assert scoring.exact_match(["a", "b"], "c") == 0


def test_a_missing_value_is_unknown_rather_than_zero() -> None:
    assert scoring.exact_match(None, "a") is None
    assert scoring.exact_match("a", None) is None
    assert scoring.set_overlap([], ["a"]) is None
    assert scoring.range_match({"minimum": 1, "maximum": 2}, None) is None
    assert scoring.ordered_distance(None, 3, maximum_distance=4) is None


def test_set_overlap_is_symmetric_and_normalised() -> None:
    assert scoring.set_overlap(["a", "b"], ["a", "b"]) == 10000
    assert scoring.set_overlap(["a", "b"], ["c", "d"]) == 0
    assert scoring.set_overlap(["a", "b"], ["b", "c"]) == scoring.set_overlap(
        ["b", "c"], ["a", "b"]
    )


def test_ordered_distance_decays_with_the_gap() -> None:
    assert scoring.ordered_distance(5, 5, maximum_distance=4) == 10000
    assert scoring.ordered_distance(5, 3, maximum_distance=4) == 5000
    assert scoring.ordered_distance(5, 1, maximum_distance=4) == 0
    # Beyond the maximum the score floors instead of going negative.
    assert scoring.ordered_distance(5, 0, maximum_distance=4) == 0


def test_range_match_rewards_centrality_not_bare_membership() -> None:
    band = {"minimum": 30, "maximum": 40}
    assert scoring.range_match(band, 35) == 10000
    assert scoring.range_match(band, 30) == 0
    assert scoring.range_match(band, 41) == 0
    assert 0 < scoring.range_match(band, 32) < 10000  # type: ignore[operator]
    assert scoring.range_match({"minimum": 33, "maximum": 33}, 33) == 10000
    assert scoring.range_match({"minimum": 40, "maximum": 30}, 35) is None


def test_geographic_compatibility_uses_coarse_codes_and_both_sides_openness() -> None:
    here = {
        "city_code": "shanghai",
        "region_code": "east",
        "country_code": "CN",
        "relocation_willingness": "same_country",
    }
    assert scoring.geographic_compatibility(here, dict(here)) == 10000

    same_region = {**here, "city_code": "suzhou"}
    same_country = {**here, "city_code": "chengdu", "region_code": "west"}
    assert (
        10000
        > scoring.geographic_compatibility(here, same_region)  # type: ignore[operator]
        > scoring.geographic_compatibility(here, same_country)  # type: ignore[operator]
    )

    # A person unwilling to move drags the joint openness down for both sides.
    rooted = {**same_country, "relocation_willingness": "not_willing"}
    assert scoring.geographic_compatibility(here, rooted) < scoring.geographic_compatibility(  # type: ignore[operator]
        here, same_country
    )
    assert scoring.geographic_compatibility({"country_code": None}, here) is None


def test_readiness_measures_available_detail_only() -> None:
    assert scoring.readiness({}) == 0
    assert scoring.readiness(projection()) == 10000


# --- directional scoring --------------------------------------------------


def test_a_well_matched_pair_scores_highly_and_confidently() -> None:
    result = _score(
        source_criteria=[criterion("age_range", "range", {"minimum": 25, "maximum": 45})]
    )
    assert result["total_score_bps"] >= 7000
    assert result["confidence_bps"] >= 5000
    assert result["missing_information"] == []


def test_a_feature_with_nothing_to_compare_is_unknown_not_scored() -> None:
    # Nobody stated an age preference, so age centrality has no basis at all.
    result = _score()
    assert result["missing_information"] == ["age_preference_centrality"]


def test_scores_stay_inside_basis_point_bounds() -> None:
    result = _score()
    assert 0 <= result["total_score_bps"] <= 10000
    assert 0 <= result["confidence_bps"] <= 10000
    for feature in result["feature_scores"]:
        raw = feature["raw_match_bps"]
        assert raw is None or 0 <= raw <= 10000


def test_missing_data_lowers_confidence_instead_of_scoring_zero() -> None:
    rich = _score()
    sparse = _score(
        target_projection=projection(
            gender_code="male",
            eligible_partner_gender_codes=["female"],
            faith_codes=[],
            lifestyle_codes=[],
            language_codes=[],
            relationship_intent=None,
            marital_status_code=None,
        )
    )
    assert sparse["confidence_bps"] < rich["confidence_bps"]
    assert sparse["missing_information"]
    assert sparse["missingness_policy"] == "ignore_and_lower_confidence"
    # Nothing was scored as a zero simply because it was blank.
    for feature in sparse["feature_scores"]:
        if feature["feature_code"] in sparse["missing_information"]:
            assert feature["raw_match_bps"] is None


def test_one_lucky_field_can_never_look_like_a_confident_perfect_match() -> None:
    lone = _score(
        target_projection=projection(
            gender_code="male",
            eligible_partner_gender_codes=["female"],
            faith_codes=[],
            lifestyle_codes=[],
            language_codes=[],
            relationship_intent=None,
            marital_status_code=None,
            children_status_code=None,
            city_code=None,
            region_code=None,
            country_code=None,
            age_years=None,
        )
    )
    if lone["total_score_bps"] >= 9000:
        assert lone["confidence_bps"] < 5000


def test_member_importance_overrides_the_platform_default_weight() -> None:
    baseline = _score()
    demoted = _score(
        source_criteria=[
            criterion("faith_status_code", "in", ["believer_baptized"], importance="nice_to_have")
        ]
    )
    faith_weight = next(
        item["importance_weight"]
        for item in demoted["feature_scores"]
        if item["feature_code"] == "faith_status_alignment"
    )
    assert faith_weight == IMPORTANCE_WEIGHTS["nice_to_have"]
    assert demoted["declared_weight"] < baseline["declared_weight"]


def test_no_preference_removes_a_feature_from_the_soft_mix() -> None:
    result = _score(
        source_criteria=[
            criterion("faith_status_code", "in", ["believer_baptized"], importance="no_preference")
        ]
    )
    codes = {item["feature_code"] for item in result["feature_scores"]}
    assert "faith_status_alignment" not in codes


def test_required_is_a_hard_constraint_and_is_not_double_counted_as_a_weight() -> None:
    assert "required" not in IMPORTANCE_WEIGHTS
    result = _score(
        source_criteria=[
            criterion(
                "faith_status_code",
                "in",
                ["believer_baptized"],
                importance="required",
                hard=True,
            )
        ]
    )
    faith_weight = next(
        item["importance_weight"]
        for item in result["feature_scores"]
        if item["feature_code"] == "faith_status_alignment"
    )
    # Falls back to the transparent platform default rather than an inflated one.
    assert faith_weight == 90


def test_tuning_adjustments_shift_weights_without_ever_going_negative() -> None:
    result = _score(weight_adjustments={"faith_status_alignment": -1000})
    codes = {item["feature_code"] for item in result["feature_scores"]}
    assert "faith_status_alignment" not in codes
    for item in result["feature_scores"]:
        assert item["importance_weight"] >= 0


def test_prohibited_signals_are_rejected_before_anything_is_scored() -> None:
    manifest = [
        {
            "feature_code": "photo_attractiveness",
            "feature_group": "appearance",
            "scoring_function_code": "exact_match",
            "projection_field": "city_code",
            "preference_criterion": None,
            "default_weight": 50,
            "explainable": True,
            "user_configurable": True,
            "explanation_code": "x",
            "sensitivity": "confidential",
            "options": {},
        }
    ]
    with pytest.raises(VavError) as excinfo:
        _score(feature_manifest=manifest)
    assert excinfo.value.code == "RECOMMENDATION_PROHIBITED_SIGNAL"


def test_scoring_is_deterministic_for_identical_inputs() -> None:
    first = _score()
    second = _score()
    assert first == second


def test_the_scoring_policy_version_travels_with_every_score() -> None:
    assert _score()["scoring_policy_version"]
