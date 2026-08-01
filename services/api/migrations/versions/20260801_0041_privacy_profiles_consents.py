"""Add privacy profiles, visibility and consent registry.

Revision ID: 20260801_0041
Revises: 20260801_0040
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0041"
down_revision = "20260801_0040"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE user_profiles (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL UNIQUE REFERENCES users(id),
      display_name VARCHAR(160), legal_name_encrypted TEXT, avatar_media_id UUID REFERENCES media_assets(id),
      date_of_birth_encrypted TEXT, gender_code VARCHAR(64), country_code CHAR(2), region VARCHAR(128),
      city VARCHAR(128), preferred_locale VARCHAR(16) NOT NULL, timezone VARCHAR(64) NOT NULL,
      public_bio VARCHAR(500), profile_status VARCHAR(32) NOT NULL DEFAULT 'incomplete',
      completeness_basis_points INTEGER NOT NULL DEFAULT 0 CHECK(completeness_basis_points BETWEEN 0 AND 10000),
      version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE user_contact_points (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      contact_type VARCHAR(32) NOT NULL, value_encrypted TEXT NOT NULL, value_hmac VARCHAR(128) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'pending_verification', verified_at TIMESTAMPTZ,
      is_primary BOOLEAN NOT NULL DEFAULT false, visibility VARCHAR(64) NOT NULL DEFAULT 'private',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id,contact_type,value_hmac)
    );
    CREATE UNIQUE INDEX uq_user_primary_contact_type ON user_contact_points(user_id,contact_type) WHERE is_primary=true;
    CREATE TABLE user_privacy_settings (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL UNIQUE REFERENCES users(id),
      searchable_by_platform_users BOOLEAN NOT NULL DEFAULT false,
      visible_in_activity_directory BOOLEAN NOT NULL DEFAULT false,
      visible_in_matchmaking BOOLEAN NOT NULL DEFAULT false,
      allow_contact_exchange_after_mutual_confirmation BOOLEAN NOT NULL DEFAULT false,
      allow_profile_use_by_ai BOOLEAN NOT NULL DEFAULT false,
      allow_service_history_use_by_ai BOOLEAN NOT NULL DEFAULT false,
      privacy_mode VARCHAR(32) NOT NULL DEFAULT 'strict', settings_version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE user_field_visibility_rules (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      data_domain VARCHAR(64) NOT NULL, field_code VARCHAR(128) NOT NULL,
      visibility VARCHAR(64) NOT NULL DEFAULT 'private', allowed_purposes JSONB NOT NULL DEFAULT '[]'::jsonb,
      allowed_recipient_types JSONB NOT NULL DEFAULT '[]'::jsonb,
      valid_from TIMESTAMPTZ NOT NULL DEFAULT now(), valid_until TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id,data_domain,field_code)
    );
    CREATE TABLE consent_definitions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), consent_code VARCHAR(128) NOT NULL UNIQUE,
      category VARCHAR(64) NOT NULL, required_for_service BOOLEAN NOT NULL, withdrawable BOOLEAN NOT NULL,
      scope_definition JSONB NOT NULL, evidence_requirements JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE consent_releases (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), consent_definition_id UUID NOT NULL REFERENCES consent_definitions(id),
      semantic_version VARCHAR(64) NOT NULL, locale VARCHAR(16) NOT NULL, title VARCHAR(300) NOT NULL,
      summary TEXT NOT NULL, full_text_content_id UUID, status VARCHAR(32) NOT NULL,
      valid_from TIMESTAMPTZ NOT NULL, valid_until TIMESTAMPTZ, checksum_sha256 VARCHAR(64) NOT NULL,
      approved_by UUID NOT NULL REFERENCES users(id), approved_at TIMESTAMPTZ NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(consent_definition_id,semantic_version,locale)
    );
    CREATE UNIQUE INDEX uq_active_consent_release_locale ON consent_releases(consent_definition_id,locale) WHERE status='active';
    CREATE TABLE user_consents (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      consent_definition_id UUID NOT NULL REFERENCES consent_definitions(id),
      consent_release_id UUID NOT NULL REFERENCES consent_releases(id), status VARCHAR(32) NOT NULL,
      scope_snapshot JSONB NOT NULL, source VARCHAR(64) NOT NULL, evidence JSONB NOT NULL,
      granted_at TIMESTAMPTZ, withdrawn_at TIMESTAMPTZ, expires_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX uq_current_user_consent ON user_consents(user_id,consent_definition_id) WHERE status='granted';
    CREATE INDEX ix_user_consents_history ON user_consents(user_id,created_at DESC);
    """)
    op.execute("""
    CREATE FUNCTION protect_active_consent_release() RETURNS trigger AS $$
    BEGIN
      IF OLD.status='active' AND (NEW.title IS DISTINCT FROM OLD.title OR NEW.summary IS DISTINCT FROM OLD.summary
        OR NEW.checksum_sha256 IS DISTINCT FROM OLD.checksum_sha256 OR NEW.semantic_version IS DISTINCT FROM OLD.semantic_version) THEN
        RAISE EXCEPTION 'active consent release content is immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER consent_release_immutable BEFORE UPDATE ON consent_releases FOR EACH ROW EXECUTE FUNCTION protect_active_consent_release()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS consent_release_immutable ON consent_releases")
    op.execute("DROP FUNCTION IF EXISTS protect_active_consent_release")
    _run("""
    DROP TABLE user_consents;
    DROP TABLE consent_releases;
    DROP TABLE consent_definitions;
    DROP TABLE user_field_visibility_rules;
    DROP TABLE user_privacy_settings;
    DROP TABLE user_contact_points;
    DROP TABLE user_profiles;
    """)
