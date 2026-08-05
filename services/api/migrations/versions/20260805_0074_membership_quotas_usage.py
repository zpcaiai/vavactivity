"""Create atomic membership quota accounting.

Revision ID: 20260805_0074
Revises: 20260805_0073
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0074"
down_revision = "20260805_0073"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE membership_quota_buckets (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      membership_account_id UUID NOT NULL REFERENCES membership_accounts(id) ON DELETE CASCADE,
      membership_cycle_id UUID REFERENCES membership_cycles(id),
      benefit_code VARCHAR(128) NOT NULL,
      period_type VARCHAR(32) NOT NULL,
      period_starts_at TIMESTAMPTZ NOT NULL,
      period_ends_at TIMESTAMPTZ,
      allocated_quantity BIGINT NOT NULL CHECK (allocated_quantity >= 0),
      consumed_quantity BIGINT NOT NULL DEFAULT 0 CHECK (consumed_quantity >= 0),
      reserved_quantity BIGINT NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
      rollover_quantity BIGINT NOT NULL DEFAULT 0 CHECK (rollover_quantity >= 0),
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(membership_account_id, benefit_code, period_starts_at),
      CHECK (period_type IN ('membership_cycle','calendar_day','calendar_week','calendar_month','lifetime','one_time')),
      CHECK (status IN ('scheduled','active','closed','expired')),
      CHECK (period_ends_at IS NULL OR period_starts_at < period_ends_at),
      CHECK (consumed_quantity + reserved_quantity <= allocated_quantity + rollover_quantity)
    );
    CREATE TABLE membership_quota_ledger (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      quota_bucket_id UUID NOT NULL REFERENCES membership_quota_buckets(id),
      user_id UUID NOT NULL REFERENCES users(id),
      operation VARCHAR(32) NOT NULL,
      quantity BIGINT NOT NULL CHECK (quantity > 0),
      source_module VARCHAR(64) NOT NULL,
      source_reference_id UUID,
      idempotency_key VARCHAR(128) NOT NULL,
      before_snapshot JSONB NOT NULL,
      after_snapshot JSONB NOT NULL,
      occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(quota_bucket_id, idempotency_key),
      CHECK (operation IN ('allocate','reserve','consume','release','expire','adjust'))
    );
    CREATE TABLE membership_quota_reservations (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      quota_bucket_id UUID NOT NULL REFERENCES membership_quota_buckets(id),
      user_id UUID NOT NULL REFERENCES users(id),
      source_module VARCHAR(64) NOT NULL,
      source_reference_id UUID NOT NULL,
      quantity BIGINT NOT NULL CHECK (quantity > 0),
      status VARCHAR(32) NOT NULL DEFAULT 'reserved',
      idempotency_key VARCHAR(128) NOT NULL,
      reserved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ,
      consumed_at TIMESTAMPTZ,
      released_at TIMESTAMPTZ,
      UNIQUE(quota_bucket_id, idempotency_key),
      CHECK (status IN ('reserved','consumed','released','expired'))
    );
    CREATE INDEX ix_membership_quota_lookup ON membership_quota_buckets(membership_account_id, benefit_code, status);
    CREATE INDEX ix_membership_reservations_expiring ON membership_quota_reservations(status, expires_at);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE membership_quota_reservations;
    DROP TABLE membership_quota_ledger;
    DROP TABLE membership_quota_buckets;
    """)
