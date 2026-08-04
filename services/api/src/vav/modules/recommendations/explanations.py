"""Rule-and-template recommendation explanations.

Explanations describe what the two members have in common and what is still
unknown. They never reveal the other person's criteria, their directional
score, internal weights, a success probability or any other candidate's rank.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from vav.modules.recommendations.strategy import (
    EXPLANATION_POLICY,
    EXPLANATION_POLICY_VERSION,
    feature_by_code,
)

#: Approved member-facing sentences, keyed by explanation code.
STRENGTH_TEMPLATES: dict[str, str] = {
    "shared_faith_status": "你们的信仰状态较为接近",
    "shared_church_tradition": "你们有共同的教会传统背景",
    "similar_faith_priority": "你们都把信仰放在婚姻中相近的位置",
    "similar_relationship_goal": "你们的关系目标较接近",
    "workable_location": "你们在地点安排上比较可行",
    "shared_language": "你们有共同的常用语言",
    "similar_family_expectation": "你们对未来家庭的期待较接近",
    "acceptable_relationship_history": "你们的婚史情况在彼此可接受的范围内",
    "similar_daily_rhythm": "你们的作息较为接近",
    "similar_lifestyle_choice": "你们的生活习惯较为接近",
    "shared_interests": "你们有若干共同兴趣",
    "similar_communication_style": "你们的沟通方式较为接近",
    "similar_education_background": "你们的教育背景较为接近",
    "age_within_preferred_range": "对方的年龄在你设置的范围内",
}

#: What still needs a conversation, phrased without blame.
GAP_TEMPLATES: dict[str, str] = {
    "faith_status_alignment": "信仰经历的具体细节仍需要进一步了解",
    "church_tradition_overlap": "双方的教会传统还需要沟通",
    "faith_importance_distance": "信仰在婚姻中的具体安排仍可进一步交流",
    "relationship_intent_alignment": "关系目标的具体节奏还需要沟通",
    "geographic_compatibility": "未来居住地的具体计划仍需沟通",
    "language_overlap": "日常沟通语言还需要确认",
    "children_expectation_alignment": "生育与育儿期待还需要进一步交流",
    "marital_history_acceptance": "过往关系经历可以在合适的时候慢慢了解",
    "daily_schedule_alignment": "作息安排上还需要相互适应",
    "smoking_alignment": "生活习惯方面还需要沟通",
    "alcohol_alignment": "生活习惯方面还需要沟通",
    "interest_overlap": "兴趣爱好还有待发现",
    "communication_overlap": "沟通偏好还需要磨合",
    "education_alignment": "教育与职业背景还可以再聊聊",
    "age_preference_centrality": "年龄相关的期待可以再确认",
    "profile_readiness": "对方的资料还在完善中",
}

DIFFERENCE_TEMPLATES: dict[str, str] = {
    "geographic_compatibility": "你们目前所在的地点有一定距离",
    "daily_schedule_alignment": "你们在生活节奏上存在差异",
    "interest_overlap": "你们的兴趣组合差异较大",
    "communication_overlap": "你们偏好的沟通方式不太一样",
    "children_expectation_alignment": "你们对未来家庭的期待需要更多沟通",
}

CAVEAT = str(EXPLANATION_POLICY["caveat"])


def _item(
    code: str,
    text: str,
    feature_codes: list[str],
    confidence: int,
    disclosure: str = "member_visible",
) -> dict[str, Any]:
    return {
        "explanation_code": code,
        "display_text": text,
        "source_feature_codes": feature_codes,
        "confidence_bps": confidence,
        "disclosure_level": disclosure,
    }


def build(
    *,
    viewer_score: dict[str, Any],
    bidirectional: dict[str, Any],
    viewer_criteria: list[dict[str, Any]],
    relaxations_applied: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the explanation a specific viewer is allowed to see."""
    max_items = int(EXPLANATION_POLICY["max_items_per_section"])
    confidence = int(bidirectional["confidence_bps"])

    mutual_strengths: list[dict[str, Any]] = []
    for feature_code in bidirectional["mutual_strengths"]:
        feature = feature_by_code(feature_code)
        if feature is None or not feature["explainable"]:
            continue
        template = STRENGTH_TEMPLATES.get(str(feature["explanation_code"]))
        if template:
            mutual_strengths.append(
                _item(str(feature["explanation_code"]), template, [feature_code], confidence)
            )

    # Only the viewer's own stated preferences are echoed back to them.
    stated = {str(item["criterion_code"]) for item in viewer_criteria}
    relevant_preferences: list[dict[str, Any]] = []
    for entry in viewer_score["feature_scores"]:
        feature = feature_by_code(str(entry["feature_code"]))
        if feature is None or not feature["explainable"]:
            continue
        criterion = feature.get("preference_criterion")
        raw = entry["raw_match_bps"]
        if criterion in stated and raw is not None and raw >= 6000:
            template = STRENGTH_TEMPLATES.get(str(feature["explanation_code"]))
            if template:
                relevant_preferences.append(
                    _item(
                        f"preference_met_{criterion}",
                        f"{template}（这是你标记为重要的条件）",
                        [str(entry["feature_code"])],
                        int(entry["confidence_bps"]),
                    )
                )

    topics: list[dict[str, Any]] = []
    for feature_code in bidirectional["asymmetric_features"]:
        template = DIFFERENCE_TEMPLATES.get(feature_code) or GAP_TEMPLATES.get(feature_code)
        if template:
            topics.append(_item(f"topic_{feature_code}", template, [feature_code], confidence))

    gaps: list[dict[str, Any]] = []
    for feature_code in bidirectional["mutual_unknowns"] or viewer_score["missing_information"]:
        template = GAP_TEMPLATES.get(feature_code)
        if template:
            gaps.append(_item(f"gap_{feature_code}", template, [feature_code], 0))

    for code in relaxations_applied or []:
        topics.append(
            _item(
                f"relaxation_{code}",
                f"此推荐放宽了你允许放宽的条件：{code}",
                [code],
                confidence,
            )
        )

    if mutual_strengths:
        summary = "你们在若干方面较为接近，可以先从这些共同点开始了解。"
    elif relevant_preferences:
        summary = "对方符合你标记的部分重要条件，其他方面还需要进一步了解。"
    else:
        summary = "你们的资料还在完善中，可以通过交流了解更多。"

    return {
        "summary": summary,
        "mutual_strengths": mutual_strengths[:max_items],
        "relevant_preferences": relevant_preferences[:max_items],
        "topics_to_explore": topics[:max_items],
        "information_gaps": gaps[:max_items],
        "caveat": CAVEAT,
        "explanation_policy_version": EXPLANATION_POLICY_VERSION,
    }


def assert_safe(explanation: dict[str, Any]) -> None:
    """Fail closed if an explanation ever carries a forbidden disclosure."""
    serialised = str(explanation)
    forbidden_markers = (
        "criterion_code",
        "hard_constraint",
        "importance_weight",
        "candidate_to_viewer_score",
        "success_probability",
        "rank_position",
        "%概率",
    )
    leaked = [marker for marker in forbidden_markers if marker in serialised]
    if leaked:
        raise ValueError(f"explanation leaked forbidden content: {', '.join(leaked)}")


def transparency_summary(viewer_criteria: list[dict[str, Any]]) -> dict[str, Any]:
    """What the member may learn about how their own recommendations are built."""
    from vav.modules.recommendations.strategy import FEATURE_MANIFEST

    stated = {str(item["criterion_code"]) for item in viewer_criteria}
    return {
        "data_categories_used": sorted(
            {str(feature["feature_group"]) for feature in FEATURE_MANIFEST}
        ),
        "your_explicit_preferences": sorted(stated),
        "platform_default_soft_signals": sorted(
            str(feature["feature_code"])
            for feature in FEATURE_MANIFEST
            if feature.get("preference_criterion") not in stated
        ),
        "never_used": [
            "照片外貌评估",
            "人脸特征",
            "族裔或肤色推断",
            "收入或消费能力",
            "AI 对话内容",
            "辅导记录",
            "心理或属灵状态推断",
        ],
        "how_to_adjust": [
            "在择偶条件中调整硬性条件与重要性",
            "在推荐设置中调整每日接收数量与探索强度",
            "关闭行为反馈个性化并重置推荐调整",
        ],
        "cannot_view": ["其他用户的择偶条件", "其他用户对你的评分", "内部权重与安全信息"],
        "explanation_policy_version": EXPLANATION_POLICY_VERSION,
    }
