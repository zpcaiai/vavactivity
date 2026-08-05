"""Feature registry integrity and scoring-function behaviour."""

from __future__ import annotations

from vav.modules.recommendations.domain import PROHIBITED_SCORING_SIGNALS
from vav.modules.recommendations.features import (
    FEATURE_DEFINITIONS,
    FEATURES_BY_CODE,
    apply_scoring_function,
    assert_registry_is_clean,
    extract_value,
    feature_manifest,
    score_exact_match,
    score_geographic_compatibility,
    score_jaccard,
    score_ordered_distance,
    score_range_match,
    score_set_overlap,
)

from ..helpers import projection


def test_registry_contains_no_prohibited_signal() -> None:
    assert_registry_is_clean()
    codes = {definition.feature_code for definition in FEATURE_DEFINITIONS}
    assert not codes & PROHIBITED_SCORING_SIGNALS
    for prohibited in ("photo_attractiveness", "income_inference", "payment_capacity"):
        assert prohibited not in codes


def test_manifest_is_versioned_and_serialisable() -> None:
    manifest = feature_manifest()
    assert len(manifest) == len(FEATURE_DEFINITIONS)
    for entry in manifest:
        assert entry["semantic_version"]
        assert entry["feature_group"]
        assert entry["scoring_function_code"]


def test_exact_match_scores_are_bounded() -> None:
    assert score_exact_match("a", "a") == 10_000
    assert score_exact_match("a", "b") == 0
    assert score_exact_match(["a", "b"], "b") == 10_000


def test_set_overlap_normalises_by_the_smaller_set() -> None:
    assert score_set_overlap(["a"], ["a", "b", "c"]) == 10_000
    assert score_set_overlap(["a", "b"], ["b", "c"]) == 5_000
    assert score_set_overlap([], ["a"]) == 0


def test_jaccard_penalises_disjoint_interests() -> None:
    assert score_jaccard(["a", "b"], ["a", "b"]) == 10_000
    assert score_jaccard(["a"], ["b"]) == 0


def test_ordered_distance_decays_with_distance() -> None:
    assert score_ordered_distance(5, 5, scale=4) == 10_000
    assert score_ordered_distance(5, 4, scale=4) == 7_500
    assert score_ordered_distance(5, 1, scale=4) == 0


def test_range_match_rewards_centrality_and_rejects_outside_values() -> None:
    assert score_range_match({"minimum": 30, "maximum": 40}, 35) == 10_000
    assert score_range_match({"minimum": 30, "maximum": 40}, 40) == 0
    assert score_range_match({"minimum": 30, "maximum": 40}, 45) == 0


def test_geographic_compatibility_uses_codes_and_relocation_only() -> None:
    same_city, reason = score_geographic_compatibility(
        projection(), projection(city_code="shanghai")
    )
    assert same_city == 10_000 and reason == "same_city"

    cross, reason = score_geographic_compatibility(
        projection(city_code="a", region_code="x", country_code="CN"),
        projection(
            city_code="b", region_code="y", country_code="US", relocation_willingness="willing"
        ),
    )
    assert reason == "cross_border_with_relocation"
    assert 0 < cross < 10_000


def test_projection_extraction_handles_prefixed_codes_and_unknowns() -> None:
    payload = projection()
    assert extract_value(payload, "smoking_status_code") == "never"
    assert extract_value(payload, "leisure_interest_codes") == ["reading", "music"]
    assert extract_value(payload, "marriage_faith_importance") == 5
    assert extract_value(payload, "daily_schedule_code") == "standard"
    assert extract_value(projection(lifestyle_codes=[]), "smoking_status_code") is None
    assert extract_value(projection(children_status_code=None), "has_children") is None


def test_every_feature_scores_within_the_basis_point_range() -> None:
    viewer = projection()
    candidate = projection(gender_code="male", eligible_partner_gender_codes=["female"])
    for definition in FEATURE_DEFINITIONS:
        lookup = definition.criterion_code or definition.similarity_code
        desired = extract_value(viewer, lookup) if lookup else None
        actual = extract_value(candidate, lookup) if lookup else None
        score, _code = apply_scoring_function(
            definition,
            desired=desired,
            actual=actual,
            viewer_projection=viewer,
            candidate_projection=candidate,
        )
        assert 0 <= score <= 10_000, definition.feature_code
    assert FEATURES_BY_CODE["profile_readiness"].confidence_only
