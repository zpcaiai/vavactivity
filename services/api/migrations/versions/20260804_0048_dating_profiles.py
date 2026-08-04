"""Add dating profiles, immutable profile versions and core details.

Revision ID: 20260804_0048
Revises: 20260804_0047
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0048"
down_revision = "20260804_0047"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE dating_profiles (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL UNIQUE REFERENCES users(id),
      profile_number VARCHAR(64) NOT NULL UNIQUE,
      status VARCHAR(32) NOT NULL DEFAULT 'draft',
      review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
      schema_release_id UUID NOT NULL REFERENCES dating_profile_schema_releases(id),
      default_locale VARCHAR(16) NOT NULL,
      relationship_intent VARCHAR(64),
      current_city_code VARCHAR(128),
      completeness_basis_points INTEGER NOT NULL DEFAULT 0 CHECK(completeness_basis_points BETWEEN 0 AND 10000),
      searchable BOOLEAN NOT NULL DEFAULT false,
      current_version_number INTEGER NOT NULL DEFAULT 1 CHECK(current_version_number > 0),
      approved_version_number INTEGER,
      submitted_at TIMESTAMPTZ,
      approved_at TIMESTAMPTZ,
      activated_at TIMESTAMPTZ,
      paused_at TIMESTAMPTZ,
      suspended_at TIMESTAMPTZ,
      suspension_reason_code VARCHAR(128),
      version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      archived_at TIMESTAMPTZ
    );
    CREATE INDEX ix_dating_profiles_status ON dating_profiles(status, updated_at DESC);
    CREATE INDEX ix_dating_profiles_review_status ON dating_profiles(review_status, submitted_at);
    CREATE TABLE dating_profile_versions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      dating_profile_id UUID NOT NULL REFERENCES dating_profiles(id) ON DELETE CASCADE,
      version_number INTEGER NOT NULL CHECK(version_number > 0),
      schema_release_id UUID NOT NULL REFERENCES dating_profile_schema_releases(id),
      snapshot_encrypted TEXT NOT NULL,
      snapshot_checksum_sha256 VARCHAR(64) NOT NULL,
      change_summary TEXT NOT NULL,
      created_by UUID NOT NULL REFERENCES users(id),
      review_status VARCHAR(32) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      submitted_at TIMESTAMPTZ,
      approved_at TIMESTAMPTZ,
      UNIQUE(dating_profile_id, version_number)
    );
    CREATE INDEX ix_dating_profile_versions_review ON dating_profile_versions(review_status, submitted_at);
    CREATE TABLE dating_profile_core_details (
      dating_profile_id UUID PRIMARY KEY REFERENCES dating_profiles(id) ON DELETE CASCADE,
      date_of_birth_source VARCHAR(32) NOT NULL DEFAULT 'privacy_protected_profile',
      age_display_mode VARCHAR(32) NOT NULL DEFAULT 'exact_age',
      gender_code VARCHAR(64),
      eligible_partner_gender_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      country_code CHAR(2),
      region_code VARCHAR(128),
      city_code VARCHAR(128),
      citizenship_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      residence_status_code VARCHAR(128),
      relocation_willingness VARCHAR(64),
      primary_language_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      additional_language_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      education_level_code VARCHAR(128),
      occupation_category_code VARCHAR(128),
      height_cm INTEGER CHECK(height_cm IS NULL OR height_cm BETWEEN 100 AND 260),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("""
    CREATE FUNCTION protect_approved_dating_profile_version() RETURNS trigger AS $$
    BEGIN
      IF OLD.approved_at IS NOT NULL AND (
        NEW.snapshot_encrypted IS DISTINCT FROM OLD.snapshot_encrypted
        OR NEW.snapshot_checksum_sha256 IS DISTINCT FROM OLD.snapshot_checksum_sha256
        OR NEW.version_number IS DISTINCT FROM OLD.version_number) THEN
        RAISE EXCEPTION 'approved dating profile versions are immutable';
      END IF;
      IF OLD.submitted_at IS NOT NULL AND NEW.snapshot_checksum_sha256 IS DISTINCT FROM OLD.snapshot_checksum_sha256 THEN
        RAISE EXCEPTION 'submitted dating profile versions are immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER dating_profile_version_immutable BEFORE UPDATE ON dating_profile_versions FOR EACH ROW EXECUTE FUNCTION protect_approved_dating_profile_version()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS dating_profile_version_immutable ON dating_profile_versions")
    op.execute("DROP FUNCTION IF EXISTS protect_approved_dating_profile_version")
    _run("""
    DROP TABLE dating_profile_core_details;
    DROP TABLE dating_profile_versions;
    DROP TABLE dating_profiles;
    """)
