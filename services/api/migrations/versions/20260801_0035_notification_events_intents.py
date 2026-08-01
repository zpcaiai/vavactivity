"""Add notification event inbox, subscriptions and intents.

Revision ID: 20260801_0035
Revises: 20260801_0034
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0035"
down_revision = "20260801_0034"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE notification_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), source_event_id UUID NOT NULL,
      source_module VARCHAR(64) NOT NULL, event_type VARCHAR(128) NOT NULL,
      event_version INTEGER NOT NULL, subject_type VARCHAR(64), subject_id UUID,
      payload_encrypted JSONB NOT NULL, payload_hash VARCHAR(128) NOT NULL,
      occurred_at TIMESTAMPTZ NOT NULL, received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      processing_status VARCHAR(32) NOT NULL, processed_at TIMESTAMPTZ, error_code VARCHAR(128),
      UNIQUE(source_module, source_event_id)
    );
    CREATE INDEX ix_notification_events_processing ON notification_events(processing_status, received_at);
    CREATE TABLE notification_event_subscriptions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), subscription_code VARCHAR(128) NOT NULL UNIQUE,
      source_event_type VARCHAR(128) NOT NULL, source_event_version INTEGER NOT NULL,
      notification_type VARCHAR(128) NOT NULL, category VARCHAR(64) NOT NULL,
      priority VARCHAR(32) NOT NULL, recipient_resolver_code VARCHAR(128) NOT NULL,
      template_code VARCHAR(128) NOT NULL, channel_policy JSONB NOT NULL,
      preference_policy VARCHAR(32) NOT NULL, scheduling_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
      deduplication_policy JSONB NOT NULL, status VARCHAR(32) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(source_event_type, source_event_version, subscription_code)
    );
    CREATE INDEX ix_notification_subscriptions_event ON notification_event_subscriptions(source_event_type, source_event_version, status);
    CREATE TABLE notification_intents (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      notification_event_id UUID REFERENCES notification_events(id),
      notification_type VARCHAR(128) NOT NULL, category VARCHAR(64) NOT NULL,
      priority VARCHAR(32) NOT NULL, recipient_type VARCHAR(32) NOT NULL,
      recipient_reference_id UUID, template_code VARCHAR(128) NOT NULL,
      channel_policy JSONB NOT NULL, preference_policy VARCHAR(32) NOT NULL,
      template_variables_encrypted TEXT NOT NULL, action_reference JSONB,
      deduplication_key VARCHAR(255) NOT NULL UNIQUE, expires_at TIMESTAMPTZ,
      status VARCHAR(32) NOT NULL DEFAULT 'created', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_notification_intents_recipient ON notification_intents(recipient_reference_id, created_at DESC);
    CREATE TABLE notification_audit_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), event_type VARCHAR(128) NOT NULL,
      actor_id UUID, subject_type VARCHAR(64) NOT NULL, subject_id UUID,
      reason TEXT, safe_context JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_notification_audit_created ON notification_audit_events(event_type, created_at DESC);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE notification_audit_events;
    DROP TABLE notification_intents;
    DROP TABLE notification_event_subscriptions;
    DROP TABLE notification_events;
    """)
