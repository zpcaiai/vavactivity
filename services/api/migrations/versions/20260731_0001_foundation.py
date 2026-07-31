"""Create system foundation tables.

Revision ID: 20260731_0001
Revises:
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def common_columns() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "system_metadata",
        *common_columns(),
        sa.Column("key", postgresql.CITEXT(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "system_settings",
        *common_columns(),
        sa.Column("key", postgresql.CITEXT(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "outbox_events",
        *common_columns(),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.String(length=200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.create_index("ix_outbox_events_pending", "outbox_events", ["published_at", "created_at"])
    op.create_table(
        "idempotency_keys",
        *common_columns(),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_idempotency_scope_key", "idempotency_keys", ["scope", "key"], unique=True)
    op.create_table(
        "audit_events",
        *common_columns(),
        sa.Column("actor_id", sa.String(length=200), nullable=True),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("subject_type", sa.String(length=120), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_events_actor_created", "audit_events", ["actor_id", "created_at"])
    op.create_index(
        "ix_audit_events_subject_created",
        "audit_events",
        ["subject_type", "subject_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_audit_event_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_event_mutation")
    op.drop_index("ix_audit_events_subject_created", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("uq_idempotency_scope_key", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    op.drop_index("ix_outbox_events_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("system_settings")
    op.drop_table("system_metadata")
