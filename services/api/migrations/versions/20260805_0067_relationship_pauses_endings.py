"""Add unilateral pauses/endings with mutual resume confirmation.

Revision ID: 20260805_0067
Revises: 20260805_0066
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0067"
down_revision = "20260805_0066"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE relationship_pauses (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_id UUID NOT NULL REFERENCES relationship_journeys(id) ON DELETE CASCADE,
      initiated_by_user_id UUID NOT NULL REFERENCES users(id),
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      private_reason_encrypted TEXT,
      user_visible_message_encrypted TEXT,
      policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      paused_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      resume_requested_by_user_id UUID REFERENCES users(id),
      resume_requested_at TIMESTAMPTZ,
      resume_accepted_by_user_id UUID REFERENCES users(id),
      resumed_at TIMESTAMPTZ,
      ended_at TIMESTAMPTZ,
      invalidated_at TIMESTAMPTZ,
      version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (status IN ('active','resume_requested','resumed','ended','invalidated'))
    );
    CREATE UNIQUE INDEX uq_relationship_active_pause ON relationship_pauses(journey_id) WHERE status IN ('active','resume_requested');

    CREATE TABLE relationship_endings (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_id UUID NOT NULL UNIQUE REFERENCES relationship_journeys(id) ON DELETE CASCADE,
      ended_by_user_id UUID REFERENCES users(id),
      status VARCHAR(32) NOT NULL DEFAULT 'confirmed',
      ending_type VARCHAR(64) NOT NULL DEFAULT 'member_ended',
      reason_code VARCHAR(128),
      private_reason_encrypted TEXT,
      user_visible_message_encrypted TEXT,
      policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      downstream_effects JSONB NOT NULL DEFAULT '{}'::jsonb,
      confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      processing_started_at TIMESTAMPTZ,
      completed_at TIMESTAMPTZ,
      version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (status IN ('confirmed','processing','completed','manual_review'))
    );

    ALTER TABLE relationship_journeys ADD CONSTRAINT fk_relationship_current_pause FOREIGN KEY (current_pause_id) REFERENCES relationship_pauses(id);
    ALTER TABLE relationship_journeys ADD CONSTRAINT fk_relationship_ending FOREIGN KEY (ending_record_id) REFERENCES relationship_endings(id);
    """)


def downgrade() -> None:
    _run("""
    ALTER TABLE relationship_journeys DROP CONSTRAINT fk_relationship_ending;
    ALTER TABLE relationship_journeys DROP CONSTRAINT fk_relationship_current_pause;
    DROP TABLE relationship_endings;
    DROP TABLE relationship_pauses;
    """)
