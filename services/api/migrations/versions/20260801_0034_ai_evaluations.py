"""Add pinned AI evaluation datasets, cases, runs and case results.

Revision ID: 20260801_0034
Revises: 20260801_0033
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260801_0034"
down_revision = "20260801_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_evaluation_datasets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("dataset_code", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(16)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "ai_evaluation_cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_evaluation_datasets.id"),
            nullable=False,
        ),
        sa.Column("case_code", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("difficulty", sa.String(32), nullable=False),
        sa.Column("initial_state_fixture", postgresql.JSONB, nullable=False),
        sa.Column("conversation_turns", postgresql.JSONB, nullable=False),
        sa.Column(
            "tool_fixtures", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("knowledge_fixture_reference", postgresql.JSONB),
        sa.Column("expected_classification", postgresql.JSONB),
        sa.Column("expected_risk_policy", postgresql.JSONB),
        sa.Column("expected_tool_calls", postgresql.JSONB),
        sa.Column(
            "forbidden_tool_calls",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "required_response_concepts",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "forbidden_response_concepts",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "expected_citation_ids",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("expected_referral_policy", postgresql.JSONB),
        sa.Column("human_rubric", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("dataset_id", "case_code"),
    )
    op.create_table(
        "ai_evaluation_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_evaluation_datasets.id"),
            nullable=False,
        ),
        sa.Column(
            "baseline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_evaluation_runs.id")
        ),
        sa.Column("graph_version", sa.String(64), nullable=False),
        sa.Column("prompt_release_manifest", postgresql.JSONB, nullable=False),
        sa.Column("model_route_manifest", postgresql.JSONB, nullable=False),
        sa.Column("tool_registry_version", sa.String(64), nullable=False),
        sa.Column("knowledge_index_manifest", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metrics", postgresql.JSONB),
        sa.Column(
            "serious_failures",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
    )
    op.create_table(
        "ai_evaluation_case_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_evaluation_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_evaluation_cases.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metrics", postgresql.JSONB, nullable=False),
        sa.Column(
            "failure_labels",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("trace_reference", sa.String(255)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("run_id", "case_id"),
    )


def downgrade() -> None:
    op.drop_table("ai_evaluation_case_results")
    op.drop_table("ai_evaluation_runs")
    op.drop_table("ai_evaluation_cases")
    op.drop_table("ai_evaluation_datasets")
