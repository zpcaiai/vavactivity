"""Explanation generation, privacy limits and the AI-rewrite boundary."""

from __future__ import annotations

from uuid import uuid4

import pytest

from vav.modules.recommendations.bidirectional import combine
from vav.modules.recommendations.explanations import (
    EXPLANATION_POLICY_VERSION,
    apply_optional_rewrite,
    assert_safe,
    build_explanation,
    member_view,
)
from vav.modules.recommendations.scoring import DirectionalCompatibilityScore, FeatureScore


def _feature(code: str, raw: int, *, available: bool = True, explanation: str | None = None):
    return FeatureScore(
        feature_code=code,
        raw_match_bps=raw,
        importance_weight=100,
        weighted_score=raw * 100,
        confidence_bps=10_000 if available else 0,
        explanation_code=explanation,
        information_available=available,
    )


def _direction(features, missing=None, satisfied=None):
    return DirectionalCompatibilityScore(
        source_user_id=uuid4(),
        target_user_id=uuid4(),
        total_score_bps=7_500,
        confidence_bps=8_000,
        feature_scores=features,
        missing_information=missing or [],
        unknown_feature_count=len(missing or []),
        satisfied_preferences=satisfied or [],
    )


def _explanation(locale: str = "zh-CN"):
    viewer = _direction(
        [
            _feature("interest_overlap", 9_000, explanation="shared_interests"),
            _feature("language_overlap", 9_000, explanation="shared_languages"),
            _feature("location_compatibility", 3_000, explanation="location_compatible"),
            _feature("desire_children_alignment", 0, available=False),
        ],
        missing=["desire_children_alignment"],
        satisfied=["language_overlap"],
    )
    candidate = _direction(
        [
            _feature("interest_overlap", 9_500, explanation="shared_interests"),
            _feature("language_overlap", 9_200, explanation="shared_languages"),
            _feature("location_compatibility", 9_000, explanation="location_compatible"),
        ],
        missing=["desire_children_alignment"],
    )
    composed = combine(viewer, candidate, minimum_directional_bps=0, minimum_bidirectional_bps=0)
    return build_explanation(viewer_score=viewer, bidirectional=composed, locale=locale)


def test_explanations_come_from_evaluated_features() -> None:
    explanation = _explanation()
    codes = {item.explanation_code for item in explanation.mutual_strengths}
    assert "shared_interests" in codes
    for item in explanation.mutual_strengths:
        assert item.source_feature_codes


def test_information_gaps_are_shown_to_the_member() -> None:
    explanation = _explanation()
    assert any(
        item.explanation_code == "information_gap:desire_children_alignment"
        for item in explanation.information_gaps
    )


def test_differences_become_topics_to_explore() -> None:
    explanation = _explanation()
    assert any(
        item.explanation_code.startswith("difference:") for item in explanation.topics_to_explore
    )


def test_explanations_never_expose_scores_or_guarantees() -> None:
    explanation = _explanation()
    serialised = str(member_view(explanation.as_dict()))
    assert "%" not in serialised
    assert "bps" not in serialised
    assert "soulmate" not in serialised.lower()
    assert explanation.caveat
    assert explanation.explanation_policy_version == EXPLANATION_POLICY_VERSION


def test_a_forbidden_claim_fails_closed() -> None:
    explanation = _explanation()
    broken = type(explanation)(
        summary="你们是灵魂伴侣",
        mutual_strengths=explanation.mutual_strengths,
        relevant_preferences=explanation.relevant_preferences,
        topics_to_explore=explanation.topics_to_explore,
        information_gaps=explanation.information_gaps,
        caveat=explanation.caveat,
    )
    with pytest.raises(ValueError):
        assert_safe(broken)


def test_locales_produce_localised_text() -> None:
    assert _explanation("en").summary != _explanation("zh-CN").summary


def test_ai_rewrite_is_rejected_when_it_adds_or_changes_claims() -> None:
    explanation = _explanation()
    good = apply_optional_rewrite(
        explanation,
        {
            "summary": "你们在几个方面比较接近。",
            "mutual_strengths": [
                {"explanation_code": item.explanation_code, "display_text": "你们有共同的兴趣。"}
                for item in explanation.mutual_strengths
            ],
        },
    )
    assert good.generated_by == "ai_rewrite"

    invented = apply_optional_rewrite(
        explanation,
        {
            "summary": "保证你们会结婚",
            "mutual_strengths": [
                {"explanation_code": item.explanation_code, "display_text": "x"}
                for item in explanation.mutual_strengths
            ],
        },
    )
    assert invented.generated_by == "deterministic_template"

    extra_item = apply_optional_rewrite(
        explanation,
        {
            "summary": "ok",
            "mutual_strengths": [{"explanation_code": "made_up", "display_text": "x"}],
        },
    )
    assert extra_item.generated_by == "deterministic_template"
    assert apply_optional_rewrite(explanation, None) is explanation


def test_relaxation_notices_are_disclosed() -> None:
    viewer = _direction([_feature("interest_overlap", 9_000, explanation="shared_interests")])
    composed = combine(viewer, viewer, minimum_directional_bps=0, minimum_bidirectional_bps=0)
    explanation = build_explanation(
        viewer_score=viewer,
        bidirectional=composed,
        relaxed_criteria=["viewer_to_candidate:city_code"],
    )
    assert explanation.relaxation_notices
    assert "city_code" in explanation.relaxation_notices[0]


def test_member_view_strips_internal_numbers_but_keeps_the_text() -> None:
    explanation = _explanation()
    view = member_view(explanation.as_dict())
    serialised = str(view)
    assert "confidence_bps" not in serialised
    assert "disclosure_level" not in serialised
    assert view["caveat"] == explanation.caveat
    assert view["mutual_strengths"][0]["display_text"]
