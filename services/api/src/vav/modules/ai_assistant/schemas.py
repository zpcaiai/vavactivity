from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RelationshipStage(StrEnum):
    SINGLE_EXPLORING = "single_exploring"
    SEEKING_PARTNER = "seeking_partner"
    INITIAL_CONTACT = "initial_contact"
    GETTING_TO_KNOW = "getting_to_know"
    DATING = "dating"
    MUTUAL_CHOICE = "mutual_choice"
    RELATIONSHIP_CONFIRMATION = "relationship_confirmation"
    RELATIONSHIP_ENDED = "relationship_ended"
    UNKNOWN = "unknown"


class RelationshipTopic(StrEnum):
    PARTNER_SELECTION = "partner_selection"
    INITIATIVE = "initiative"
    MUTUAL_CHOICE = "mutual_choice"
    COMMUNICATION = "communication"
    BOUNDARIES = "boundaries"
    TRUST = "trust"
    SECURITY = "security"
    CONFLICT = "conflict"
    REJECTION = "rejection"
    RELATIONSHIP_CONFIRMATION = "relationship_confirmation"
    BREAKUP = "breakup"
    FAMILY_EXPECTATIONS = "family_expectations"
    FAITH_AND_VALUES = "faith_and_values"
    SELF_UNDERSTANDING = "self_understanding"
    SERVICE_NAVIGATION = "service_navigation"
    OTHER = "other"


class UserIntent(StrEnum):
    SEEK_UNDERSTANDING = "seek_understanding"
    SEEK_ADVICE = "seek_advice"
    SEEK_REFLECTION = "seek_reflection"
    SEEK_DECISION_HELP = "seek_decision_help"
    SEEK_SERVICE = "seek_service"
    SEEK_FACTUAL_INFORMATION = "seek_factual_information"
    EXPRESS_EMOTION = "express_emotion"
    REPORT_SAFETY_CONCERN = "report_safety_concern"


class RiskCategory(StrEnum):
    NONE = "none"
    SELF_HARM = "self_harm"
    SUICIDE = "suicide"
    VIOLENCE = "violence"
    ABUSE = "abuse"
    COERCIVE_CONTROL = "coercive_control"
    STALKING = "stalking"
    IMMEDIATE_SAFETY = "immediate_safety"
    SEVERE_MENTAL_HEALTH = "severe_mental_health"
    MEDICAL = "medical"
    LEGAL = "legal"
    EXPLOITATION = "exploitation"
    FRAUD = "fraud"
    MINOR_SAFETY = "minor_safety"


class RiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    IMMEDIATE = "immediate"


class MessageClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relationship_stage: RelationshipStage
    primary_topic: RelationshipTopic
    secondary_topics: list[RelationshipTopic] = Field(default_factory=list)
    user_intent: UserIntent
    desired_support: list[str] = Field(default_factory=list)
    emotional_signals: list[str] = Field(default_factory=list)
    recommendation_candidates: list[str] = Field(default_factory=list)
    requires_current_service_data: bool
    requires_knowledge_retrieval: bool
    requires_human_review: bool
    confidence_basis_points: int = Field(ge=0, le=10_000)
    uncertainty_reasons: list[str] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    categories: list[RiskCategory]
    level: RiskLevel
    indicators: list[str] = Field(default_factory=list)
    immediate_danger_possible: bool
    ordinary_advice_allowed: bool
    human_referral_required: bool
    emergency_guidance_required: bool
    confidence_basis_points: int = Field(ge=0, le=10_000)
    uncertainty_reasons: list[str] = Field(default_factory=list)
    safe_response_policy: str


class InformationCompleteness(BaseModel):
    sufficient_for_response: bool
    missing_fields: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list, max_length=2)
    confidence_basis_points: int = Field(ge=0, le=10_000)


class ResponseClaim(BaseModel):
    claim_id: str
    claim_text: str
    claim_type: str
    citation_ids: list[UUID] = Field(default_factory=list)
    support_level: Literal[
        "directly_supported",
        "partially_supported",
        "reasoned_inference",
        "unsourced_general_guidance",
    ]


class GeneratedAgentResponse(BaseModel):
    opening_empathy: str | None = None
    understanding_summary: str
    blind_spot_reflections: list[str] = Field(default_factory=list, max_length=2)
    action_suggestions: list[str] = Field(default_factory=list, max_length=4)
    reflection_questions: list[str] = Field(default_factory=list, max_length=2)
    service_recommendations: list[dict[str, Any]] = Field(default_factory=list, max_length=3)
    safety_notice: str | None = None
    claims: list[ResponseClaim] = Field(default_factory=list)
    final_text: str


class CreateConversationRequest(BaseModel):
    locale: str = "zh-CN"
    user_timezone: str = "Asia/Shanghai"
    consent_version: str
    accept_ai_disclosure: bool
    memory_opt_in: bool = False


class SendMessageRequest(BaseModel):
    client_message_id: str = Field(min_length=8, max_length=128)
    content: str = Field(min_length=1, max_length=10_000)
    locale: str = "zh-CN"


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"] | None = None
    reported: bool = False
    reason: str | None = Field(default=None, max_length=2000)


class MemoryConsentRequest(BaseModel):
    enabled: bool


class ToolConfirmationRequest(BaseModel):
    tool_code: str = Field(min_length=3, max_length=128)
    arguments: dict[str, Any]


class ExecuteConfirmedToolRequest(BaseModel):
    confirmation_token: str = Field(min_length=16, max_length=512)
    arguments: dict[str, Any]
    idempotency_key: str = Field(min_length=8, max_length=128)


class HannaAgentState(TypedDict, total=False):
    conversation_id: str
    turn_id: str
    user_id: str
    locale: str
    consented: bool
    user_message: str
    recent_messages: list[dict[str, str]]
    conversation_summary: str | None
    classification: dict[str, Any] | None
    risk_assessment: dict[str, Any] | None
    completeness: dict[str, Any] | None
    retrieval_bundle: dict[str, Any] | None
    planned_tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    response_plan: dict[str, Any] | None
    generated_response: dict[str, Any] | None
    citations: list[dict[str, Any]]
    warnings: list[str]
    referral: dict[str, Any] | None
    next_action: str | None
    visited_nodes: list[str]
    retry_count: int
