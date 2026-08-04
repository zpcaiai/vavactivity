"""Add de-identified recommendation projections for dating profiles.

Revision ID: 20260804_0053
Revises: 20260804_0052
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0053"
down_revision = "20260804_0052"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE dating_profile_recommendation_projections (
      dating_profile_id UUID PRIMARY KEY REFERENCES dating_profiles(id) ON DELETE CASCADE,
      user_id UUID NOT NULL UNIQUE REFERENCES users(id),
      approved_profile_version INTEGER NOT NULL,
      preference_version INTEGER NOT NULL,
      privacy_settings_version INTEGER NOT NULL,
      eligible BOOLEAN NOT NULL,
      ineligible_reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      age_bucket VARCHAR(32),
      age_years INTEGER,
      country_code CHAR(2),
      region_code VARCHAR(128),
      city_code VARCHAR(128),
      gender_code VARCHAR(64),
      eligible_partner_gender_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      faith_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      relationship_intent VARCHAR(64),
      marital_status_code VARCHAR(128),
      children_status_code VARCHAR(128),
      relocation_willingness VARCHAR(64),
      language_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      lifestyle_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      indexed_preference_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
      projection_checksum VARCHAR(64) NOT NULL,
      projection_version INTEGER NOT NULL DEFAULT 1 CHECK(projection_version > 0),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_dating_projection_eligible ON dating_profile_recommendation_projections(eligible, country_code, region_code);
    CREATE INDEX ix_dating_projection_age ON dating_profile_recommendation_projections(eligible, age_years);
    CREATE TABLE dating_profile_projection_jobs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      dating_profile_id UUID NOT NULL REFERENCES dating_profiles(id) ON DELETE CASCADE,
      trigger_event VARCHAR(128) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0,
      last_error TEXT,
      dedupe_key VARCHAR(200) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      processed_at TIMESTAMPTZ
    );
    CREATE UNIQUE INDEX uq_dating_projection_job_pending ON dating_profile_projection_jobs(dedupe_key) WHERE status='pending';
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE dating_profile_projection_jobs;
    DROP TABLE dating_profile_recommendation_projections;
    """)
