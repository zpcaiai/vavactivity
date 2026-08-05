"""Add versioned stage registry and mutual stage proposals.

Revision ID: 20260805_0066
Revises: 20260805_0065
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0066"
down_revision = "20260805_0065"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE relationship_stage_registries (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      registry_code VARCHAR(64) NOT NULL,
      registry_version VARCHAR(64) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'draft',
      manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
      policy JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_by UUID REFERENCES users(id),
      approved_by UUID REFERENCES users(id),
      approved_at TIMESTAMPTZ,
      activated_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(registry_code, registry_version)
    );

    CREATE TABLE relationship_stage_proposals (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_id UUID NOT NULL REFERENCES relationship_journeys(id) ON DELETE CASCADE,
      proposer_user_id UUID NOT NULL REFERENCES users(id),
      recipient_user_id UUID NOT NULL REFERENCES users(id),
      from_stage_code VARCHAR(64) NOT NULL,
      to_stage_code VARCHAR(64) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'pending',
      message_encrypted TEXT,
      policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      idempotency_key VARCHAR(128) NOT NULL,
      proposed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ NOT NULL,
      accepted_at TIMESTAMPTZ,
      declined_at TIMESTAMPTZ,
      cancelled_at TIMESTAMPTZ,
      invalidated_at TIMESTAMPTZ,
      decline_reason_code VARCHAR(128),
      version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (proposer_user_id <> recipient_user_id),
      CHECK (status IN ('pending','accepted','declined','cancelled','expired','invalidated')),
      UNIQUE(proposer_user_id, idempotency_key)
    );
    CREATE UNIQUE INDEX uq_relationship_pending_stage_proposal ON relationship_stage_proposals(journey_id) WHERE status='pending';
    CREATE INDEX ix_relationship_proposals_recipient ON relationship_stage_proposals(recipient_user_id, status);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE relationship_stage_proposals;
    DROP TABLE relationship_stage_registries;
    """)
