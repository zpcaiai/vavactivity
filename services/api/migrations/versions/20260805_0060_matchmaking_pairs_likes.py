"""Add canonical matchmaking pairs and directional likes.

A pair is one unordered row: the CHECK and the unique constraint together make
it impossible for (A, B) and (B, A) to become two pairs. The partial unique
index on likes is what makes a duplicate click impossible at the database
layer rather than something the application hopes to win a race against.

Revision ID: 20260805_0060
Revises: 20260804_0059
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0060"
down_revision = "20260804_0059"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE matchmaking_pairs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_low_id UUID NOT NULL REFERENCES users(id),
      user_high_id UUID NOT NULL REFERENCES users(id),
      status VARCHAR(32) NOT NULL DEFAULT 'interacting',
      recommendation_candidate_pair_id UUID,
      active_mutual_match_id UUID,
      restriction_version INTEGER NOT NULL DEFAULT 0,
      pair_version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (user_low_id::text < user_high_id::text),
      UNIQUE(user_low_id, user_high_id)
    );
    CREATE INDEX ix_matchmaking_pairs_low ON matchmaking_pairs(user_low_id, status);
    CREATE INDEX ix_matchmaking_pairs_high ON matchmaking_pairs(user_high_id, status);

    CREATE TABLE matchmaking_likes (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      pair_id UUID NOT NULL REFERENCES matchmaking_pairs(id),
      actor_user_id UUID NOT NULL REFERENCES users(id),
      target_user_id UUID NOT NULL REFERENCES users(id),
      source VARCHAR(32) NOT NULL DEFAULT 'recommendation',
      recommendation_item_id UUID REFERENCES recommendation_items(id),
      activity_mutual_choice_id UUID,
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      invalidation_reason_code VARCHAR(128),
      idempotency_key VARCHAR(128) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      matched_at TIMESTAMPTZ,
      withdrawn_at TIMESTAMPTZ,
      invalidated_at TIMESTAMPTZ,
      expires_at TIMESTAMPTZ,
      CHECK (actor_user_id <> target_user_id),
      UNIQUE(actor_user_id, idempotency_key)
    );
    CREATE UNIQUE INDEX uq_active_like_direction ON matchmaking_likes(actor_user_id, target_user_id) WHERE status IN ('active', 'matched');
    CREATE INDEX ix_matchmaking_likes_pair ON matchmaking_likes(pair_id, status);
    CREATE INDEX ix_matchmaking_likes_actor ON matchmaking_likes(actor_user_id, created_at DESC);
    CREATE INDEX ix_matchmaking_likes_item ON matchmaking_likes(recommendation_item_id);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE matchmaking_likes;
    DROP TABLE matchmaking_pairs;
    """)
