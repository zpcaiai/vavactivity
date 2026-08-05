"""Add interaction history, inbox, idempotency records and audit events.

History is append-only and stores status transitions with controlled metadata.
It never stores a full skip reason, an invitation body or a contact value —
those live in their own encrypted columns, so a safety investigation can
reconstruct what happened without the timeline itself becoming a leak.

Revision ID: 20260805_0064
Revises: 20260805_0063
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0064"
down_revision = "20260805_0063"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE matchmaking_interaction_history (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      pair_id UUID NOT NULL REFERENCES matchmaking_pairs(id),
      actor_user_id UUID REFERENCES users(id),
      entity_type VARCHAR(64) NOT NULL,
      entity_id UUID,
      action VARCHAR(64) NOT NULL,
      from_status VARCHAR(32),
      to_status VARCHAR(32),
      reason_code VARCHAR(128),
      safe_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      request_id UUID,
      occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_matchmaking_history_pair ON matchmaking_interaction_history(pair_id, occurred_at DESC);
    CREATE INDEX ix_matchmaking_history_entity ON matchmaking_interaction_history(entity_type, entity_id);

    CREATE TABLE matchmaking_interaction_inbox_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      source_module VARCHAR(64) NOT NULL,
      source_event_id UUID NOT NULL,
      event_type VARCHAR(128) NOT NULL,
      event_version INTEGER NOT NULL DEFAULT 1,
      payload JSONB NOT NULL DEFAULT '{}'::jsonb,
      status VARCHAR(32) NOT NULL DEFAULT 'received',
      attempts INTEGER NOT NULL DEFAULT 0,
      received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      processed_at TIMESTAMPTZ,
      error_code VARCHAR(128),
      UNIQUE(source_module, source_event_id)
    );
    CREATE INDEX ix_matchmaking_inbox_pending ON matchmaking_interaction_inbox_events(status, received_at);

    CREATE TABLE matchmaking_idempotency_records (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL REFERENCES users(id),
      operation VARCHAR(64) NOT NULL,
      idempotency_key VARCHAR(128) NOT NULL,
      request_hash VARCHAR(128) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'in_progress',
      response_snapshot_encrypted JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      completed_at TIMESTAMPTZ,
      expires_at TIMESTAMPTZ NOT NULL,
      UNIQUE(user_id, operation, idempotency_key)
    );
    CREATE INDEX ix_matchmaking_idempotency_expiry ON matchmaking_idempotency_records(expires_at);

    CREATE TABLE matchmaking_interaction_audit_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      event_type VARCHAR(128) NOT NULL,
      actor_id UUID REFERENCES users(id),
      subject_type VARCHAR(64) NOT NULL,
      subject_id UUID,
      purpose VARCHAR(128),
      reason TEXT,
      safe_context JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_matchmaking_interaction_audit_type ON matchmaking_interaction_audit_events(event_type, created_at DESC);
    CREATE INDEX ix_matchmaking_interaction_audit_subject ON matchmaking_interaction_audit_events(subject_type, subject_id);

    CREATE TABLE matchmaking_interaction_dead_letters (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      inbox_event_id UUID REFERENCES matchmaking_interaction_inbox_events(id),
      event_type VARCHAR(128) NOT NULL,
      error_code VARCHAR(128) NOT NULL,
      error_detail TEXT,
      status VARCHAR(32) NOT NULL DEFAULT 'open',
      resolved_by UUID REFERENCES users(id),
      resolution_note TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      resolved_at TIMESTAMPTZ
    );
    CREATE INDEX ix_matchmaking_dead_letters_status ON matchmaking_interaction_dead_letters(status, created_at DESC);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE matchmaking_interaction_dead_letters;
    DROP TABLE matchmaking_interaction_audit_events;
    DROP TABLE matchmaking_idempotency_records;
    DROP TABLE matchmaking_interaction_inbox_events;
    DROP TABLE matchmaking_interaction_history;
    """)
