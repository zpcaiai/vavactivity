"""Add skips, mutual matches and match sources.

UNIQUE(pair_id) on the mutual match is the final duplicate boundary: two
members clicking at the same moment contend on the pair row, and if the
application ever loses that race the constraint still refuses the second row.

Revision ID: 20260805_0061
Revises: 20260805_0060
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0061"
down_revision = "20260805_0060"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE matchmaking_skips (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      pair_id UUID NOT NULL REFERENCES matchmaking_pairs(id),
      actor_user_id UUID NOT NULL REFERENCES users(id),
      target_user_id UUID NOT NULL REFERENCES users(id),
      recommendation_item_id UUID REFERENCES recommendation_items(id),
      skip_type VARCHAR(32) NOT NULL DEFAULT 'not_now',
      reason_code VARCHAR(128),
      reason_details_encrypted TEXT,
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      cooldown_until TIMESTAMPTZ,
      undo_available_until TIMESTAMPTZ,
      idempotency_key VARCHAR(128) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      withdrawn_at TIMESTAMPTZ,
      expired_at TIMESTAMPTZ,
      CHECK (actor_user_id <> target_user_id),
      UNIQUE(actor_user_id, idempotency_key)
    );
    CREATE UNIQUE INDEX uq_active_skip_direction ON matchmaking_skips(actor_user_id, target_user_id) WHERE status = 'active';
    CREATE INDEX ix_matchmaking_skips_pair ON matchmaking_skips(pair_id, status);
    CREATE INDEX ix_matchmaking_skips_cooldown ON matchmaking_skips(actor_user_id, cooldown_until);

    CREATE TABLE matchmaking_mutual_matches (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      match_number VARCHAR(64) NOT NULL UNIQUE,
      pair_id UUID NOT NULL REFERENCES matchmaking_pairs(id),
      user_low_id UUID NOT NULL REFERENCES users(id),
      user_high_id UUID NOT NULL REFERENCES users(id),
      source VARCHAR(32) NOT NULL DEFAULT 'recommendation',
      low_to_high_like_id UUID REFERENCES matchmaking_likes(id),
      high_to_low_like_id UUID REFERENCES matchmaking_likes(id),
      activity_mutual_choice_id UUID,
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      match_version INTEGER NOT NULL DEFAULT 1,
      matched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      closed_at TIMESTAMPTZ,
      invalidated_at TIMESTAMPTZ,
      closure_reason_code VARCHAR(128),
      closed_by_user_id UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (user_low_id::text < user_high_id::text),
      UNIQUE(pair_id)
    );
    CREATE INDEX ix_matchmaking_matches_low ON matchmaking_mutual_matches(user_low_id, status);
    CREATE INDEX ix_matchmaking_matches_high ON matchmaking_mutual_matches(user_high_id, status);

    CREATE TABLE matchmaking_match_sources (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      mutual_match_id UUID NOT NULL REFERENCES matchmaking_mutual_matches(id),
      source_type VARCHAR(32) NOT NULL,
      source_reference_id UUID NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(source_type, source_reference_id)
    );
    CREATE INDEX ix_matchmaking_match_sources_match ON matchmaking_match_sources(mutual_match_id);

    ALTER TABLE matchmaking_pairs
      ADD CONSTRAINT fk_matchmaking_pairs_active_match
      FOREIGN KEY (active_mutual_match_id) REFERENCES matchmaking_mutual_matches(id);
    """)


def downgrade() -> None:
    _run("""
    ALTER TABLE matchmaking_pairs DROP CONSTRAINT fk_matchmaking_pairs_active_match;
    DROP TABLE matchmaking_match_sources;
    DROP TABLE matchmaking_mutual_matches;
    DROP TABLE matchmaking_skips;
    """)
