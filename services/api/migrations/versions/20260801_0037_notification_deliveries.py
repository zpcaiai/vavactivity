"""Add in-app notifications, deliveries, attempts and dead letters.

Revision ID: 20260801_0037
Revises: 20260801_0036
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0037"
down_revision = "20260801_0036"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE user_notifications (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      notification_intent_id UUID NOT NULL REFERENCES notification_intents(id),
      category VARCHAR(64) NOT NULL, priority VARCHAR(32) NOT NULL,
      title VARCHAR(300) NOT NULL, body TEXT NOT NULL, action_type VARCHAR(64),
      action_reference JSONB, action_url VARCHAR(1000), status VARCHAR(32) NOT NULL DEFAULT 'active',
      available_from TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ,
      read_at TIMESTAMPTZ, archived_at TIMESTAMPTZ, withdrawn_at TIMESTAMPTZ,
      template_release_id UUID REFERENCES notification_template_releases(id),
      rendering_snapshot JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id, notification_intent_id)
    );
    CREATE INDEX ix_user_notifications_list ON user_notifications(user_id, status, created_at DESC);
    CREATE TABLE notification_deliveries (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      notification_intent_id UUID NOT NULL REFERENCES notification_intents(id),
      user_id UUID REFERENCES users(id), channel VARCHAR(32) NOT NULL,
      priority VARCHAR(32) NOT NULL DEFAULT 'normal', destination_encrypted TEXT,
      destination_hash VARCHAR(128), template_release_id UUID NOT NULL REFERENCES notification_template_releases(id),
      locale VARCHAR(16) NOT NULL, subject_rendered_encrypted TEXT,
      body_html_rendered_encrypted TEXT, body_text_rendered_encrypted TEXT,
      rendering_checksum VARCHAR(128) NOT NULL, status VARCHAR(32) NOT NULL,
      provider VARCHAR(64), provider_message_id VARCHAR(255), scheduled_at TIMESTAMPTZ,
      first_attempt_at TIMESTAMPTZ, sent_at TIMESTAMPTZ, delivered_at TIMESTAMPTZ,
      attempt_count INTEGER NOT NULL DEFAULT 0, next_attempt_at TIMESTAMPTZ,
      expires_at TIMESTAMPTZ, deduplication_key VARCHAR(255) NOT NULL,
      processing_lease_until TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(channel, deduplication_key)
    );
    CREATE INDEX ix_notification_deliveries_due ON notification_deliveries(status, next_attempt_at, priority, created_at);
    CREATE TABLE notification_delivery_attempts (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), delivery_id UUID NOT NULL REFERENCES notification_deliveries(id),
      attempt_number INTEGER NOT NULL, provider VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL,
      provider_message_id VARCHAR(255), provider_response_code VARCHAR(128),
      request_metadata JSONB NOT NULL, response_metadata JSONB, error_class VARCHAR(64),
      error_code VARCHAR(128), error_message_safe TEXT, started_at TIMESTAMPTZ NOT NULL,
      completed_at TIMESTAMPTZ, UNIQUE(delivery_id, attempt_number)
    );
    CREATE TABLE notification_dead_letters (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), source_type VARCHAR(64) NOT NULL,
      source_id UUID NOT NULL, failure_stage VARCHAR(64) NOT NULL, error_code VARCHAR(128) NOT NULL,
      safe_error_context JSONB NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'open',
      assigned_to UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      resolved_at TIMESTAMPTZ, resolution_reason TEXT,
      UNIQUE(source_type, source_id, failure_stage, status)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE notification_dead_letters;
    DROP TABLE notification_delivery_attempts;
    DROP TABLE notification_deliveries;
    DROP TABLE user_notifications;
    """)
