"""Create versioned membership plans.

Revision ID: 20260805_0071
Revises: 20260805_0070
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0071"
down_revision = "20260805_0070"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE membership_plans (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      plan_code VARCHAR(128) NOT NULL UNIQUE,
      internal_name VARCHAR(200) NOT NULL,
      plan_type VARCHAR(32) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'draft',
      default_locale VARCHAR(16) NOT NULL DEFAULT 'en',
      current_version_id UUID,
      display_order INTEGER NOT NULL DEFAULT 0,
      featured BOOLEAN NOT NULL DEFAULT FALSE,
      created_by UUID NOT NULL REFERENCES users(id),
      updated_by UUID NOT NULL REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      archived_at TIMESTAMPTZ,
      CHECK (plan_type IN ('free','paid','trial','internal_grant')),
      CHECK (status IN ('draft','active','retired','archived'))
    );
    CREATE TABLE membership_plan_versions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      membership_plan_id UUID NOT NULL REFERENCES membership_plans(id),
      version_number INTEGER NOT NULL CHECK (version_number > 0),
      semantic_version VARCHAR(64) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'draft',
      benefit_manifest JSONB NOT NULL DEFAULT '[]'::jsonb,
      access_policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      quota_policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
      valid_until TIMESTAMPTZ,
      created_by UUID NOT NULL REFERENCES users(id),
      approved_by UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      approved_at TIMESTAMPTZ,
      activated_at TIMESTAMPTZ,
      UNIQUE(membership_plan_id, version_number),
      CHECK (status IN ('draft','review','approved','active','retired')),
      CHECK (valid_until IS NULL OR valid_from < valid_until)
    );
    ALTER TABLE membership_plans ADD CONSTRAINT fk_membership_current_version FOREIGN KEY (current_version_id) REFERENCES membership_plan_versions(id);
    CREATE TABLE membership_plan_localizations (
      membership_plan_version_id UUID NOT NULL REFERENCES membership_plan_versions(id) ON DELETE CASCADE,
      locale VARCHAR(16) NOT NULL,
      name VARCHAR(200) NOT NULL,
      short_description VARCHAR(500),
      description_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
      benefit_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
      limitation_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
      PRIMARY KEY(membership_plan_version_id, locale)
    );
    CREATE INDEX ix_membership_plans_public ON membership_plans(status, display_order);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE membership_plan_localizations;
    ALTER TABLE membership_plans DROP CONSTRAINT fk_membership_current_version;
    DROP TABLE membership_plan_versions;
    DROP TABLE membership_plans;
    """)
