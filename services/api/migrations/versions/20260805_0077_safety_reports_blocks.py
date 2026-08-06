"""Create safety reports, blocks and pair versions.

Revision ID: 20260805_0077
Revises: 20260805_0076
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0077"
down_revision = "20260805_0076"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE safety_reports (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      report_number VARCHAR(64) NOT NULL UNIQUE,
      reporter_user_id UUID NOT NULL REFERENCES users(id),
      reported_user_id UUID REFERENCES users(id),
      target_type VARCHAR(64) NOT NULL,
      target_reference_id UUID,
      category VARCHAR(64) NOT NULL,
      severity_claim VARCHAR(32),
      status VARCHAR(32) NOT NULL DEFAULT 'submitted',
      description_encrypted TEXT,
      user_safety_state JSONB NOT NULL DEFAULT '{}'::jsonb,
      block_requested BOOLEAN NOT NULL DEFAULT FALSE,
      immediate_danger_claimed BOOLEAN NOT NULL DEFAULT FALSE,
      source_context JSONB NOT NULL DEFAULT '{}'::jsonb,
      idempotency_key VARCHAR(128) NOT NULL,
      submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      closed_at TIMESTAMPTZ,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version INTEGER NOT NULL DEFAULT 1,
      UNIQUE(reporter_user_id, idempotency_key),
      CHECK (reported_user_id IS NULL OR reporter_user_id <> reported_user_id),
      CHECK (status IN ('submitted','triaged','in_review','action_taken','closed','withdrawn'))
    );
    CREATE TABLE user_blocks (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      blocker_user_id UUID NOT NULL REFERENCES users(id),
      blocked_user_id UUID NOT NULL REFERENCES users(id),
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      source VARCHAR(32) NOT NULL DEFAULT 'user',
      source_report_id UUID REFERENCES safety_reports(id),
      reason_code VARCHAR(128),
      private_reason_encrypted TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      lifted_at TIMESTAMPTZ,
      version INTEGER NOT NULL DEFAULT 1,
      CHECK (blocker_user_id <> blocked_user_id),
      CHECK (status IN ('active','lifted'))
    );
    CREATE UNIQUE INDEX uq_active_user_block ON user_blocks(blocker_user_id,blocked_user_id) WHERE status='active';
    CREATE INDEX ix_user_blocks_blocked ON user_blocks(blocked_user_id,status);
    CREATE TABLE safety_pair_versions (
      user_low_id UUID NOT NULL REFERENCES users(id),
      user_high_id UUID NOT NULL REFERENCES users(id),
      restriction_version INTEGER NOT NULL DEFAULT 1,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(user_low_id,user_high_id),
      CHECK (user_low_id::text < user_high_id::text)
    );
    CREATE TABLE safety_audit_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      actor_user_id UUID REFERENCES users(id),
      subject_user_id UUID REFERENCES users(id),
      event_type VARCHAR(128) NOT NULL,
      aggregate_type VARCHAR(64) NOT NULL,
      aggregate_id UUID,
      safe_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      request_id UUID,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_safety_reports_reporter ON safety_reports(reporter_user_id,submitted_at DESC);
    CREATE INDEX ix_safety_reports_queue ON safety_reports(status,immediate_danger_claimed,submitted_at);
    CREATE INDEX ix_safety_audit_subject ON safety_audit_events(subject_user_id,created_at DESC);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE safety_audit_events;
    DROP TABLE safety_pair_versions;
    DROP TABLE user_blocks;
    DROP TABLE safety_reports;
    """)
