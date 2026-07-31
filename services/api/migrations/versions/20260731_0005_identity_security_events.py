"""Create append-only security events.

Revision ID: 20260731_0005
Revises: 20260731_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0005"
down_revision: str | None = "20260731_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("target_type", sa.String(64)),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column("request_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reason", sa.Text()),
        sa.Column("before_state", postgresql.JSONB()),
        sa.Column("after_state", postgresql.JSONB()),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("ip_address_hash", sa.String(128)),
        sa.Column("user_agent_hash", sa.String(128)),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_security_audit_event_type_occurred",
        "security_audit_events",
        ["event_type", "occurred_at"],
    )
    op.create_index(
        "ix_security_audit_target", "security_audit_events", ["target_type", "target_id"]
    )
    op.create_table(
        "login_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_hash", sa.String(128), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_login_attempt_request"),
    )
    op.create_index(
        "ix_login_attempt_email_created", "login_attempts", ["email_hash", "created_at"]
    )
    op.execute(
        """
        CREATE TRIGGER security_audit_events_append_only
        BEFORE UPDATE OR DELETE ON security_audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS security_audit_events_append_only ON security_audit_events")
    op.drop_index("ix_login_attempt_email_created", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index("ix_security_audit_target", table_name="security_audit_events")
    op.drop_index("ix_security_audit_event_type_occurred", table_name="security_audit_events")
    op.drop_table("security_audit_events")
