"""Add recommendation strategies, feature definitions, pool entries and audit.

Revision ID: 20260804_0054
Revises: 20260804_0053
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0054"
down_revision = "20260804_0053"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE recommendation_strategies (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      strategy_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'draft',
      hard_constraint_policy JSONB NOT NULL,
      feature_manifest JSONB NOT NULL,
      scoring_policy JSONB NOT NULL,
      bidirectional_policy JSONB NOT NULL,
      ranking_policy JSONB NOT NULL,
      diversification_policy JSONB NOT NULL,
      exposure_policy JSONB NOT NULL,
      explanation_policy JSONB NOT NULL,
      cold_start_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
      applicable_regions JSONB NOT NULL DEFAULT '[]'::jsonb,
      applicable_segments JSONB NOT NULL DEFAULT '[]'::jsonb,
      evaluation_run_id UUID,
      created_by UUID REFERENCES users(id),
      approved_by UUID REFERENCES users(id),
      activated_by UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      approved_at TIMESTAMPTZ,
      activated_at TIMESTAMPTZ,
      UNIQUE(strategy_code, semantic_version)
    );
    CREATE UNIQUE INDEX uq_recommendation_strategy_active ON recommendation_strategies(strategy_code) WHERE status='active';

    CREATE TABLE recommendation_feature_definitions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      feature_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL,
      feature_group VARCHAR(64) NOT NULL,
      value_schema JSONB NOT NULL,
      scoring_function_code VARCHAR(128) NOT NULL,
      sensitivity VARCHAR(32) NOT NULL,
      explainable BOOLEAN NOT NULL DEFAULT true,
      user_configurable BOOLEAN NOT NULL DEFAULT true,
      default_weight INTEGER NOT NULL DEFAULT 0 CHECK(default_weight >= 0 AND default_weight <= 100),
      confidence_only BOOLEAN NOT NULL DEFAULT false,
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(feature_code, semantic_version)
    );

    CREATE TABLE recommendation_pool_entries (
      user_id UUID PRIMARY KEY REFERENCES users(id),
      dating_profile_id UUID NOT NULL,
      profile_projection_version INTEGER NOT NULL,
      preference_version INTEGER NOT NULL,
      privacy_settings_version INTEGER NOT NULL,
      country_code CHAR(2),
      region_code VARCHAR(128),
      city_code VARCHAR(128),
      age_bucket VARCHAR(32),
      age_years INTEGER,
      gender_code VARCHAR(64),
      eligible_partner_gender_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      relationship_intent VARCHAR(64),
      eligible BOOLEAN NOT NULL,
      eligibility_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
      stated_criteria_count INTEGER NOT NULL DEFAULT 0,
      approved_at TIMESTAMPTZ,
      searchable_from TIMESTAMPTZ,
      searchable_until TIMESTAMPTZ,
      pool_version INTEGER NOT NULL DEFAULT 1 CHECK(pool_version > 0),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_recommendation_pool_eligible ON recommendation_pool_entries(eligible, country_code, region_code);
    CREATE INDEX ix_recommendation_pool_age ON recommendation_pool_entries(eligible, age_years);
    CREATE INDEX ix_recommendation_pool_gender ON recommendation_pool_entries(eligible, gender_code);

    CREATE TABLE recommendation_audit_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      event_type VARCHAR(128) NOT NULL,
      actor_id UUID REFERENCES users(id),
      subject_type VARCHAR(64) NOT NULL,
      subject_id UUID,
      reason TEXT,
      safe_context JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_recommendation_audit_type ON recommendation_audit_events(event_type, created_at DESC);
    CREATE INDEX ix_recommendation_audit_subject ON recommendation_audit_events(subject_type, subject_id);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE recommendation_audit_events;
    DROP TABLE recommendation_pool_entries;
    DROP TABLE recommendation_feature_definitions;
    DROP TABLE recommendation_strategies;
    """)
