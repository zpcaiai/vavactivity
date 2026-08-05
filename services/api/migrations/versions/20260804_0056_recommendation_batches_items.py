"""Add recommendation batches, items and rank results.

Revision ID: 20260804_0056
Revises: 20260804_0055
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0056"
down_revision = "20260804_0055"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE recommendation_batches (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL REFERENCES users(id),
      batch_number BIGINT NOT NULL,
      batch_type VARCHAR(32) NOT NULL,
      strategy_id UUID NOT NULL REFERENCES recommendation_strategies(id),
      profile_projection_version INTEGER NOT NULL,
      preference_version INTEGER NOT NULL,
      privacy_settings_version INTEGER NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'building',
      requested_size INTEGER NOT NULL CHECK(requested_size > 0),
      generated_size INTEGER NOT NULL DEFAULT 0,
      ranking_seed VARCHAR(128) NOT NULL,
      period_key VARCHAR(64) NOT NULL,
      idempotency_key VARCHAR(160) NOT NULL,
      generated_at TIMESTAMPTZ,
      activated_at TIMESTAMPTZ,
      expires_at TIMESTAMPTZ,
      generation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id, batch_number),
      UNIQUE(user_id, idempotency_key)
    );
    CREATE INDEX ix_recommendation_batch_user_status ON recommendation_batches(user_id, status, created_at DESC);
    CREATE UNIQUE INDEX uq_recommendation_batch_active_period ON recommendation_batches(user_id, batch_type, period_key) WHERE status IN ('building','validating','ready','active');

    CREATE TABLE recommendation_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      recommendation_batch_id UUID NOT NULL REFERENCES recommendation_batches(id) ON DELETE CASCADE,
      viewer_user_id UUID NOT NULL REFERENCES users(id),
      recommended_user_id UUID NOT NULL REFERENCES users(id),
      candidate_pair_id UUID NOT NULL REFERENCES recommendation_candidate_pairs(id),
      candidate_projection_version INTEGER NOT NULL DEFAULT 0,
      candidate_privacy_version INTEGER NOT NULL DEFAULT 0,
      rank_position INTEGER NOT NULL CHECK(rank_position > 0),
      viewer_to_candidate_score_bps INTEGER NOT NULL CHECK(viewer_to_candidate_score_bps BETWEEN 0 AND 10000),
      candidate_to_viewer_score_bps INTEGER NOT NULL CHECK(candidate_to_viewer_score_bps BETWEEN 0 AND 10000),
      bidirectional_score_bps INTEGER NOT NULL CHECK(bidirectional_score_bps BETWEEN 0 AND 10000),
      confidence_bps INTEGER NOT NULL CHECK(confidence_bps BETWEEN 0 AND 10000),
      explanation_snapshot JSONB NOT NULL,
      visible_profile_snapshot JSONB NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'ready',
      available_from TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ,
      exposed_at TIMESTAMPTZ,
      viewed_at TIMESTAMPTZ,
      invalidated_at TIMESTAMPTZ,
      invalidation_reason VARCHAR(128),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(recommendation_batch_id, recommended_user_id),
      UNIQUE(recommendation_batch_id, rank_position)
    );
    CREATE INDEX ix_recommendation_item_viewer ON recommendation_items(viewer_user_id, status, rank_position);
    CREATE INDEX ix_recommendation_item_recommended ON recommendation_items(recommended_user_id, created_at DESC);

    CREATE TABLE recommendation_rank_results (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      recommendation_batch_id UUID NOT NULL REFERENCES recommendation_batches(id) ON DELETE CASCADE,
      candidate_pair_id UUID NOT NULL REFERENCES recommendation_candidate_pairs(id),
      base_score_bps INTEGER NOT NULL CHECK(base_score_bps BETWEEN 0 AND 10000),
      adjusted_score_bps INTEGER NOT NULL CHECK(adjusted_score_bps BETWEEN 0 AND 10000),
      novelty_adjustment_bps INTEGER NOT NULL DEFAULT 0,
      diversity_adjustment_bps INTEGER NOT NULL DEFAULT 0,
      exposure_adjustment_bps INTEGER NOT NULL DEFAULT 0,
      exploration_adjustment_bps INTEGER NOT NULL DEFAULT 0,
      final_rank INTEGER NOT NULL CHECK(final_rank > 0),
      adjustment_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(recommendation_batch_id, candidate_pair_id),
      UNIQUE(recommendation_batch_id, final_rank)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE recommendation_rank_results;
    DROP TABLE recommendation_items;
    DROP TABLE recommendation_batches;
    """)
