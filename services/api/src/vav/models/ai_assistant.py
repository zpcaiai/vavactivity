from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.base import Base


def uuid_pk() -> Mapped[UUID]:
    return mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class AiModelProfile(Base):
    __tablename__ = "ai_model_profiles"
    id: Mapped[UUID] = uuid_pk()
    profile_code: Mapped[str] = mapped_column(String(128), unique=True)
    provider: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(200))
    model_revision: Mapped[str | None] = mapped_column(String(128))
    task_type: Mapped[str] = mapped_column(String(64))
    context_window_tokens: Mapped[int | None] = mapped_column(Integer)
    maximum_output_tokens: Mapped[int | None] = mapped_column(Integer)
    structured_output_supported: Mapped[bool] = mapped_column(Boolean)
    tool_calling_supported: Mapped[bool] = mapped_column(Boolean)
    input_cost_per_million_minor: Mapped[int | None] = mapped_column(BigInteger)
    output_cost_per_million_minor: Mapped[int | None] = mapped_column(BigInteger)
    cost_currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32))
    configuration: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiModelRoute(Base):
    __tablename__ = "ai_model_routes"
    id: Mapped[UUID] = uuid_pk()
    route_code: Mapped[str] = mapped_column(String(128), unique=True)
    task_type: Mapped[str] = mapped_column(String(64))
    primary_model_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_model_profiles.id")
    )
    fallback_model_profile_ids: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    maximum_latency_ms: Mapped[int | None] = mapped_column(Integer)
    maximum_cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    retry_policy: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    routing_policy: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiPromptDefinition(Base):
    __tablename__ = "ai_prompt_definitions"
    id: Mapped[UUID] = uuid_pk()
    prompt_code: Mapped[str] = mapped_column(String(128), unique=True)
    purpose: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    owner_team: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiPromptRelease(Base):
    __tablename__ = "ai_prompt_releases"
    __table_args__ = (UniqueConstraint("prompt_definition_id", "semantic_version", "locale"),)
    id: Mapped[UUID] = uuid_pk()
    prompt_definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_prompt_definitions.id")
    )
    semantic_version: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str | None] = mapped_column(String(16))
    template_content: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, object]] = mapped_column(JSONB)
    output_schema: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    safety_policy_version: Mapped[str | None] = mapped_column(String(64))
    tool_registry_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiSafetyPolicy(Base):
    __tablename__ = "ai_safety_policies"
    __table_args__ = (UniqueConstraint("policy_code", "semantic_version", "locale"),)
    id: Mapped[UUID] = uuid_pk()
    policy_code: Mapped[str] = mapped_column(String(128))
    semantic_version: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(16))
    policy_definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    response_templates: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32))
    approved_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiToolDefinition(Base):
    __tablename__ = "ai_tool_definitions"
    __table_args__ = (UniqueConstraint("tool_code", "semantic_version"),)
    id: Mapped[UUID] = uuid_pk()
    tool_code: Mapped[str] = mapped_column(String(128))
    semantic_version: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, object]] = mapped_column(JSONB)
    output_schema: Mapped[dict[str, object]] = mapped_column(JSONB)
    risk_level: Mapped[str] = mapped_column(String(32))
    required_permissions: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    user_confirmation_required: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    idempotency_required: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    allowed_agent_profiles: Mapped[list[str]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiConversation(Base):
    __tablename__ = "ai_conversations"
    id: Mapped[UUID] = uuid_pk()
    conversation_number: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'active'"))
    assistant_profile: Mapped[str] = mapped_column(String(64), server_default=text("'hanna_v1'"))
    locale: Mapped[str] = mapped_column(String(16))
    user_timezone: Mapped[str] = mapped_column(String(64))
    consent_version: Mapped[str] = mapped_column(String(32))
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    memory_consent_status: Mapped[str] = mapped_column(
        String(32), server_default=text("'not_granted'")
    )
    relationship_stage: Mapped[str | None] = mapped_column(String(64))
    primary_topic: Mapped[str | None] = mapped_column(String(64))
    latest_risk_level: Mapped[str | None] = mapped_column(String(32))
    active_graph_version: Mapped[str] = mapped_column(String(64))
    active_prompt_release_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_prompt_releases.id")
    )
    active_model_route_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_model_routes.id")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summarized_through_turn: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "turn_number", "role"),
        UniqueConstraint("conversation_id", "client_message_id"),
    )
    id: Mapped[UUID] = uuid_pk()
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_conversations.id")
    )
    turn_number: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32))
    message_type: Mapped[str] = mapped_column(String(32))
    client_message_id: Mapped[str | None] = mapped_column(String(128))
    content_encrypted: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(128))
    locale: Mapped[str] = mapped_column(String(16))
    model_provider: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(200))
    model_revision: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    cost_currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiAgentTurn(Base):
    __tablename__ = "ai_agent_turns"
    __table_args__ = (UniqueConstraint("conversation_id", "turn_number"),)
    id: Mapped[UUID] = uuid_pk()
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_conversations.id")
    )
    turn_number: Mapped[int] = mapped_column(Integer)
    user_message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_messages.id")
    )
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_messages.id")
    )
    status: Mapped[str] = mapped_column(String(32))
    graph_version: Mapped[str] = mapped_column(String(64))
    state_schema_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    prompt_release_manifest: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    model_route_manifest: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    tool_registry_version: Mapped[str] = mapped_column(String(64))
    safety_policy_version: Mapped[str] = mapped_column(String(64))
    knowledge_index_manifest: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    checkpoint_reference: Mapped[str | None] = mapped_column(String(255))
    classification_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    risk_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    context_snapshot_encrypted: Mapped[str | None] = mapped_column(Text)
    response_plan_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message_safe: Mapped[str | None] = mapped_column(Text)


class AiGraphCheckpoint(Base):
    __tablename__ = "ai_graph_checkpoints"
    __table_args__ = (UniqueConstraint("agent_turn_id", "sequence_number"),)
    id: Mapped[UUID] = uuid_pk()
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_conversations.id")
    )
    agent_turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_agent_turns.id")
    )
    thread_id: Mapped[str] = mapped_column(String(128))
    graph_version: Mapped[str] = mapped_column(String(64))
    state_schema_version: Mapped[int] = mapped_column(Integer)
    node_name: Mapped[str] = mapped_column(String(128))
    state_hash: Mapped[str] = mapped_column(String(128))
    encrypted_state: Mapped[str] = mapped_column(Text)
    sequence_number: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiHumanReferral(Base):
    __tablename__ = "ai_human_referrals"
    id: Mapped[UUID] = uuid_pk()
    referral_number: Mapped[str] = mapped_column(String(64), unique=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_conversations.id")
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    source_turn_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_agent_turns.id")
    )
    referral_type: Mapped[str] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(32))
    risk_category: Mapped[str | None] = mapped_column(String(64))
    risk_level: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    user_visible_summary_encrypted: Mapped[str | None] = mapped_column(Text)
    internal_context_encrypted: Mapped[str | None] = mapped_column(Text)
    assigned_team: Mapped[str | None] = mapped_column(String(128))
    assigned_to: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    consent_status: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_encrypted: Mapped[str | None] = mapped_column(Text)


class AiEvaluationDataset(Base):
    __tablename__ = "ai_evaluation_datasets"
    id: Mapped[UUID] = uuid_pk()
    dataset_code: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    purpose: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiEvaluationCase(Base):
    __tablename__ = "ai_evaluation_cases"
    __table_args__ = (UniqueConstraint("dataset_id", "case_code"),)
    id: Mapped[UUID] = uuid_pk()
    dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_evaluation_datasets.id")
    )
    case_code: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64))
    difficulty: Mapped[str] = mapped_column(String(32))
    initial_state_fixture: Mapped[dict[str, object]] = mapped_column(JSONB)
    conversation_turns: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    tool_fixtures: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    knowledge_fixture_reference: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    expected_classification: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    expected_risk_policy: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    expected_tool_calls: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
    forbidden_tool_calls: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    required_response_concepts: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    forbidden_response_concepts: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    expected_citation_ids: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    expected_referral_policy: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    human_rubric: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiEvaluationRun(Base):
    __tablename__ = "ai_evaluation_runs"
    id: Mapped[UUID] = uuid_pk()
    dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_evaluation_datasets.id")
    )
    baseline_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_evaluation_runs.id")
    )
    graph_version: Mapped[str] = mapped_column(String(64))
    prompt_release_manifest: Mapped[dict[str, object]] = mapped_column(JSONB)
    model_route_manifest: Mapped[dict[str, object]] = mapped_column(JSONB)
    tool_registry_version: Mapped[str] = mapped_column(String(64))
    knowledge_index_manifest: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32))
    metrics: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    serious_failures: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
