"""Add governed operational notification campaigns.

Revision ID: 20260801_0040
Revises: 20260801_0039
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0040"
down_revision = "20260801_0039"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE notification_campaigns (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), campaign_code VARCHAR(128) NOT NULL UNIQUE,
      internal_name VARCHAR(300) NOT NULL, campaign_type VARCHAR(32) NOT NULL,
      category VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, template_code VARCHAR(128) NOT NULL,
      template_release_manifest JSONB NOT NULL, audience_definition JSONB NOT NULL,
      audience_snapshot_id UUID, channel_policy JSONB NOT NULL, scheduled_at TIMESTAMPTZ,
      rate_limit_per_minute INTEGER, batch_size INTEGER,
      test_send_completed_at TIMESTAMPTZ, release_reason TEXT,
      created_by UUID NOT NULL REFERENCES users(id), approved_by UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), approved_at TIMESTAMPTZ,
      started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
      paused_at TIMESTAMPTZ, cancelled_at TIMESTAMPTZ
    );
    CREATE TABLE notification_campaign_audiences (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), campaign_id UUID NOT NULL REFERENCES notification_campaigns(id),
      generated_at TIMESTAMPTZ NOT NULL DEFAULT now(), audience_definition_snapshot JSONB NOT NULL,
      total_candidates INTEGER NOT NULL, eligible_recipients INTEGER NOT NULL,
      suppressed_recipients INTEGER NOT NULL, locale_distribution JSONB NOT NULL DEFAULT '{}'::jsonb,
      region_distribution JSONB NOT NULL DEFAULT '{}'::jsonb, checksum_sha256 VARCHAR(64) NOT NULL,
      UNIQUE(campaign_id, checksum_sha256)
    );
    ALTER TABLE notification_campaigns ADD CONSTRAINT fk_notification_campaign_audience
      FOREIGN KEY (audience_snapshot_id) REFERENCES notification_campaign_audiences(id);
    CREATE TABLE notification_campaign_recipients (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), audience_id UUID NOT NULL REFERENCES notification_campaign_audiences(id),
      user_id UUID NOT NULL REFERENCES users(id), locale VARCHAR(16) NOT NULL,
      destination_hash VARCHAR(128), eligibility_snapshot JSONB NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'pending', notification_intent_id UUID REFERENCES notification_intents(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(audience_id, user_id)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE notification_campaign_recipients;
    ALTER TABLE notification_campaigns DROP CONSTRAINT fk_notification_campaign_audience;
    DROP TABLE notification_campaign_audiences;
    DROP TABLE notification_campaigns;
    """)
