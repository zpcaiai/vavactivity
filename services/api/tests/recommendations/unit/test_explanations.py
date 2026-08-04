"""Recommendation explanations."""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any

import pytest

from vav.modules.recommendations import explanations
from vav.modules.recommendations.strategy import EXPLANATION_POLICY, FEATURE_MANIFEST

from ..helpers import criterion


def viewer_score(**features: int | None) -> dict[str, Any]:
    return {
        "feature_scores": [
            {"feature_code": code, "raw_match_bps": raw, "confidence_bps": 9000}
            for code, raw in features.items()
        ],
        "missing_information": [code for code, raw in features.items() if raw is None],
    }


def bidirectional(
    *,
    mutual: list[str] | None = None,
    asymmetric: list[str] | None = None,
    unknowns: list[str] | None = None,
    confidence: int = 8000,
) -> dict[str, Any]:
    return {
        "mutual_strengths": mutual or [],
        "asymmetric_features": asymmetric or [],
        "mutual_unknowns": unknowns or [],
        "confidence_bps": confidence,
    }


def test_a_strong_pair_gets_mutual_strengths_and_a_caveat() -> None:
    result = explanations.build(
        viewer_score=viewer_score(faith_status_alignment=9000),
        bidirectional=bidirectional(mutual=["faith_status_alignment", "language_overlap"]),
        viewer_criteria=[],
    )
    codes = [item["explanation_code"] for item in result["mutual_strengths"]]
    assert "shared_faith_status" in codes
    assert result["caveat"] == EXPLANATION_POLICY["caveat"]
    assert result["summary"]


def test_every_sentence_comes_from_an_approved_template() -> None:
    approved = set(explanations.STRENGTH_TEMPLATES.values())
    result = explanations.build(
        viewer_score=viewer_score(faith_status_alignment=9000),
        bidirectional=bidirectional(mutual=["faith_status_alignment"]),
        viewer_criteria=[],
    )
    for item in result["mutual_strengths"]:
        assert item["display_text"] in approved


def test_only_the_viewers_own_stated_preferences_are_echoed_back() -> None:
    result = explanations.build(
        viewer_score=viewer_score(faith_status_alignment=9500, interest_overlap=9500),
        bidirectional=bidirectional(),
        viewer_criteria=[criterion("faith_status_code", "in", ["believer_baptized"])],
    )
    codes = [item["explanation_code"] for item in result["relevant_preferences"]]
    assert codes == ["preference_met_faith_status_code"]
    assert "（这是你标记为重要的条件）" in result["relevant_preferences"][0]["display_text"]


def test_the_other_persons_criteria_and_score_are_never_disclosed() -> None:
    result = explanations.build(
        viewer_score=viewer_score(faith_status_alignment=9000),
        bidirectional=bidirectional(mutual=["faith_status_alignment"]),
        viewer_criteria=[criterion("faith_status_code", "in", ["believer_baptized"])],
    )
    explanations.assert_safe(result)
    serialised = str(result)
    for forbidden in ("candidate_to_viewer", "user_b_to_a", "success_probability", "rank_position"):
        assert forbidden not in serialised


def test_a_leaking_explanation_fails_closed() -> None:
    with pytest.raises(ValueError):
        explanations.assert_safe({"summary": "对方的 success_probability 是 88%"})


def test_unexplainable_features_never_reach_a_member() -> None:
    hidden = [feature["feature_code"] for feature in FEATURE_MANIFEST if not feature["explainable"]]
    assert "profile_readiness" in hidden
    result = explanations.build(
        viewer_score=viewer_score(profile_readiness=10000),
        bidirectional=bidirectional(mutual=hidden),
        viewer_criteria=[],
    )
    assert result["mutual_strengths"] == []


def test_gaps_are_phrased_without_blaming_either_person() -> None:
    result = explanations.build(
        viewer_score=viewer_score(),
        bidirectional=bidirectional(unknowns=["interest_overlap", "language_overlap"]),
        viewer_criteria=[],
    )
    assert result["information_gaps"]
    for item in result["information_gaps"]:
        assert item["display_text"] in explanations.GAP_TEMPLATES.values()
        assert "不合格" not in item["display_text"]
        assert "差" not in item["display_text"]


def test_differences_become_topics_to_explore_rather_than_verdicts() -> None:
    result = explanations.build(
        viewer_score=viewer_score(),
        bidirectional=bidirectional(asymmetric=["geographic_compatibility"]),
        viewer_criteria=[],
    )
    assert (
        result["topics_to_explore"][0]["display_text"] in explanations.DIFFERENCE_TEMPLATES.values()
    )


def test_an_applied_relaxation_is_disclosed_to_the_viewer() -> None:
    result = explanations.build(
        viewer_score=viewer_score(),
        bidirectional=bidirectional(),
        viewer_criteria=[],
        relaxations_applied=["city_code"],
    )
    texts = [item["display_text"] for item in result["topics_to_explore"]]
    assert any("放宽" in text and "city_code" in text for text in texts)


def test_each_section_is_capped_so_a_card_stays_readable() -> None:
    maximum = int(EXPLANATION_POLICY["max_items_per_section"])
    every_feature = [feature["feature_code"] for feature in FEATURE_MANIFEST]
    result = explanations.build(
        viewer_score=viewer_score(),
        bidirectional=bidirectional(mutual=every_feature, unknowns=every_feature),
        viewer_criteria=[],
    )
    assert len(result["mutual_strengths"]) <= maximum
    assert len(result["information_gaps"]) <= maximum


def test_a_sparse_pair_still_gets_an_honest_summary() -> None:
    result = explanations.build(
        viewer_score=viewer_score(), bidirectional=bidirectional(), viewer_criteria=[]
    )
    assert result["summary"] == "你们的资料还在完善中，可以通过交流了解更多。"
    assert result["mutual_strengths"] == []


def test_explanations_are_deterministic() -> None:
    args = {
        "viewer_score": viewer_score(faith_status_alignment=9000),
        "bidirectional": bidirectional(mutual=["faith_status_alignment"]),
        "viewer_criteria": [criterion("faith_status_code", "in", ["believer_baptized"])],
    }
    assert explanations.build(**args) == explanations.build(**args)  # type: ignore[arg-type]


def test_transparency_tells_a_member_what_is_used_and_what_never_is() -> None:
    summary = explanations.transparency_summary(
        [criterion("faith_status_code", "in", ["believer_baptized"])]
    )
    assert "faith_status_code" in summary["your_explicit_preferences"]
    assert summary["data_categories_used"]
    assert "照片外貌评估" in summary["never_used"]
    assert "其他用户的择偶条件" in summary["cannot_view"]
    assert summary["how_to_adjust"]
