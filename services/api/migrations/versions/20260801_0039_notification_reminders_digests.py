"""Add notification reminders, policies and digest items.

Revision ID: 20260801_0039
Revises: 20260801_0038
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0039"
down_revision = "20260801_0038"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE notification_reminder_policies (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), policy_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL, source_event_type VARCHAR(128) NOT NULL,
      reminder_rules JSONB NOT NULL, status VARCHAR(32) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(policy_code, semantic_version)
    );
    CREATE TABLE notification_reminders (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), reminder_type VARCHAR(128) NOT NULL,
      subject_type VARCHAR(64) NOT NULL, subject_id UUID NOT NULL,
      recipient_user_id UUID NOT NULL REFERENCES users(id), template_code VARCHAR(128) NOT NULL,
      category VARCHAR(64) NOT NULL, trigger_at TIMESTAMPTZ NOT NULL, timezone VARCHAR(64) NOT NULL,
      trigger_reference_version INTEGER NOT NULL, status VARCHAR(32) NOT NULL,
      deduplication_key VARCHAR(255) NOT NULL UNIQUE,
      dispatched_intent_id UUID REFERENCES notification_intents(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_notification_reminders_due ON notification_reminders(status, trigger_at);
    CREATE TABLE notification_digest_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      category VARCHAR(64) NOT NULL, notification_intent_id UUID NOT NULL REFERENCES notification_intents(id),
      digest_frequency VARCHAR(32) NOT NULL, digest_window_key VARCHAR(128) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'pending', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id, notification_intent_id, digest_frequency)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE notification_digest_items;
    DROP TABLE notification_reminders;
    DROP TABLE notification_reminder_policies;
    """)
