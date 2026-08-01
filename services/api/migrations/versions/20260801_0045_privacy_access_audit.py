"""Add privacy break-glass and audit records.

Revision ID: 20260801_0045
Revises: 20260801_0044
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0045"
down_revision = "20260801_0044"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE privacy_break_glass_access (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), request_number VARCHAR(64) NOT NULL UNIQUE,
      requester_user_id UUID NOT NULL REFERENCES users(id), subject_user_id UUID NOT NULL REFERENCES users(id),
      data_scope JSONB NOT NULL, purpose VARCHAR(128) NOT NULL, reason_encrypted TEXT NOT NULL,
      status VARCHAR(32) NOT NULL, approved_by UUID REFERENCES users(id), approved_at TIMESTAMPTZ,
      expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE privacy_sensitive_access_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), actor_user_id UUID NOT NULL REFERENCES users(id),
      subject_user_id UUID NOT NULL REFERENCES users(id), module_code VARCHAR(64) NOT NULL,
      asset_code VARCHAR(128) NOT NULL, access_type VARCHAR(32) NOT NULL, purpose VARCHAR(128) NOT NULL,
      permission_code VARCHAR(128) NOT NULL, break_glass_access_id UUID REFERENCES privacy_break_glass_access(id),
      request_id UUID, result VARCHAR(32) NOT NULL, occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_sensitive_access_subject ON privacy_sensitive_access_events(subject_user_id,occurred_at DESC);
    CREATE TABLE privacy_audit_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), event_type VARCHAR(128) NOT NULL,
      actor_id UUID REFERENCES users(id), subject_type VARCHAR(64) NOT NULL, subject_id UUID,
      reason TEXT, safe_context JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_privacy_audit_event ON privacy_audit_events(event_type,created_at DESC);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE privacy_audit_events;
    DROP TABLE privacy_sensitive_access_events;
    DROP TABLE privacy_break_glass_access;
    """)
