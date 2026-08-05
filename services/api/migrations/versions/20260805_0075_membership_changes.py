"""Create membership changes, trials, grants and adjustments.

Revision ID: 20260805_0075
Revises: 20260805_0074
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0075"
down_revision = "20260805_0074"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE membership_change_requests (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      membership_account_id UUID NOT NULL REFERENCES membership_accounts(id),
      user_id UUID NOT NULL REFERENCES users(id),
      change_type VARCHAR(32) NOT NULL,
      from_plan_version_id UUID NOT NULL REFERENCES membership_plan_versions(id),
      to_plan_version_id UUID NOT NULL REFERENCES membership_plan_versions(id),
      effective_policy VARCHAR(32) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'draft',
      commerce_quote_id UUID,
      commerce_change_reference_id UUID,
      pricing_snapshot JSONB,
      benefit_diff_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      quota_transition_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
      idempotency_key VARCHAR(128) NOT NULL,
      requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      confirmed_at TIMESTAMPTZ,
      effective_at TIMESTAMPTZ,
      applied_at TIMESTAMPTZ,
      failure_code VARCHAR(128),
      version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id, idempotency_key),
      CHECK (change_type IN ('upgrade','downgrade','billing_period_change','cancel','reactivate')),
      CHECK (effective_policy IN ('immediate','next_cycle','fixed_date')),
      CHECK (status IN ('draft','quoted','confirmation_required','confirmed','scheduled','processing','applied','cancelled','failed'))
    );
    CREATE TABLE membership_trial_policies (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      policy_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL,
      membership_plan_version_id UUID NOT NULL REFERENCES membership_plan_versions(id),
      duration_days INTEGER NOT NULL CHECK (duration_days > 0),
      eligibility_policy JSONB NOT NULL,
      requires_payment_method BOOLEAN NOT NULL DEFAULT FALSE,
      auto_converts BOOLEAN NOT NULL DEFAULT FALSE,
      status VARCHAR(32) NOT NULL DEFAULT 'draft',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(policy_code, semantic_version),
      CHECK (status IN ('draft','active','retired'))
    );
    CREATE TABLE membership_trial_history (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL REFERENCES users(id),
      policy_id UUID NOT NULL REFERENCES membership_trial_policies(id),
      membership_account_id UUID NOT NULL REFERENCES membership_accounts(id),
      started_at TIMESTAMPTZ NOT NULL,
      ended_at TIMESTAMPTZ,
      outcome VARCHAR(32),
      UNIQUE(user_id, policy_id)
    );
    CREATE TABLE membership_manual_grants (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL REFERENCES users(id),
      membership_plan_version_id UUID NOT NULL REFERENCES membership_plan_versions(id),
      grant_type VARCHAR(32) NOT NULL,
      reason_code VARCHAR(128) NOT NULL,
      reason_encrypted TEXT,
      starts_at TIMESTAMPTZ NOT NULL,
      expires_at TIMESTAMPTZ NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'pending_approval',
      granted_by UUID NOT NULL REFERENCES users(id),
      approved_by UUID REFERENCES users(id),
      membership_account_id UUID REFERENCES membership_accounts(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      revoked_at TIMESTAMPTZ,
      CHECK (grant_type IN ('customer_support','service_compensation','promotional','staff','migration')),
      CHECK (status IN ('pending_approval','approved','active','expired','revoked','rejected')),
      CHECK (starts_at < expires_at),
      CHECK (approved_by IS NULL OR approved_by <> granted_by)
    );
    CREATE TABLE membership_quota_adjustments (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      quota_bucket_id UUID NOT NULL REFERENCES membership_quota_buckets(id),
      adjustment_type VARCHAR(32) NOT NULL,
      quantity BIGINT NOT NULL CHECK (quantity <> 0),
      reason_code VARCHAR(128) NOT NULL,
      reason_encrypted TEXT,
      created_by UUID NOT NULL REFERENCES users(id),
      approved_by UUID REFERENCES users(id),
      idempotency_key VARCHAR(128) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'pending_approval',
      applied_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(quota_bucket_id, idempotency_key),
      CHECK (adjustment_type IN ('credit','debit','compensation','correction')),
      CHECK (status IN ('pending_approval','applied','rejected')),
      CHECK (approved_by IS NULL OR approved_by <> created_by)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE membership_quota_adjustments;
    DROP TABLE membership_manual_grants;
    DROP TABLE membership_trial_history;
    DROP TABLE membership_trial_policies;
    DROP TABLE membership_change_requests;
    """)
