"""Add recommendation exposures and daily exposure budgets.

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
      source VARCHAR(32) NOT NULL,
      exposed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      duration_ms INTEGER,
      counted_as_visible BOOLEAN NOT NULL DEFAULT false,
      idempotency_key VARCHAR(128) NOT NULL,
      UNIQUE(viewer_user_id, idempotency_key)
    );
    CREATE INDEX ix_recommendation_exposures_pair ON recommendation_exposures(viewer_user_id, exposed_user_id, exposed_at DESC);
    CREATE INDEX ix_recommendation_exposures_exposed ON recommendation_exposures(exposed_user_id, exposed_at DESC);
    CREATE TABLE recommendation_exposure_budgets (
      user_id UUID NOT NULL REFERENCES users(id),
      budget_date DATE NOT NULL,
      daily_received_limit INTEGER NOT NULL,
      daily_shown_limit INTEGER NOT NULL,
      current_received_count INTEGER NOT NULL DEFAULT 0 CHECK(current_received_count >= 0),
      current_shown_count INTEGER NOT NULL DEFAULT 0 CHECK(current_shown_count >= 0),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, budget_date)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE recommendation_exposure_budgets;
    DROP TABLE recommendation_exposures;
    """)
