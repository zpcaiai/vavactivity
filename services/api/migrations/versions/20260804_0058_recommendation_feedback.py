"""Add recommendation feedback events and user tuning profiles.

Revision ID: 20260804_0058
Revises: 20260804_0057
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0058"
down_revision = "20260804_0057"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE recommendation_feedback_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      viewer_user_id UUID NOT NULL REFERENCES users(id),
      recommended_user_id UUID NOT NULL REFERENCES users(id),
      recommendation_item_id UUID REFERENCES recommendation_items(id) ON DELETE SET NULL,
      candidate_pair_id UUID REFERENCES recommendation_candidate_pairs(id) ON DELETE SET NULL,
      feedback_type VARCHAR(64) NOT NULL,
      reason_code VARCHAR(128),
      reason_details_encrypted TEXT,
      source_module VARCHAR(64) NOT NULL,
      source_event_id UUID,
      occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      idempotency_key VARCHAR(128) NOT NULL,
      UNIQUE(viewer_user_id, idempotency_key)
    );
    CREATE INDEX ix_recommendation_feedback_viewer ON recommendation_feedback_events(viewer_user_id, feedback_type, occurred_at DESC);
    CREATE INDEX ix_recommendation_feedback_pair ON recommendation_feedback_events(viewer_user_id, recommended_user_id, occurred_at DESC);
    CREATE TABLE recommendation_user_tuning_profiles (
      user_id UUID PRIMARY KEY REFERENCES users(id),
      tuning_version INTEGER NOT NULL DEFAULT 1 CHECK(tuning_version > 0),
      feature_weight_adjustments JSONB NOT NULL DEFAULT '{}'::jsonb,
      exploration_level VARCHAR(32) NOT NULL DEFAULT 'balanced',
      feedback_personalization_enabled BOOLEAN NOT NULL DEFAULT true,
      daily_received_limit INTEGER,
      allow_relaxed_recommendations BOOLEAN NOT NULL DEFAULT false,
      recommendations_paused BOOLEAN NOT NULL DEFAULT false,
      derived_from_feedback_through TIMESTAMPTZ,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE recommendation_skip_cooldowns (
      viewer_user_id UUID NOT NULL REFERENCES users(id),
      skipped_user_id UUID NOT NULL REFERENCES users(id),
      reason_code VARCHAR(128),
      cooldown_until TIMESTAMPTZ NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (viewer_user_id, skipped_user_id)
    );
    CREATE INDEX ix_recommendation_skip_cooldown_until ON recommendation_skip_cooldowns(cooldown_until);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE recommendation_skip_cooldowns;
    DROP TABLE recommendation_user_tuning_profiles;
    DROP TABLE recommendation_feedback_events;
    """)
