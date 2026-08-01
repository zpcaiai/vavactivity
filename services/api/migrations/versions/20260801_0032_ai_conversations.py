"""Add encrypted AI conversations, messages, turns, summaries and checkpoints.

Revision ID: 20260801_0032
Revises: 20260801_0031
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260801_0032"
down_revision = "20260801_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("conversation_number", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'active'")),
        sa.Column(
            "assistant_profile", sa.String(64), nullable=False, server_default=sa.text("'hanna_v1'")
        ),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("user_timezone", sa.String(64), nullable=False),
        sa.Column("consent_version", sa.String(32), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "memory_consent_status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'not_granted'"),
        ),
        sa.Column("relationship_stage", sa.String(64)),
        sa.Column("primary_topic", sa.String(64)),
        sa.Column("latest_risk_level", sa.String(32)),
        sa.Column("active_graph_version", sa.String(64), nullable=False),
        sa.Column(
            "active_prompt_release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_prompt_releases.id"),
        ),
        sa.Column(
            "active_model_route_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_model_routes.id"),
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column(
            "summarized_through_turn", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_ai_conversations_user_last", "ai_conversations", ["user_id", "last_message_at"]
    )
    op.create_table(
        "ai_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_conversations.id"),
            nullable=False,
        ),
        sa.Column("turn_number", sa.Integer, nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("message_type", sa.String(32), nullable=False),
        sa.Column("client_message_id", sa.String(128)),
        sa.Column("content_encrypted", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("model_provider", sa.String(64)),
        sa.Column("model_name", sa.String(200)),
        sa.Column("model_revision", sa.String(128)),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("cost_minor", sa.BigInteger),
        sa.Column("cost_currency", sa.String(3)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("conversation_id", "turn_number", "role"),
        sa.UniqueConstraint("conversation_id", "client_message_id"),
    )
    op.create_table(
        "ai_agent_turns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_conversations.id"),
            nullable=False,
        ),
        sa.Column("turn_number", sa.Integer, nullable=False),
        sa.Column(
            "user_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_messages.id"),
            nullable=False,
        ),
        sa.Column(
            "assistant_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_messages.id")
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("graph_version", sa.String(64), nullable=False),
        sa.Column("state_schema_version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column(
            "prompt_release_manifest",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "model_route_manifest",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("tool_registry_version", sa.String(64), nullable=False),
        sa.Column("safety_policy_version", sa.String(64), nullable=False),
        sa.Column(
            "knowledge_index_manifest",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("checkpoint_reference", sa.String(255)),
        sa.Column("classification_snapshot", postgresql.JSONB),
        sa.Column("risk_snapshot", postgresql.JSONB),
        sa.Column("context_snapshot_encrypted", sa.Text),
        sa.Column("response_plan_snapshot", postgresql.JSONB),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(128)),
        sa.Column("error_message_safe", sa.Text),
        sa.UniqueConstraint("conversation_id", "turn_number"),
    )
    op.create_table(
        "ai_graph_checkpoints",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "agent_turn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_agent_turns.id"),
            nullable=False,
        ),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("graph_version", sa.String(64), nullable=False),
        sa.Column("state_schema_version", sa.Integer, nullable=False),
        sa.Column("node_name", sa.String(128), nullable=False),
        sa.Column("state_hash", sa.String(128), nullable=False),
        sa.Column("encrypted_state", sa.Text, nullable=False),
        sa.Column("sequence_number", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("agent_turn_id", "sequence_number"),
    )
    op.create_table(
        "ai_node_traces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "agent_turn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_agent_turns.id"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(128), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_hash", sa.String(128), nullable=False),
        sa.Column(
            "output_summary",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("error_code", sa.String(128)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "ai_conversation_summaries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_conversations.id"),
            nullable=False,
        ),
        sa.Column("summary_version", sa.Integer, nullable=False),
        sa.Column("summarized_through_turn", sa.Integer, nullable=False),
        sa.Column("factual_summary_encrypted", sa.Text, nullable=False),
        sa.Column("unresolved_questions_encrypted", sa.Text, nullable=False),
        sa.Column("user_goals_encrypted", sa.Text, nullable=False),
        sa.Column("event_timeline_encrypted", sa.Text, nullable=False),
        sa.Column("risk_summary_encrypted", sa.Text),
        sa.Column("inferred_items_encrypted", sa.Text, nullable=False),
        sa.Column("model_provider", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column(
            "prompt_release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_prompt_releases.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("conversation_id", "summary_version"),
    )
    op.create_table(
        "ai_model_invocations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_conversations.id")
        ),
        sa.Column(
            "agent_turn_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_agent_turns.id")
        ),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column(
            "model_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_model_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "prompt_release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_prompt_releases.id"),
        ),
        sa.Column("input_hash", sa.String(128), nullable=False),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("cost_minor", sa.BigInteger),
        sa.Column("cost_currency", sa.String(3)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("fallback_used", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("error_code", sa.String(128)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    for table in (
        "ai_model_invocations",
        "ai_conversation_summaries",
        "ai_node_traces",
        "ai_graph_checkpoints",
        "ai_agent_turns",
        "ai_messages",
    ):
        op.drop_table(table)
    op.drop_index("ix_ai_conversations_user_last", table_name="ai_conversations")
    op.drop_table("ai_conversations")
