# ruff: noqa: E501

"""Relationship status gate, free-attempt ledger, wait pool and delivery history.

Covers MATCH-001, MATCH-002 and MATCH-003.

Revision ID: 20260812_0096
Revises: 20260812_0095
"""

from alembic import op

revision = "20260812_0096"
down_revision = "20260812_0095"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE member_relationship_statuses (
          user_id UUID PRIMARY KEY REFERENCES users(id),
          status VARCHAR(32) NOT NULL DEFAULT 'undisclosed',
          source VARCHAR(32) NOT NULL DEFAULT 'self_declared',
          couple_relationship_id UUID,
          declared_at TIMESTAMPTZ,
          effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_by UUID REFERENCES users(id),
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('undisclosed','single','dating','engaged','married','separated','widowed')),
          CHECK (source IN ('self_declared','couple_binding','admin')),
          CHECK (source <> 'couple_binding' OR couple_relationship_id IS NOT NULL)
        );
        CREATE INDEX member_relationship_statuses_status_idx
          ON member_relationship_statuses (status);

        -- Append-only. A status change revokes access going forward; it never
        -- erases the record of what the status used to be (MATCH-001).
        CREATE TABLE member_relationship_status_history (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          from_status VARCHAR(32),
          to_status VARCHAR(32) NOT NULL,
          source VARCHAR(32) NOT NULL,
          reason TEXT,
          actor_id UUID REFERENCES users(id),
          actor_kind VARCHAR(16) NOT NULL,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (actor_kind IN ('member','admin','system'))
        );
        CREATE INDEX member_relationship_status_history_user_idx
          ON member_relationship_status_history (user_id, occurred_at DESC);

        CREATE TABLE matchmaking_entitlements (
          user_id UUID PRIMARY KEY REFERENCES users(id),
          granted INTEGER NOT NULL DEFAULT 0,
          consumed INTEGER NOT NULL DEFAULT 0,
          expires_at TIMESTAMPTZ,
          policy_version VARCHAR(64) NOT NULL DEFAULT 'dec-004-pending',
          -- Current de-duplication generation. Bumping this is how a reset
          -- takes effect; history rows from earlier generations are kept.
          delivery_reset_generation INTEGER NOT NULL DEFAULT 1,
          first_granted_at TIMESTAMPTZ,
          last_consumed_at TIMESTAMPTZ,
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (granted >= 0),
          CHECK (consumed >= 0),
          CHECK (consumed <= granted),
          CHECK (delivery_reset_generation >= 1)
        );

        -- Every balance change is one row. The unique idempotency key is what
        -- makes a retried generation impossible to double-charge (MATCH-002).
        CREATE TABLE matchmaking_entitlement_entries (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          delta INTEGER NOT NULL,
          reason VARCHAR(24) NOT NULL,
          idempotency_key VARCHAR(255) NOT NULL,
          batch_id UUID,
          granted_after INTEGER NOT NULL,
          consumed_after INTEGER NOT NULL,
          balance_after INTEGER NOT NULL,
          actor_id UUID REFERENCES users(id),
          actor_kind VARCHAR(16) NOT NULL DEFAULT 'system',
          note TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (idempotency_key),
          CHECK (reason IN ('grant','consume','refund','expire','admin_adjust')),
          CHECK (balance_after >= 0),
          CHECK (reason <> 'admin_adjust' OR note IS NOT NULL)
        );
        CREATE INDEX matchmaking_entitlement_entries_user_idx
          ON matchmaking_entitlement_entries (user_id, created_at DESC);

        CREATE TABLE matchmaking_wait_pool_entries (
          user_id UUID PRIMARY KEY REFERENCES users(id),
          status VARCHAR(16) NOT NULL DEFAULT 'waiting',
          entered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_notified_at TIMESTAMPTZ,
          notify_count INTEGER NOT NULL DEFAULT 0,
          last_opportunity_key VARCHAR(128),
          exited_at TIMESTAMPTZ,
          exit_reason VARCHAR(64),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('waiting','notified','exited')),
          CHECK (status <> 'exited' OR exited_at IS NOT NULL)
        );
        CREATE INDEX matchmaking_wait_pool_active_idx
          ON matchmaking_wait_pool_entries (status, entered_at) WHERE status <> 'exited';

        -- One row per (member, candidate) ever delivered. A reset writes a new
        -- reset_generation rather than deleting rows, so "why did I see this
        -- person again" always has an answer (MATCH-003).
        CREATE TABLE matchmaking_delivery_history (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          candidate_user_id UUID NOT NULL REFERENCES users(id),
          first_delivered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_delivered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          delivery_count INTEGER NOT NULL DEFAULT 1,
          first_batch_id UUID,
          reset_generation INTEGER NOT NULL DEFAULT 1,
          UNIQUE (user_id, candidate_user_id, reset_generation),
          CHECK (user_id <> candidate_user_id),
          CHECK (delivery_count >= 1)
        );
        CREATE INDEX matchmaking_delivery_history_user_idx
          ON matchmaking_delivery_history (user_id, reset_generation);

        CREATE TABLE matchmaking_delivery_resets (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          from_generation INTEGER NOT NULL,
          to_generation INTEGER NOT NULL,
          reason TEXT NOT NULL,
          actor_id UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (to_generation = from_generation + 1)
        );
        CREATE INDEX matchmaking_delivery_resets_user_idx
          ON matchmaking_delivery_resets (user_id, created_at DESC);

        -- V1.6 requires approved disclaimer copy on the recommendation surface.
        -- The table ships empty: no invented legal text (DEC-003 discipline).
        CREATE TABLE matchmaking_disclaimers (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          disclaimer_code VARCHAR(128) NOT NULL,
          semantic_version VARCHAR(32) NOT NULL,
          locale VARCHAR(16) NOT NULL,
          body TEXT NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          approved_by UUID REFERENCES users(id),
          approved_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (disclaimer_code, semantic_version, locale),
          CHECK (status IN ('draft','published','archived')),
          CHECK (status <> 'published' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
        );
        """
    )

    # Existing members have never answered the question, so they start
    # undisclosed and matchmaking stays closed until they say they are single.
    # Backfilling everyone to "single" would silently grant access nobody asked
    # for, which is exactly what MATCH-001 forbids.
    op.execute(
        """
        INSERT INTO member_relationship_statuses (user_id, status, source, effective_from)
        SELECT id, 'undisclosed', 'self_declared', now() FROM users
        ON CONFLICT (user_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS matchmaking_disclaimers;
        DROP TABLE IF EXISTS matchmaking_delivery_resets;
        DROP TABLE IF EXISTS matchmaking_delivery_history;
        DROP TABLE IF EXISTS matchmaking_wait_pool_entries;
        DROP TABLE IF EXISTS matchmaking_entitlement_entries;
        DROP TABLE IF EXISTS matchmaking_entitlements;
        DROP TABLE IF EXISTS member_relationship_status_history;
        DROP TABLE IF EXISTS member_relationship_statuses;
        """
    )
