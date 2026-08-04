"""Add partner-preference profiles and hard/soft criteria.

Revision ID: 20260804_0051
Revises: 20260804_0050
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0051"
down_revision = "20260804_0050"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE partner_preference_profiles (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL UNIQUE REFERENCES users(id),
      dating_profile_id UUID NOT NULL UNIQUE REFERENCES dating_profiles(id) ON DELETE CASCADE,
      status VARCHAR(32) NOT NULL DEFAULT 'draft',
      schema_release_id UUID NOT NULL REFERENCES dating_profile_schema_releases(id),
      preference_version INTEGER NOT NULL DEFAULT 1 CHECK(preference_version > 0),
      allow_recommendation_relaxation BOOLEAN NOT NULL DEFAULT false,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE partner_preference_criteria (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      partner_preference_profile_id UUID NOT NULL REFERENCES partner_preference_profiles(id) ON DELETE CASCADE,
      criterion_code VARCHAR(128) NOT NULL,
      operator VARCHAR(32) NOT NULL,
      desired_value JSONB NOT NULL,
      importance VARCHAR(32) NOT NULL,
      hard_constraint BOOLEAN NOT NULL DEFAULT false,
      allow_unknown BOOLEAN NOT NULL DEFAULT true,
      allow_system_relaxation BOOLEAN NOT NULL DEFAULT false,
      user_explanation TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(partner_preference_profile_id, criterion_code)
    );
    CREATE INDEX ix_partner_preference_criteria_hard ON partner_preference_criteria(partner_preference_profile_id, hard_constraint);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE partner_preference_criteria;
    DROP TABLE partner_preference_profiles;
    """)
