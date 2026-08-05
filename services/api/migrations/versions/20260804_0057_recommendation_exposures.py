"""Add exposure events, daily budgets and per-profile exposure counters.

Revision ID: 20260804_0057
Revises: 20260804_0056
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0057"
down_revision = "20260804_0056"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE recommendation_exposures (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      recommendation_item_id UUID NOT NULL REFERENCES recommendation_items(id) ON DELETE CASCADE,
      viewer_user_id UUID NOT NULL REFERENCES users(id),
      exposed_user_id UUID NOT NULL REFERENCES users(id),
      exposure_type VARCHAR(32) NOT NULL,
      exposure_sequence INTEGER NOT NULL DEFAULT 1,
      source VARCHAR(32) NOT NULL DEFAULT 'recommendation_list',
      counted_as_visible BOOLEAN NOT NULL DEFAULT false,
      exposed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      duration_ms INTEGER,
      idempotency_key VARCHAR(128) NOT NULL,
      UNIQUE(viewer_user_id, idempotency_key)
    );
    CREATE INDEX ix_recommendation_exposure_pair ON recommendation_exposures(viewer_user_id, exposed_user_id, exposed_at DESC);
    CREATE INDEX ix_recommendation_exposure_profile ON recommendation_exposures(exposed_user_id, exposed_at DESC);

    CREATE TABLE recommendation_exposure_budgets (
      user_id UUID NOT NULL REFERENCES users(id),
      budget_date DATE NOT NULL,
      daily_received_limit INTEGER NOT NULL CHECK(daily_received_limit >= 0),
      daily_shown_limit INTEGER NOT NULL CHECK(daily_shown_limit >= 0),
      current_received_count INTEGER NOT NULL DEFAULT 0 CHECK(current_received_count >= 0),
      current_shown_count INTEGER NOT NULL DEFAULT 0 CHECK(current_shown_count >= 0),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, budget_date)
    );

    CREATE TABLE recommendation_profile_exposure_stats (
      user_id UUID PRIMARY KEY REFERENCES users(id),
      total_exposures BIGINT NOT NULL DEFAULT 0,
      distinct_viewers BIGINT NOT NULL DEFAULT 0,
      first_exposed_at TIMESTAMPTZ,
      last_exposed_at TIMESTAMPTZ,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE recommendation_profile_exposure_stats;
    DROP TABLE recommendation_exposure_budgets;
    DROP TABLE recommendation_exposures;
    """)
