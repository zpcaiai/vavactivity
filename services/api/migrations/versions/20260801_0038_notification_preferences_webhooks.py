"""Add notification preferences, consent, unsubscribe, Webhooks and suppression.

Revision ID: 20260801_0038
Revises: 20260801_0037
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0038"
down_revision = "20260801_0037"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE notification_preferences (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      category VARCHAR(64) NOT NULL, channel VARCHAR(32) NOT NULL, enabled BOOLEAN NOT NULL,
      frequency VARCHAR(32) NOT NULL DEFAULT 'immediate', quiet_hours_enabled BOOLEAN NOT NULL DEFAULT false,
      quiet_hours_start TIME, quiet_hours_end TIME, quiet_hours_timezone VARCHAR(64),
      source VARCHAR(32) NOT NULL, version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id, category, channel)
    );
    CREATE TABLE notification_consents (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      consent_type VARCHAR(64) NOT NULL, consent_version VARCHAR(32) NOT NULL,
      status VARCHAR(32) NOT NULL, granted_at TIMESTAMPTZ, withdrawn_at TIMESTAMPTZ,
      source VARCHAR(64) NOT NULL, evidence JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id, consent_type, consent_version)
    );
    CREATE TABLE notification_unsubscribe_tokens (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      category VARCHAR(64) NOT NULL, channel VARCHAR(32) NOT NULL, token_hash VARCHAR(128) NOT NULL UNIQUE,
      expires_at TIMESTAMPTZ, consumed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE notification_provider_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), provider VARCHAR(64) NOT NULL,
      provider_event_id VARCHAR(255) NOT NULL, event_type VARCHAR(64) NOT NULL,
      provider_message_id VARCHAR(255), signature_verified BOOLEAN NOT NULL,
      payload_encrypted JSONB NOT NULL, payload_hash VARCHAR(128) NOT NULL,
      processing_status VARCHAR(32) NOT NULL, received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      processed_at TIMESTAMPTZ, UNIQUE(provider, provider_event_id)
    );
    CREATE TABLE notification_suppressions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), destination_type VARCHAR(32) NOT NULL,
      destination_hash VARCHAR(128) NOT NULL, channel VARCHAR(32) NOT NULL,
      suppression_reason VARCHAR(64) NOT NULL, source VARCHAR(64) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ, lifted_at TIMESTAMPTZ, lifted_by UUID REFERENCES users(id),
      lift_reason TEXT
    );
    CREATE UNIQUE INDEX uq_notification_suppressions_active_destination
      ON notification_suppressions(destination_hash, channel, suppression_reason)
      WHERE status = 'active';
    CREATE TABLE notification_provider_health (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), provider VARCHAR(64) NOT NULL UNIQUE,
      circuit_state VARCHAR(32) NOT NULL DEFAULT 'closed', consecutive_failures INTEGER NOT NULL DEFAULT 0,
      recent_success_basis_points INTEGER NOT NULL DEFAULT 10000, p95_latency_ms INTEGER,
      rate_limit_basis_points INTEGER NOT NULL DEFAULT 0, server_error_basis_points INTEGER NOT NULL DEFAULT 0,
      last_success_at TIMESTAMPTZ, last_failure_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE notification_provider_health;
    DROP TABLE notification_suppressions;
    DROP TABLE notification_provider_events;
    DROP TABLE notification_unsubscribe_tokens;
    DROP TABLE notification_consents;
    DROP TABLE notification_preferences;
    """)
