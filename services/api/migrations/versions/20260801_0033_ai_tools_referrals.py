"""Add AI tool execution, recommendation, referral, feedback and confirmation data.

Revision ID: 20260801_0033
Revises: 20260801_0032
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260801_0033"
down_revision = "20260801_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_tool_confirmations",
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
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("tool_code", sa.String(128), nullable=False),
        sa.Column("input_hash", sa.String(128), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "ai_tool_executions",
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
        sa.Column("tool_code", sa.String(128), nullable=False),
        sa.Column("tool_version", sa.String(64), nullable=False),
        sa.Column("call_sequence", sa.Integer, nullable=False),
        sa.Column("input_encrypted", sa.Text, nullable=False),
        sa.Column("input_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confirmation_status", sa.String(32)),
        sa.Column("confirmed_by_user_at", sa.DateTime(timezone=True)),
        sa.Column("output_encrypted", sa.Text),
        sa.Column("output_summary", postgresql.JSONB),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(128)),
        sa.Column("error_message_safe", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("agent_turn_id", "call_sequence"),
        sa.UniqueConstraint("conversation_id", "idempotency_key"),
    )
    op.create_table(
        "ai_service_recommendations",
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
        sa.Column("recommendation_type", sa.String(32), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_reason_encrypted", sa.Text, nullable=False),
        sa.Column("availability_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("price_snapshot", postgresql.JSONB),
        sa.Column("rank_position", sa.Integer, nullable=False),
        sa.Column("confidence_basis_points", sa.Integer, nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("converted_reference_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "ai_human_referrals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("referral_number", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "source_turn_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_agent_turns.id")
        ),
        sa.Column("referral_type", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(32), nullable=False),
        sa.Column("risk_category", sa.String(64)),
        sa.Column("risk_level", sa.String(32)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("user_visible_summary_encrypted", sa.Text),
        sa.Column("internal_context_encrypted", sa.Text),
        sa.Column("assigned_team", sa.String(128)),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("consent_status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_encrypted", sa.Text),
    )
    op.create_table(
        "ai_action_items",
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
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("content_encrypted", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'open'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "ai_message_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_messages.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("rating", sa.String(16)),
        sa.Column("reported", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("reason_encrypted", sa.Text),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'open'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("message_id", "user_id"),
    )
    op.create_table(
        "ai_response_citations",
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
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_messages.id"),
            nullable=False,
        ),
        sa.Column("claim_id", sa.String(128), nullable=False),
        sa.Column("claim_text_hash", sa.String(128), nullable=False),
        sa.Column("knowledge_citation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("support_level", sa.String(32), nullable=False),
        sa.Column("validation_status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    for table in (
        "ai_response_citations",
        "ai_message_feedback",
        "ai_action_items",
        "ai_human_referrals",
        "ai_service_recommendations",
        "ai_tool_executions",
        "ai_tool_confirmations",
    ):
        op.drop_table(table)
