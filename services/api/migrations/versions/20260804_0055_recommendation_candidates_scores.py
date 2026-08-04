"""Add the recommendation pool, normalised candidate pairs and directional scores.

Revision ID: 20260804_0055
Revises: 20260804_0054
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0055"
down_revision = "20260804_0054"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE recommendation_pool_entries (
      user_id UUID PRIMARY KEY REFERENCES users(id),
      dating_profile_id UUID NOT NULL REFERENCES dating_profiles(id) ON DELETE CASCADE,
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
      recommendations_paused BOOLEAN NOT NULL DEFAULT false,
      searchable_from TIMESTAMPTZ,
      searchable_until TIMESTAMPTZ,
      pool_version INTEGER NOT NULL DEFAULT 1,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_recommendation_pool_eligible ON recommendation_pool_entries(eligible, country_code, region_code);
    CREATE INDEX ix_recommendation_pool_age ON recommendation_pool_entries(eligible, age_years);
    CREATE TABLE recommendation_candidate_pairs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_low_id UUID NOT NULL REFERENCES users(id),
      user_high_id UUID NOT NULL REFERENCES users(id),
      low_profile_projection_version INTEGER NOT NULL,
      high_profile_projection_version INTEGER NOT NULL,
      low_preference_version INTEGER NOT NULL,
      high_preference_version INTEGER NOT NULL,
      strategy_id UUID NOT NULL REFERENCES recommendation_strategies(id),
      status VARCHAR(32) NOT NULL,
      eligibility_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      hard_constraint_snapshot JSONB,
      score_snapshot JSONB,
      generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      valid_until TIMESTAMPTZ,
      invalidated_at TIMESTAMPTZ,
      invalidation_reason VARCHAR(128),
      CHECK (user_low_id <> user_high_id),
      CHECK (user_low_id < user_high_id),
      UNIQUE(user_low_id, user_high_id, strategy_id, low_profile_projection_version,
             high_profile_projection_version, low_preference_version, high_preference_version)
    );
    CREATE INDEX ix_candidate_pairs_low ON recommendation_candidate_pairs(user_low_id, status) WHERE invalidated_at IS NULL;
    CREATE INDEX ix_candidate_pairs_high ON recommendation_candidate_pairs(user_high_id, status) WHERE invalidated_at IS NULL;
    CREATE TABLE recommendation_directional_scores (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      candidate_pair_id UUID NOT NULL REFERENCES recommendation_candidate_pairs(id) ON DELETE CASCADE,
      source_user_id UUID NOT NULL REFERENCES users(id),
      target_user_id UUID NOT NULL REFERENCES users(id),
      total_score_bps INTEGER NOT NULL CHECK(total_score_bps BETWEEN 0 AND 10000),
      confidence_bps INTEGER NOT NULL CHECK(confidence_bps BETWEEN 0 AND 10000),
      feature_scores JSONB NOT NULL DEFAULT '[]'::jsonb,
      missing_information JSONB NOT NULL DEFAULT '[]'::jsonb,
      unknown_feature_count INTEGER NOT NULL DEFAULT 0,
      scoring_policy_version VARCHAR(64) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(candidate_pair_id, source_user_id)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE recommendation_directional_scores;
    DROP TABLE recommendation_candidate_pairs;
    DROP TABLE recommendation_pool_entries;
    """)
