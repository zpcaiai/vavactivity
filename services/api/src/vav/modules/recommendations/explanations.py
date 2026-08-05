"""Rule-backed, privacy-preserving recommendation explanations.

Explanations are generated from evaluated features and approved templates
only. They never add a fact that scoring did not establish, never reveal the
other member's preferences or the internal weights, and never state a
probability or a guarantee.
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vav.modules.recommendations.bidirectional import BidirectionalCompatibilityResult
from vav.modules.recommendations.domain import PROHIBITED_EXPLANATION_PHRASES
from vav.modules.recommendations.features import FEATURES_BY_CODE
from vav.modules.recommendations.scoring import DirectionalCompatibilityScore

EXPLANATION_POLICY_VERSION = "1.0.0"

DISCLOSURE_MUTUAL = "mutual_public"
DISCLOSURE_OWN_PREFERENCE = "own_preference"
DISCLOSURE_INFORMATION_GAP = "information_gap"

#: Approved display templates, keyed by explanation code and locale.
TEMPLATES: dict[str, dict[str, str]] = {
    "shared_faith_background": {
        "zh-CN": "你们的信仰背景有共同之处",
        "en": "You share parts of your faith background",
    },
    "shared_church_tradition": {
        "zh-CN": "你们在教会传统上有重合",
        "en": "You have overlapping church traditions",
    },
    "similar_faith_importance": {
        "zh-CN": "你们对信仰在婚姻中的位置看法接近",
        "en": "You place similar importance on faith in marriage",
    },
    "location_compatible": {
        "zh-CN": "你们所在的位置便于认识",
        "en": "Your locations make meeting practical",
    },
    "same_city": {"zh-CN": "你们在同一个城市", "en": "You live in the same city"},
    "same_region": {"zh-CN": "你们在同一个地区", "en": "You live in the same region"},
    "same_country": {"zh-CN": "你们在同一个国家", "en": "You live in the same country"},
    "cross_border_with_relocation": {
        "zh-CN": "双方都接受跨地区认识",
        "en": "You are both open to meeting across regions",
    },
    "distant_without_relocation": {
        "zh-CN": "你们目前相距较远，需要沟通见面方式",
        "en": "You are currently far apart and would need to discuss meeting",
    },
    "similar_relocation_openness": {
        "zh-CN": "你们对未来迁居的态度接近",
        "en": "You have similar views on relocating",
    },
    "similar_relationship_goals": {
        "zh-CN": "你们的关系目标较接近",
        "en": "Your relationship goals are close",
    },
    "age_within_preferred_range": {
        "zh-CN": "对方的年龄在你设置的范围内",
        "en": "Their age falls inside the range you set",
    },
    "relationship_history_compatible": {
        "zh-CN": "对方的婚姻状况符合你设置的条件",
        "en": "Their relationship history matches what you asked for",
    },
    "similar_children_expectations": {
        "zh-CN": "你们对子女的期待较为接近",
        "en": "Your expectations about children are close",
    },
    "similar_family_plans": {
        "zh-CN": "你们对未来家庭的计划较接近",
        "en": "Your plans for a future family are close",
    },
    "similar_daily_rhythm": {
        "zh-CN": "你们的作息较为接近",
        "en": "You keep similar daily rhythms",
    },
    "similar_smoking_habits": {
        "zh-CN": "你们在吸烟习惯上一致",
        "en": "Your smoking habits align",
    },
    "similar_alcohol_habits": {
        "zh-CN": "你们在饮酒习惯上接近",
        "en": "Your views on alcohol are close",
    },
    "shared_interests": {"zh-CN": "你们有若干共同兴趣", "en": "You share several interests"},
    "similar_communication_style": {
        "zh-CN": "你们在沟通方式上较接近",
        "en": "You have similar communication styles",
    },
    "shared_languages": {"zh-CN": "你们有共同使用的语言", "en": "You share a common language"},
    "similar_education_background": {
        "zh-CN": "你们的教育背景相近",
        "en": "Your educational backgrounds are similar",
    },
    "profile_information_available": {
        "zh-CN": "对方的资料填写较完整",
        "en": "Their profile is well filled in",
    },
}

GAP_TEMPLATES: dict[str, dict[str, str]] = {
    "faith_status_alignment": {
        "zh-CN": "对方尚未补充部分信仰信息",
        "en": "Some faith details are not filled in yet",
    },
    "church_tradition_overlap": {
        "zh-CN": "教会传统信息还不完整",
        "en": "Church tradition details are incomplete",
    },
    "marriage_faith_importance_alignment": {
        "zh-CN": "信仰在婚姻中的位置还需要沟通",
        "en": "How faith fits into marriage is still to discuss",
    },
    "location_compatibility": {
        "zh-CN": "未来居住地的具体计划仍需沟通",
        "en": "Where you would live still needs a conversation",
    },
    "relocation_alignment": {
        "zh-CN": "迁居意愿的信息尚不完整",
        "en": "Relocation preferences are incomplete",
    },
    "relationship_intent_alignment": {
        "zh-CN": "关系目标的信息尚不完整",
        "en": "Relationship goals are not fully stated",
    },
    "age_preference_centrality": {
        "zh-CN": "年龄相关信息不完整",
        "en": "Age information is incomplete",
    },
    "marital_status_alignment": {
        "zh-CN": "婚姻状况信息尚未填写",
        "en": "Relationship history is not filled in",
    },
    "children_expectation_alignment": {
        "zh-CN": "对方尚未填写子女相关的期待",
        "en": "Expectations about children are not filled in",
    },
    "desire_children_alignment": {
        "zh-CN": "生育期待仍需要进一步了解",
        "en": "Plans about children still need discussion",
    },
    "daily_schedule_alignment": {
        "zh-CN": "作息信息尚未填写",
        "en": "Daily rhythm is not filled in",
    },
    "smoking_alignment": {"zh-CN": "吸烟习惯信息缺失", "en": "Smoking habits are not stated"},
    "alcohol_alignment": {"zh-CN": "饮酒习惯信息缺失", "en": "Alcohol habits are not stated"},
    "interest_overlap": {"zh-CN": "兴趣信息还不完整", "en": "Interests are not fully listed"},
    "communication_style_overlap": {
        "zh-CN": "沟通方式信息还不完整",
        "en": "Communication preferences are incomplete",
    },
    "language_overlap": {"zh-CN": "语言信息还不完整", "en": "Language information is incomplete"},
    "education_alignment": {
        "zh-CN": "教育背景信息未填写",
        "en": "Education background is not filled in",
    },
    "profile_readiness": {
        "zh-CN": "对方的资料仍在完善中",
        "en": "Their profile is still filling in",
    },
}

DIFFERENCE_TEMPLATES: dict[str, dict[str, str]] = {
    "location_compatibility": {
        "zh-CN": "你们在居住地上存在差异，值得进一步沟通",
        "en": "Your locations differ and are worth discussing",
    },
    "daily_schedule_alignment": {
        "zh-CN": "你们在生活节奏上存在差异",
        "en": "Your daily rhythms differ",
    },
    "interest_overlap": {
        "zh-CN": "你们的兴趣重合较少，可以互相了解",
        "en": "Your interests overlap little, which is worth exploring",
    },
    "communication_style_overlap": {
        "zh-CN": "你们的沟通方式不完全一致",
        "en": "Your communication styles are not identical",
    },
}

CAVEATS: dict[str, str] = {
    "zh-CN": "推荐只是认识的机会，最终判断由你自己作出；平台不对结果作任何保证。",
    "en": "A recommendation is an opportunity to get to know someone. The decision is yours, and the platform makes no promise about the outcome.",
}

SUMMARIES: dict[str, str] = {
    "zh-CN": "你们在以下方面较为接近，也有一些信息仍需进一步了解。",
    "en": "You are close in the areas below, and some information is still to be explored.",
}

EMPTY_SUMMARIES: dict[str, str] = {
    "zh-CN": "这位成员符合你设置的基本条件，你们的资料还需要进一步补充。",
    "en": "This member meets the conditions you set; there is still more profile detail to fill in.",
}


@dataclass(frozen=True)
class ExplanationItem:
    explanation_code: str
    display_text: str
    source_feature_codes: list[str]
    confidence_bps: int
    disclosure_level: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "explanation_code": self.explanation_code,
            "display_text": self.display_text,
            "source_feature_codes": self.source_feature_codes,
            "confidence_bps": self.confidence_bps,
            "disclosure_level": self.disclosure_level,
        }


@dataclass(frozen=True)
class RecommendationExplanation:
    summary: str
    mutual_strengths: list[ExplanationItem]
    relevant_preferences: list[ExplanationItem]
    topics_to_explore: list[ExplanationItem]
    information_gaps: list[ExplanationItem]
    caveat: str
    explanation_policy_version: str = EXPLANATION_POLICY_VERSION
    locale: str = "zh-CN"
    generated_by: str = "deterministic_template"
    relaxation_notices: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "mutual_strengths": [item.as_dict() for item in self.mutual_strengths],
            "relevant_preferences": [item.as_dict() for item in self.relevant_preferences],
            "topics_to_explore": [item.as_dict() for item in self.topics_to_explore],
            "information_gaps": [item.as_dict() for item in self.information_gaps],
            "caveat": self.caveat,
            "explanation_policy_version": self.explanation_policy_version,
            "locale": self.locale,
            "generated_by": self.generated_by,
            "relaxation_notices": self.relaxation_notices,
        }


def _text(table: dict[str, dict[str, str]], code: str, locale: str) -> str | None:
    entry = table.get(code)
    if entry is None:
        return None
    return entry.get(locale) or entry.get("zh-CN") or next(iter(entry.values()), None)


def assert_safe(explanation: RecommendationExplanation) -> None:
    """Fail closed if an explanation ever produces a forbidden claim.

    The caveat is checked against the approved constants instead of the phrase
    list, because the caveat's whole job is to *deny* a guarantee — scanning it
    for the word would reject the very disclaimer that has to be shown.
    """
    if explanation.caveat not in set(CAVEATS.values()):
        raise ValueError("explanations must carry an approved caveat")
    haystack = " ".join(
        [
            explanation.summary,
            *[item.display_text for item in explanation.mutual_strengths],
            *[item.display_text for item in explanation.relevant_preferences],
            *[item.display_text for item in explanation.topics_to_explore],
            *[item.display_text for item in explanation.information_gaps],
        ]
    ).lower()
    for phrase in PROHIBITED_EXPLANATION_PHRASES:
        if phrase.lower() in haystack:
            raise ValueError(f"explanation contains a prohibited claim: {phrase}")
    if "%" in haystack or "bps" in haystack:
        raise ValueError("explanations cannot expose numeric compatibility scores")


def member_view(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Strip every internal number before an explanation reaches a member.

    Confidence and disclosure levels are kept in the stored snapshot for
    diagnostics and audit, but a member is shown text only — never a score, a
    percentage or an internal signal strength.
    """

    def _items(key: str) -> list[dict[str, Any]]:
        return [
            {
                "explanation_code": str(item.get("explanation_code", "")),
                "display_text": str(item.get("display_text", "")),
            }
            for item in snapshot.get(key, []) or []
        ]

    return {
        "summary": snapshot.get("summary", ""),
        "mutual_strengths": _items("mutual_strengths"),
        "relevant_preferences": _items("relevant_preferences"),
        "topics_to_explore": _items("topics_to_explore"),
        "information_gaps": _items("information_gaps"),
        "caveat": snapshot.get("caveat", ""),
        "relaxation_notices": list(snapshot.get("relaxation_notices", []) or []),
        "explanation_policy_version": snapshot.get("explanation_policy_version"),
    }


def build_explanation(
    *,
    viewer_score: DirectionalCompatibilityScore,
    bidirectional: BidirectionalCompatibilityResult,
    locale: str = "zh-CN",
    relaxed_criteria: list[str] | None = None,
    max_items: int = 4,
) -> RecommendationExplanation:
    """Build the viewer-facing explanation for one recommendation item.

    Only the viewer's own directional evidence and the mutual strengths both
    directions agreed on are used; nothing describes the other member's
    preferences or their opinion of the viewer.
    """
    by_code = {score.feature_code: score for score in viewer_score.feature_scores}

    strengths: list[ExplanationItem] = []
    for feature_code in bidirectional.mutual_strengths:
        score = by_code.get(feature_code)
        if score is None or score.explanation_code is None:
            continue
        display = _text(TEMPLATES, score.explanation_code, locale)
        if display is None:
            continue
        strengths.append(
            ExplanationItem(
                explanation_code=score.explanation_code,
                display_text=display,
                source_feature_codes=[feature_code],
                confidence_bps=score.confidence_bps,
                disclosure_level=DISCLOSURE_MUTUAL,
            )
        )
        if len(strengths) >= max_items:
            break

    preferences: list[ExplanationItem] = []
    for feature_code in viewer_score.satisfied_preferences:
        score = by_code.get(feature_code)
        if score is None or score.explanation_code is None:
            continue
        if any(item.source_feature_codes == [feature_code] for item in strengths):
            continue
        display = _text(TEMPLATES, score.explanation_code, locale)
        if display is None:
            continue
        preferences.append(
            ExplanationItem(
                explanation_code=score.explanation_code,
                display_text=display,
                source_feature_codes=[feature_code],
                confidence_bps=score.confidence_bps,
                disclosure_level=DISCLOSURE_OWN_PREFERENCE,
            )
        )
        if len(preferences) >= max_items:
            break

    topics: list[ExplanationItem] = []
    for feature_code in bidirectional.asymmetric_features:
        display = _text(DIFFERENCE_TEMPLATES, feature_code, locale)
        if display is None:
            continue
        score = by_code.get(feature_code)
        topics.append(
            ExplanationItem(
                explanation_code=f"difference:{feature_code}",
                display_text=display,
                source_feature_codes=[feature_code],
                confidence_bps=score.confidence_bps if score else 0,
                disclosure_level=DISCLOSURE_MUTUAL,
            )
        )
        if len(topics) >= max_items:
            break

    gaps: list[ExplanationItem] = []
    for feature_code in viewer_score.missing_information:
        definition = FEATURES_BY_CODE.get(feature_code)
        if definition is None or not definition.explainable:
            continue
        display = _text(GAP_TEMPLATES, feature_code, locale)
        if display is None:
            continue
        gaps.append(
            ExplanationItem(
                explanation_code=f"information_gap:{feature_code}",
                display_text=display,
                source_feature_codes=[feature_code],
                confidence_bps=0,
                disclosure_level=DISCLOSURE_INFORMATION_GAP,
            )
        )
        if len(gaps) >= max_items:
            break

    notices: list[str] = []
    for code in relaxed_criteria or []:
        criterion = code.split(":", 1)[-1]
        notices.append(
            f"此推荐放宽了你允许放宽的条件：{criterion}"
            if locale.startswith("zh")
            else f"This recommendation relaxed a condition you allowed to be relaxed: {criterion}"
        )

    summary_table = SUMMARIES if (strengths or preferences) else EMPTY_SUMMARIES
    explanation = RecommendationExplanation(
        summary=summary_table.get(locale, summary_table["zh-CN"]),
        mutual_strengths=strengths,
        relevant_preferences=preferences,
        topics_to_explore=topics,
        information_gaps=gaps,
        caveat=CAVEATS.get(locale, CAVEATS["zh-CN"]),
        locale=locale,
        relaxation_notices=notices,
    )
    assert_safe(explanation)
    return explanation


def apply_optional_rewrite(
    explanation: RecommendationExplanation,
    rewritten: dict[str, Any] | None,
) -> RecommendationExplanation:
    """Accept an optional AI rewrite only when it adds no new claim.

    The rewrite may reword approved items; it may not introduce codes, change
    item counts or produce a forbidden claim. Anything unexpected falls back to
    the deterministic template.
    """
    if not rewritten:
        return explanation
    try:
        summary = str(rewritten["summary"])
        items = rewritten.get("mutual_strengths") or []
        if len(items) != len(explanation.mutual_strengths):
            return explanation
        rebuilt: list[ExplanationItem] = []
        for original, replacement in zip(explanation.mutual_strengths, items, strict=True):
            if str(replacement.get("explanation_code")) != original.explanation_code:
                return explanation
            rebuilt.append(
                ExplanationItem(
                    explanation_code=original.explanation_code,
                    display_text=str(replacement["display_text"]),
                    source_feature_codes=original.source_feature_codes,
                    confidence_bps=original.confidence_bps,
                    disclosure_level=original.disclosure_level,
                )
            )
        candidate = RecommendationExplanation(
            summary=summary,
            mutual_strengths=rebuilt,
            relevant_preferences=explanation.relevant_preferences,
            topics_to_explore=explanation.topics_to_explore,
            information_gaps=explanation.information_gaps,
            caveat=explanation.caveat,
            locale=explanation.locale,
            generated_by="ai_rewrite",
            relaxation_notices=explanation.relaxation_notices,
        )
        assert_safe(candidate)
    except (KeyError, TypeError, ValueError):
        return explanation
    return candidate
