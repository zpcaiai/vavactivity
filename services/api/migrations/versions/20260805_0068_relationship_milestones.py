"""Add participant-authored relationship milestones.

Revision ID: 20260805_0068
Revises: 20260805_0067
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0068"
down_revision = "20260805_0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE relationship_milestones (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_id UUID NOT NULL REFERENCES relationship_journeys(id) ON DELETE CASCADE,
      created_by_user_id UUID NOT NULL REFERENCES users(id),
      milestone_type VARCHAR(64) NOT NULL,
      title VARCHAR(160) NOT NULL,
      description_encrypted TEXT,
      visibility VARCHAR(32) NOT NULL DEFAULT 'shared',
      occurred_on DATE,
      source_entity_type VARCHAR(64),
      source_entity_id UUID,
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      deleted_at TIMESTAMPTZ,
      CHECK (visibility IN ('private','shared')),
      CHECK (status IN ('active','deleted'))
    )
    """)
    op.execute(
        "CREATE INDEX ix_relationship_milestones_journey "
        "ON relationship_milestones(journey_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE relationship_milestones")
