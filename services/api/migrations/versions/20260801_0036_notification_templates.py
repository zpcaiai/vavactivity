"""Add versioned multilingual notification templates.

Revision ID: 20260801_0036
Revises: 20260801_0035
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0036"
down_revision = "20260801_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE notification_template_definitions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), template_code VARCHAR(128) NOT NULL UNIQUE,
      internal_name VARCHAR(200) NOT NULL, category VARCHAR(64) NOT NULL,
      purpose VARCHAR(64) NOT NULL, variable_schema JSONB NOT NULL,
      required_channels JSONB NOT NULL DEFAULT '[]'::jsonb, supported_channels JSONB NOT NULL,
      status VARCHAR(32) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("""
    CREATE TABLE notification_template_releases (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      template_definition_id UUID NOT NULL REFERENCES notification_template_definitions(id),
      semantic_version VARCHAR(64) NOT NULL, locale VARCHAR(16) NOT NULL,
      channel VARCHAR(32) NOT NULL, subject_template TEXT, title_template TEXT,
      body_html_template TEXT, body_text_template TEXT NOT NULL,
      action_label_template TEXT, action_url_template TEXT, checksum_sha256 VARCHAR(64) NOT NULL,
      status VARCHAR(32) NOT NULL, created_by UUID NOT NULL REFERENCES users(id),
      approved_by UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      approved_at TIMESTAMPTZ, activated_at TIMESTAMPTZ,
      UNIQUE(template_definition_id, semantic_version, locale, channel)
    )
    """)
    op.execute("""
    CREATE INDEX ix_notification_template_active
    ON notification_template_releases(template_definition_id, locale, channel, status)
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION notification_template_release_immutable() RETURNS trigger AS $$
    BEGIN
      IF OLD.status IN ('active','superseded','revoked') AND
         (NEW.semantic_version,NEW.locale,NEW.channel,NEW.subject_template,NEW.title_template,
          NEW.body_html_template,NEW.body_text_template,NEW.action_label_template,
          NEW.action_url_template,NEW.checksum_sha256)
         IS DISTINCT FROM
         (OLD.semantic_version,OLD.locale,OLD.channel,OLD.subject_template,OLD.title_template,
          OLD.body_html_template,OLD.body_text_template,OLD.action_label_template,
          OLD.action_url_template,OLD.checksum_sha256) THEN
        RAISE EXCEPTION 'active notification template releases are immutable';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER trg_notification_template_release_immutable
      BEFORE UPDATE ON notification_template_releases FOR EACH ROW
      EXECUTE FUNCTION notification_template_release_immutable()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_notification_template_release_immutable ON notification_template_releases"
    )
    op.execute("DROP FUNCTION notification_template_release_immutable()")
    op.execute("DROP TABLE notification_template_releases")
    op.execute("DROP TABLE notification_template_definitions")
