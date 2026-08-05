"""Directional soft scoring, weights, missingness and determinism."""

from __future__ import annotations

from uuid import uuid4

from vav.modules.recommendations.domain import MissingnessPolicy
from vav.modules.recommendations.scoring import (
    IMPORTANCE_WEIGHTS,
    importance_weight,
    score_direction,
)

from ..helpers import criterion, projection

VIEWER = uuid4()
CANDIDATE = uuid4()


def _score(viewer_criteria, candidate_payload=None, **kwargs):
    return score_direction(
        source_user_id=VIEWER,
        target_user_id=CANDIDATE,
        viewer_projection=projection(),
        candidate_projection=candidate_payload
        or projection(gender_code="male", eligible_partner_gender_codes=["female"]),
        viewer_criteria=viewer_criteria,
        **kwargs,
    )


def test_scores_are_always_basis_points() -> None:
    result = _score([])
    assert 0 <= result.total_score_bps <= 10_000
    assert 0 <= result.confidence_bps <= 10_000


def test_member_importance_drives_the_weight() -> None:
    assert importance_weight("very_important") == 100
    assert importance_weight("important") == 70
    assert importance_weight("nice_to_have") == 35
    assert importance_weight("no_preference") == 0
    assert importance_weight(None) == 0
    assert IMPORTANCE_WEIGHTS["required"] == 0


def test_required_criteria_are_not_counted_twice_as_soft_preferences() -> None:
    result = _score([criterion("relationship_intent", "equals", "marriage_oriented", hard=True)])
    intent = next(
        item
        for item in result.feature_scores
        if item.feature_code == "relationship_intent_alignment"
    )
    assert intent.hard_constraint_satisfied
    assert intent.importance_weight == 0
    assert intent.weighted_score == 0


def test_missing_information_lowers_confidence_instead_of_scoring_zero() -> None:
    complete = _score(
        [criterion("smoking_status_code", "in", ["never"], importance="very_important")]
    )
    sparse = _score(
        [criterion("smoking_status_code", "in", ["never"], importance="very_important")],
        candidate_payload=projection(
            gender_code="male", eligible_partner_gender_codes=["female"], lifestyle_codes=[]
        ),
    )
    assert sparse.confidence_bps < complete.confidence_bps
    assert "smoking_alignment" in sparse.missing_information
    missing = next(
        item for item in sparse.feature_scores if item.feature_code == "smoking_alignment"
    )
    assert missing.weighted_score == 0
    assert not missing.information_available


def test_a_single_matching_field_cannot_produce_a_confident_perfect_score() -> None:
    result = score_direction(
        source_user_id=VIEWER,
        target_user_id=CANDIDATE,
        viewer_projection=projection(
            faith_codes=[], language_codes=[], lifestyle_codes=[], relationship_intent=None
        ),
        candidate_projection=projection(
            gender_code="male",
            eligible_partner_gender_codes=["female"],
            faith_codes=[],
            language_codes=[],
            lifestyle_codes=[],
            relationship_intent=None,
        ),
        viewer_criteria=[criterion("city_code", "equals", "shanghai", importance="very_important")],
    )
    assert result.confidence_bps < 6_000


def test_neutral_and_penalty_missingness_policies_are_supported() -> None:
    sparse = projection(
        gender_code="male", eligible_partner_gender_codes=["female"], lifestyle_codes=[]
    )
    neutral = _score(
        [criterion("smoking_status_code", "in", ["never"])],
        candidate_payload=sparse,
        missingness_policy=MissingnessPolicy.NEUTRAL_SCORE.value,
    )
    penalty = _score(
        [criterion("smoking_status_code", "in", ["never"])],
        candidate_payload=sparse,
        missingness_policy=MissingnessPolicy.CONFIGURED_PENALTY.value,
        missing_penalty_bps=1_000,
    )
    assert neutral.total_score_bps >= penalty.total_score_bps


def test_the_same_inputs_always_produce_the_same_score() -> None:
    criteria = [
        criterion("faith_status_code", "in", ["believer_baptized"], importance="very_important")
    ]
    first = _score(criteria)
    second = _score(criteria)
    assert first.total_score_bps == second.total_score_bps
    assert first.confidence_bps == second.confidence_bps


def test_scoring_records_its_policy_and_registry_versions() -> None:
    result = _score([])
    assert result.scoring_policy_version
    assert result.feature_registry_version


def test_member_tuning_is_bounded() -> None:
    boosted = _score(
        [criterion("interest_overlap", "contains_any", ["reading"])],
        tuning_adjustments={"interest_overlap": 99.0},
    )
    for score in boosted.feature_scores:
        assert score.importance_weight <= 150
