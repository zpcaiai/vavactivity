"""Add canonical candidate pairs, directional scores and pair exclusions.

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
    CREATE TABLE recommendation_candidate_pairs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_low_id UUID NOT NULL REFERENCES users(id),
      user_high_id UUID NOT NULL REFERENCES users(id),
      low_profile_projection_version INTEGER NOT NULL,
      high_profile_projection_version INTEGER NOT NULL,
      low_preference_version INTEGER NOT NULL,
      high_preference_version INTEGER NOT NULL,
      strategy_id UUID NOT NULL REFERENCES recommendation_strategies(id),
      status VARCHAR(32) NOT NULL DEFAULT 'eligible',
      eligibility_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      hard_constraint_snapshot JSONB,
      score_snapshot JSONB,
      generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      valid_until TIMESTAMPTZ,
      invalidated_at TIMESTAMPTZ,
      invalidation_reason VARCHAR(128),
      CHECK (user_low_id <> user_high_id),
      CHECK (user_low_id::text < user_high_id::text),
      UNIQUE(
        user_low_id,
        user_high_id,
        strategy_id,
        low_profile_projection_version,
        high_profile_projection_version,
        low_preference_version,
        high_preference_version
      )
    );
    CREATE INDEX ix_recommendation_pair_low ON recommendation_candidate_pairs(user_low_id, status);
    CREATE INDEX ix_recommendation_pair_high ON recommendation_candidate_pairs(user_high_id, status);
    CREATE INDEX ix_recommendation_pair_validity ON recommendation_candidate_pairs(status, valid_until);

    CREATE TABLE recommendation_directional_scores (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      candidate_pair_id UUID NOT NULL REFERENCES recommendation_candidate_pairs(id) ON DELETE CASCADE,
      source_user_id UUID NOT NULL REFERENCES users(id),
      target_user_id UUID NOT NULL REFERENCES users(id),
      total_score_bps INTEGER NOT NULL CHECK(total_score_bps BETWEEN 0 AND 10000),
      confidence_bps INTEGER NOT NULL CHECK(confidence_bps BETWEEN 0 AND 10000),
      unknown_feature_count INTEGER NOT NULL DEFAULT 0,
      feature_scores JSONB NOT NULL DEFAULT '[]'::jsonb,
      missing_information JSONB NOT NULL DEFAULT '[]'::jsonb,
      satisfied_preferences JSONB NOT NULL DEFAULT '[]'::jsonb,
      scoring_policy_version VARCHAR(64) NOT NULL,
      feature_registry_version VARCHAR(64) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(candidate_pair_id, source_user_id, scoring_policy_version, feature_registry_version)
    );

    CREATE TABLE recommendation_pair_exclusions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_low_id UUID NOT NULL REFERENCES users(id),
      user_high_id UUID NOT NULL REFERENCES users(id),
      exclusion_type VARCHAR(64) NOT NULL,
      source_module VARCHAR(64) NOT NULL,
      reason_code VARCHAR(128),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ,
      released_at TIMESTAMPTZ,
      CHECK (user_low_id::text < user_high_id::text)
    );
    CREATE UNIQUE INDEX uq_recommendation_pair_exclusion_active ON recommendation_pair_exclusions(user_low_id, user_high_id, exclusion_type) WHERE released_at IS NULL;
    CREATE INDEX ix_recommendation_pair_exclusion_low ON recommendation_pair_exclusions(user_low_id, expires_at);
    CREATE INDEX ix_recommendation_pair_exclusion_high ON recommendation_pair_exclusions(user_high_id, expires_at);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE recommendation_pair_exclusions;
    DROP TABLE recommendation_directional_scores;
    DROP TABLE recommendation_candidate_pairs;
    """)
