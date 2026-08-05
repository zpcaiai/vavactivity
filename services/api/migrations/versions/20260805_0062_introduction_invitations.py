"""Add introduction invitations.

The partial unique index allows at most one pending invitation per match, so a
double submit or two devices cannot open a second one. ``invitation_version``
carries the optimistic lock that stops a stale client from accepting an
invitation that was already cancelled or expired.

Revision ID: 20260805_0062
Revises: 20260805_0061
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0062"
down_revision = "20260805_0061"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE matchmaking_introduction_invitations (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      invitation_number VARCHAR(64) NOT NULL UNIQUE,
      mutual_match_id UUID NOT NULL REFERENCES matchmaking_mutual_matches(id),
      pair_id UUID NOT NULL REFERENCES matchmaking_pairs(id),
      sender_user_id UUID NOT NULL REFERENCES users(id),
      recipient_user_id UUID NOT NULL REFERENCES users(id),
      status VARCHAR(32) NOT NULL DEFAULT 'pending',
      invitation_version INTEGER NOT NULL DEFAULT 1,
      message_encrypted TEXT,
      message_screening JSONB NOT NULL DEFAULT '{}'::jsonb,
      policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      idempotency_key VARCHAR(128) NOT NULL,
      sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ NOT NULL,
      accepted_at TIMESTAMPTZ,
      declined_at TIMESTAMPTZ,
      cancelled_at TIMESTAMPTZ,
      expired_at TIMESTAMPTZ,
      invalidated_at TIMESTAMPTZ,
      decline_reason_code VARCHAR(128),
      internal_invalidation_reason VARCHAR(128),
      relationship_handoff_id UUID,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (sender_user_id <> recipient_user_id),
      UNIQUE(sender_user_id, idempotency_key)
    );
    CREATE UNIQUE INDEX uq_active_invitation_per_match ON matchmaking_introduction_invitations(mutual_match_id) WHERE status = 'pending';
    CREATE INDEX ix_matchmaking_invitations_recipient ON matchmaking_introduction_invitations(recipient_user_id, status);
    CREATE INDEX ix_matchmaking_invitations_sender ON matchmaking_introduction_invitations(sender_user_id, status);
    CREATE INDEX ix_matchmaking_invitations_expiry ON matchmaking_introduction_invitations(expires_at) WHERE status = 'pending';

    CREATE TABLE matchmaking_pair_cooldowns (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      pair_id UUID NOT NULL REFERENCES matchmaking_pairs(id),
      cooldown_type VARCHAR(64) NOT NULL,
      reason_code VARCHAR(128),
      starts_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ NOT NULL,
      released_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX uq_matchmaking_pair_cooldown_active ON matchmaking_pair_cooldowns(pair_id, cooldown_type) WHERE released_at IS NULL;
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE matchmaking_pair_cooldowns;
    DROP TABLE matchmaking_introduction_invitations;
    """)
