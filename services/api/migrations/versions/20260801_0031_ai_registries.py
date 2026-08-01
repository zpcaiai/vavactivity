"""Add versioned AI model, prompt, safety and tool registries.

Revision ID: 20260801_0031
Revises: 20260731_0030
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260801_0031"
down_revision = "20260731_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_model_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("profile_code", sa.String(128), nullable=False, unique=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("model_revision", sa.String(128)),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("context_window_tokens", sa.Integer),
        sa.Column("maximum_output_tokens", sa.Integer),
        sa.Column("structured_output_supported", sa.Boolean, nullable=False),
        sa.Column("tool_calling_supported", sa.Boolean, nullable=False),
        sa.Column("input_cost_per_million_minor", sa.BigInteger),
        sa.Column("output_cost_per_million_minor", sa.BigInteger),
        sa.Column("cost_currency", sa.String(3)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "configuration", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "ai_model_routes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("route_code", sa.String(128), nullable=False, unique=True),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column(
            "primary_model_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_model_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "fallback_model_profile_ids",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("maximum_latency_ms", sa.Integer),
        sa.Column("maximum_cost_minor", sa.BigInteger),
        sa.Column(
            "retry_policy", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "routing_policy",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "ai_prompt_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("prompt_code", sa.String(128), nullable=False, unique=True),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("owner_team", sa.String(128)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "ai_prompt_releases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "prompt_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_prompt_definitions.id"),
            nullable=False,
        ),
        sa.Column("semantic_version", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(16)),
        sa.Column("template_content", sa.Text, nullable=False),
        sa.Column("input_schema", postgresql.JSONB, nullable=False),
        sa.Column("output_schema", postgresql.JSONB),
        sa.Column("safety_policy_version", sa.String(64)),
        sa.Column("tool_registry_version", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("prompt_definition_id", "semantic_version", "locale"),
    )
    op.create_table(
        "ai_safety_policies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("policy_code", sa.String(128), nullable=False),
        sa.Column("semantic_version", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("policy_definition", postgresql.JSONB, nullable=False),
        sa.Column("response_templates", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("policy_code", "semantic_version", "locale"),
    )
    op.create_table(
        "ai_tool_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tool_code", sa.String(128), nullable=False),
        sa.Column("semantic_version", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("input_schema", postgresql.JSONB, nullable=False),
        sa.Column("output_schema", postgresql.JSONB, nullable=False),
        sa.Column("risk_level", sa.String(32), nullable=False),
        sa.Column(
            "required_permissions",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "user_confirmation_required",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "idempotency_required", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column("timeout_seconds", sa.Integer, nullable=False),
        sa.Column("allowed_agent_profiles", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tool_code", "semantic_version"),
    )
    op.create_table(
        "ai_audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("details_encrypted", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    for table in (
        "ai_audit_events",
        "ai_tool_definitions",
        "ai_safety_policies",
        "ai_prompt_releases",
        "ai_prompt_definitions",
        "ai_model_routes",
        "ai_model_profiles",
    ):
        op.drop_table(table)
