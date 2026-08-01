from __future__ import annotations

from vav.modules.ai_assistant.schemas import (
    GeneratedAgentResponse,
    RiskAssessment,
    RiskCategory,
    RiskLevel,
)

SIGNALS: dict[RiskCategory, tuple[str, ...]] = {
    RiskCategory.SUICIDE: ("自杀", "不想活", "结束生命", "suicide", "kill myself"),
    RiskCategory.SELF_HARM: ("自残", "伤害自己", "self harm", "hurt myself"),
    RiskCategory.VIOLENCE: ("杀了他", "打死", "伤害对方", "kill them", "attack them"),
    RiskCategory.ABUSE: ("家暴", "殴打我", "虐待", "abuse", "beats me"),
    RiskCategory.COERCIVE_CONTROL: ("控制我", "不让我出门", "监控手机", "coercive control"),
    RiskCategory.STALKING: ("跟踪我", "尾随", "stalking", "stalks me"),
    RiskCategory.IMMEDIATE_SAFETY: (
        "现在有危险",
        "正在追我",
        "有刀",
        "immediate danger",
        "has a weapon",
    ),
    RiskCategory.SEVERE_MENTAL_HEALTH: ("幻听", "精神崩溃", "psychosis", "hearing voices"),
    RiskCategory.MEDICAL: ("诊断", "处方", "吃什么药", "medical diagnosis", "prescribe"),
    RiskCategory.LEGAL: ("法律意见", "一定违法", "起诉", "legal advice", "sue"),
    RiskCategory.EXPLOITATION: ("被迫卖淫", "人口贩卖", "trafficking", "exploitation"),
    RiskCategory.FRAUD: ("骗钱", "投资转账", "诈骗", "fraud", "wire money"),
    RiskCategory.MINOR_SAFETY: ("未成年人", "未满18", "minor", "under 18"),
}


def assess_risk(message: str) -> RiskAssessment:
    normalized = message.casefold()
    categories = [
        category for category, terms in SIGNALS.items() if any(term in normalized for term in terms)
    ]
    explicit_plan = any(term in normalized for term in ("计划", "刀", "枪", "plan", "weapon"))
    plan_negated = any(
        term in normalized for term in ("没有计划", "无计划", "没有具体计划", "no plan")
    )
    immediate = RiskCategory.IMMEDIATE_SAFETY in categories or (
        any(category in categories for category in (RiskCategory.SUICIDE, RiskCategory.VIOLENCE))
        and any(term in normalized for term in ("现在", "马上", "now"))
        or (
            any(
                category in categories for category in (RiskCategory.SUICIDE, RiskCategory.VIOLENCE)
            )
            and explicit_plan
            and not plan_negated
        )
    )
    high = any(
        category in categories
        for category in (
            RiskCategory.SUICIDE,
            RiskCategory.SELF_HARM,
            RiskCategory.VIOLENCE,
            RiskCategory.ABUSE,
            RiskCategory.COERCIVE_CONTROL,
            RiskCategory.STALKING,
            RiskCategory.EXPLOITATION,
            RiskCategory.MINOR_SAFETY,
        )
    )
    moderate = any(
        category in categories
        for category in (
            RiskCategory.SEVERE_MENTAL_HEALTH,
            RiskCategory.MEDICAL,
            RiskCategory.LEGAL,
            RiskCategory.FRAUD,
        )
    )
    level = (
        RiskLevel.IMMEDIATE
        if immediate
        else RiskLevel.HIGH
        if high
        else RiskLevel.MODERATE
        if moderate
        else RiskLevel.NONE
    )
    effective_categories = categories or [RiskCategory.NONE]
    return RiskAssessment(
        categories=effective_categories,
        level=level,
        indicators=[category.value for category in categories],
        immediate_danger_possible=immediate,
        ordinary_advice_allowed=level in {RiskLevel.NONE, RiskLevel.LOW},
        human_referral_required=level in {RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.IMMEDIATE},
        emergency_guidance_required=immediate,
        confidence_basis_points=9500 if categories else 8000,
        uncertainty_reasons=[] if categories else ["No configured high-risk signal matched."],
        safe_response_policy="hanna-safety-1.0.0",
    )


def safety_response(risk: RiskAssessment, locale: str) -> GeneratedAgentResponse:
    if locale == "en":
        text = (
            "Your immediate safety matters more than relationship advice. "
            "Move to a safer place if you can, contact a trusted person, and use your local "
            "emergency or crisis service if danger may be immediate. This AI is not an emergency, "
            "medical, or legal service. An internal human review has been requested."
        )
    else:
        text = (
            "你当前的人身安全比一般关系建议更重要。如条件允许，请先转移到更安全的位置并联系可信任的人；"
            "若危险可能正在发生，请使用你所在地区的紧急或危机求助渠道。"
            "本 AI 不属于紧急、医疗或法律服务，"
            "系统已创建受限的人工复核。"
        )
    return GeneratedAgentResponse(
        understanding_summary="检测到需要优先处理的安全或专业支持信号。",
        safety_notice=text,
        final_text=text,
    )
