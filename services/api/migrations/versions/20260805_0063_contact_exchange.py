"""Add mutually confirmed contact exchange.

Consent is bound to a hash snapshot of the selected contact points. That is
what makes the consent specific: a member agrees to share *this* verified
value, and replacing it breaks the hash, suspends the grant and requires a
fresh confirmation instead of silently widening what was agreed.

Reveal tokens are stored hashed, are viewer scoped and are short lived, so a
leaked list response cannot be replayed into plaintext.

Revision ID: 20260805_0063
Revises: 20260805_0062
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0063"
down_revision = "20260805_0062"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE matchmaking_contact_exchange_requests (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      mutual_match_id UUID NOT NULL REFERENCES matchmaking_mutual_matches(id),
      invitation_id UUID NOT NULL REFERENCES matchmaking_introduction_invitations(id),
      pair_id UUID NOT NULL REFERENCES matchmaking_pairs(id),
      requested_by_user_id UUID NOT NULL REFERENCES users(id),
      status VARCHAR(32) NOT NULL DEFAULT 'requested',
      policy_version VARCHAR(64) NOT NULL,
      policy VARCHAR(64) NOT NULL DEFAULT 'mutual_confirmation_required',
      consent_version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      activated_at TIMESTAMPTZ,
      revoked_at TIMESTAMPTZ,
      invalidated_at TIMESTAMPTZ,
      UNIQUE(mutual_match_id)
    );
    CREATE INDEX ix_matchmaking_contact_requests_pair ON matchmaking_contact_exchange_requests(pair_id, status);

    CREATE TABLE matchmaking_contact_exchange_consents (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      contact_exchange_request_id UUID NOT NULL REFERENCES matchmaking_contact_exchange_requests(id),
      user_id UUID NOT NULL REFERENCES users(id),
      status VARCHAR(32) NOT NULL DEFAULT 'pending',
      selected_contact_point_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
      contact_point_hash_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      platform_only_preferred BOOLEAN NOT NULL DEFAULT false,
      consent_release_id UUID,
      consented_at TIMESTAMPTZ,
      withdrawn_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(contact_exchange_request_id, user_id)
    );

    CREATE TABLE matchmaking_contact_exchange_grants (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      contact_exchange_request_id UUID NOT NULL REFERENCES matchmaking_contact_exchange_requests(id),
      viewer_user_id UUID NOT NULL REFERENCES users(id),
      owner_user_id UUID NOT NULL REFERENCES users(id),
      contact_point_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
      contact_hash_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ,
      suspended_at TIMESTAMPTZ,
      revoked_at TIMESTAMPTZ,
      revoke_reason VARCHAR(128),
      CHECK (viewer_user_id <> owner_user_id),
      UNIQUE(contact_exchange_request_id, viewer_user_id, owner_user_id)
    );
    CREATE INDEX ix_matchmaking_contact_grants_viewer ON matchmaking_contact_exchange_grants(viewer_user_id, status);
    CREATE INDEX ix_matchmaking_contact_grants_owner ON matchmaking_contact_exchange_grants(owner_user_id, status);

    CREATE TABLE matchmaking_contact_reveal_tokens (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      grant_id UUID NOT NULL REFERENCES matchmaking_contact_exchange_grants(id),
      viewer_user_id UUID NOT NULL REFERENCES users(id),
      token_hash VARCHAR(128) NOT NULL UNIQUE,
      contact_point_id UUID NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'issued',
      issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ NOT NULL,
      consumed_at TIMESTAMPTZ,
      invalidated_at TIMESTAMPTZ
    );
    CREATE INDEX ix_matchmaking_reveal_tokens_grant ON matchmaking_contact_reveal_tokens(grant_id, status);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE matchmaking_contact_reveal_tokens;
    DROP TABLE matchmaking_contact_exchange_grants;
    DROP TABLE matchmaking_contact_exchange_consents;
    DROP TABLE matchmaking_contact_exchange_requests;
    """)
