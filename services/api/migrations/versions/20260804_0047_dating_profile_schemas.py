"""Add versioned dating-profile schema releases, field definitions and taxonomies.

Revision ID: 20260804_0047
Revises: 20260801_0046
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0047"
down_revision = "20260801_0046"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE dating_profile_schema_releases (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      schema_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL,
      status VARCHAR(32) NOT NULL,
      field_manifest JSONB NOT NULL,
      completeness_policy JSONB NOT NULL,
      submission_policy JSONB NOT NULL,
      valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
      valid_until TIMESTAMPTZ,
      created_by UUID NOT NULL REFERENCES users(id),
      approved_by UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      approved_at TIMESTAMPTZ,
      UNIQUE(schema_code, semantic_version)
    );
    CREATE UNIQUE INDEX uq_active_dating_schema_release ON dating_profile_schema_releases(schema_code) WHERE status='active';
    CREATE TABLE dating_profile_field_definitions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      schema_release_id UUID NOT NULL REFERENCES dating_profile_schema_releases(id) ON DELETE CASCADE,
      field_code VARCHAR(128) NOT NULL,
      section_code VARCHAR(128) NOT NULL,
      field_type VARCHAR(64) NOT NULL,
      value_schema JSONB NOT NULL,
      required_for_submission BOOLEAN NOT NULL DEFAULT false,
      required_for_recommendation BOOLEAN NOT NULL DEFAULT false,
      sensitivity VARCHAR(32) NOT NULL,
      default_visibility VARCHAR(64) NOT NULL,
      searchable BOOLEAN NOT NULL DEFAULT false,
      recommendation_eligible BOOLEAN NOT NULL DEFAULT false,
      sort_order INTEGER NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(schema_release_id, field_code)
    );
    CREATE INDEX ix_dating_field_definitions_section ON dating_profile_field_definitions(schema_release_id, section_code, sort_order);
    CREATE TABLE dating_taxonomies (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      taxonomy_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL,
      status VARCHAR(32) NOT NULL,
      values_manifest JSONB NOT NULL,
      approved_by UUID REFERENCES users(id),
      approved_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(taxonomy_code, semantic_version)
    );
    CREATE UNIQUE INDEX uq_active_dating_taxonomy ON dating_taxonomies(taxonomy_code) WHERE status='active';
    CREATE TABLE dating_taxonomy_localizations (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      taxonomy_id UUID NOT NULL REFERENCES dating_taxonomies(id) ON DELETE CASCADE,
      value_code VARCHAR(128) NOT NULL,
      locale VARCHAR(16) NOT NULL,
      label VARCHAR(300) NOT NULL,
      description TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(taxonomy_id, value_code, locale)
    );
    """)
    op.execute("""
    CREATE FUNCTION protect_active_dating_schema_release() RETURNS trigger AS $$
    BEGIN
      IF OLD.status='active' AND (NEW.field_manifest IS DISTINCT FROM OLD.field_manifest
        OR NEW.completeness_policy IS DISTINCT FROM OLD.completeness_policy
        OR NEW.submission_policy IS DISTINCT FROM OLD.submission_policy
        OR NEW.semantic_version IS DISTINCT FROM OLD.semantic_version) THEN
        RAISE EXCEPTION 'active dating schema release content is immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER dating_schema_release_immutable BEFORE UPDATE ON dating_profile_schema_releases FOR EACH ROW EXECUTE FUNCTION protect_active_dating_schema_release()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS dating_schema_release_immutable ON dating_profile_schema_releases"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_active_dating_schema_release")
    _run("""
    DROP TABLE dating_taxonomy_localizations;
    DROP TABLE dating_taxonomies;
    DROP TABLE dating_profile_field_definitions;
    DROP TABLE dating_profile_schema_releases;
    """)
