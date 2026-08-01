from __future__ import annotations

from vav.modules.ai_assistant.schemas import (
    InformationCompleteness,
    MessageClassification,
    RelationshipStage,
    RelationshipTopic,
    UserIntent,
)


def classify_message(message: str) -> MessageClassification:
    value = message.casefold()
    topic_terms = (
        (RelationshipTopic.BOUNDARIES, ("边界", "界限", "boundary")),
        (RelationshipTopic.CONFLICT, ("争吵", "冲突", "吵架", "conflict")),
        (RelationshipTopic.COMMUNICATION, ("沟通", "回复", "消息", "communication")),
        (RelationshipTopic.TRUST, ("信任", "怀疑", "trust")),
        (RelationshipTopic.REJECTION, ("拒绝", "不喜欢我", "rejection")),
        (RelationshipTopic.BREAKUP, ("分手", "结束关系", "breakup")),
        (RelationshipTopic.FAITH_AND_VALUES, ("信仰", "价值观", "faith", "values")),
        (
            RelationshipTopic.SERVICE_NAVIGATION,
            ("课程", "活动", "辅导", "价格", "名额", "course", "activity", "counseling"),
        ),
    )
    topics = [topic for topic, terms in topic_terms if any(term in value for term in terms)]
    primary = topics[0] if topics else RelationshipTopic.OTHER
    stage = RelationshipStage.UNKNOWN
    for candidate, terms in (
        (RelationshipStage.RELATIONSHIP_ENDED, ("分手", "结束关系", "breakup")),
        (RelationshipStage.DATING, ("约会", "交往", "dating")),
        (RelationshipStage.GETTING_TO_KNOW, ("认识", "了解阶段", "getting to know")),
        (RelationshipStage.MUTUAL_CHOICE, ("互选", "mutual choice")),
        (RelationshipStage.SINGLE_EXPLORING, ("单身", "single")),
    ):
        if any(term in value for term in terms):
            stage = candidate
            break
    service = primary is RelationshipTopic.SERVICE_NAVIGATION
    intent = UserIntent.SEEK_SERVICE if service else UserIntent.SEEK_ADVICE
    if any(term in value for term in ("为什么", "理解", "why", "understand")):
        intent = UserIntent.SEEK_UNDERSTANDING
    return MessageClassification(
        relationship_stage=stage,
        primary_topic=primary,
        secondary_topics=topics[1:],
        user_intent=intent,
        desired_support=[
            "service_navigation" if service else "action_plan",
            "blind_spot_reflection",
        ],
        emotional_signals=[
            signal
            for signal in ("难过", "焦虑", "生气", "sad", "anxious", "angry")
            if signal in value
        ],
        recommendation_candidates=["course", "activity", "counseling_service"] if service else [],
        requires_current_service_data=service,
        requires_knowledge_retrieval=not service
        or any(term in value for term in ("边界", "方法", "原则")),
        requires_human_review=primary is RelationshipTopic.OTHER and len(message.strip()) < 12,
        confidence_basis_points=8500 if primary is not RelationshipTopic.OTHER else 5800,
        uncertainty_reasons=[]
        if primary is not RelationshipTopic.OTHER
        else ["Topic needs clarification."],
    )


def assess_completeness(
    message: str, classification: MessageClassification
) -> InformationCompleteness:
    if classification.requires_current_service_data or len(message.strip()) >= 12:
        return InformationCompleteness(sufficient_for_response=True, confidence_basis_points=8500)
    return InformationCompleteness(
        sufficient_for_response=False,
        missing_fields=["current_event", "user_goal"],
        clarifying_questions=[
            "你愿意补充最近一次具体互动发生了什么吗？可以跳过不想回答的细节。",
            "这次你更希望获得理解梳理、行动建议，还是平台服务信息？",
        ],
        confidence_basis_points=5000,
    )
