"""Add opt-in reminder plans, audit trail and delivery dead letters.

Revision ID: 20260805_0070
Revises: 20260805_0069
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0070"
down_revision = "20260805_0069"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE relationship_reminder_plans (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_id UUID NOT NULL REFERENCES relationship_journeys(id) ON DELETE CASCADE,
      participant_user_id UUID NOT NULL REFERENCES users(id),
      reminder_type VARCHAR(64) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      cadence_days INTEGER NOT NULL DEFAULT 30,
      next_due_at TIMESTAMPTZ,
      last_sent_at TIMESTAMPTZ,
      sent_this_month INTEGER NOT NULL DEFAULT 0,
      opt_in_recorded_at TIMESTAMPTZ NOT NULL,
      dedup_key VARCHAR(128) NOT NULL,
      policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(participant_user_id, dedup_key),
      CHECK (cadence_days >= 1),
      CHECK (status IN ('active','paused','cancelled','completed'))
    );
    CREATE INDEX ix_relationship_reminders_due ON relationship_reminder_plans(status, next_due_at);
    CREATE TABLE relationship_audit_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      event_type VARCHAR(128) NOT NULL,
      actor_id UUID REFERENCES users(id),
      journey_id UUID REFERENCES relationship_journeys(id),
      subject_type VARCHAR(64) NOT NULL,
      subject_id UUID,
      purpose VARCHAR(128),
      reason TEXT,
      safe_context JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_relationship_audit_journey ON relationship_audit_events(journey_id, created_at DESC);
    CREATE TABLE relationship_dead_letters (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      inbox_event_id UUID REFERENCES relationship_inbox_events(id),
      event_type VARCHAR(128) NOT NULL,
      error_code VARCHAR(128) NOT NULL,
      error_detail TEXT,
      status VARCHAR(32) NOT NULL DEFAULT 'open',
      resolved_by UUID REFERENCES users(id),
      resolution_note TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      resolved_at TIMESTAMPTZ
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE relationship_dead_letters;
    DROP TABLE relationship_audit_events;
    DROP TABLE relationship_reminder_plans;
    """)
