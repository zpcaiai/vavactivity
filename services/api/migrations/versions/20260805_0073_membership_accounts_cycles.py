"""Create membership projections, cycles and event inbox.

Revision ID: 20260805_0073
Revises: 20260805_0072
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0073"
down_revision = "20260805_0072"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE membership_sku_mappings (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      catalog_sku_id UUID NOT NULL UNIQUE REFERENCES product_skus(id),
      membership_plan_id UUID NOT NULL REFERENCES membership_plans(id),
      membership_plan_version_id UUID NOT NULL REFERENCES membership_plan_versions(id),
      billing_period VARCHAR(32) NOT NULL,
      trial_policy JSONB,
      grace_period_policy JSONB,
      valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
      valid_until TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (billing_period IN ('monthly','yearly','custom','none')),
      CHECK (valid_until IS NULL OR valid_from < valid_until)
    );
    CREATE TABLE membership_accounts (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL REFERENCES users(id),
      membership_plan_id UUID NOT NULL REFERENCES membership_plans(id),
      membership_plan_version_id UUID NOT NULL REFERENCES membership_plan_versions(id),
      status VARCHAR(32) NOT NULL,
      source_type VARCHAR(32) NOT NULL,
      catalog_sku_id UUID REFERENCES product_skus(id),
      commerce_subscription_id UUID REFERENCES subscriptions(id),
      entitlement_id UUID REFERENCES entitlements(id),
      current_cycle_id UUID,
      starts_at TIMESTAMPTZ NOT NULL,
      expires_at TIMESTAMPTZ,
      cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
      cancellation_effective_at TIMESTAMPTZ,
      grace_period_ends_at TIMESTAMPTZ,
      version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (status IN ('pending','active','trialing','grace_period','past_due','paused','cancel_scheduled','cancelled','expired','revoked')),
      CHECK (source_type IN ('free_default','paid_subscription','trial','admin_grant','compensation','migration')),
      CHECK (expires_at IS NULL OR starts_at < expires_at)
    );
    CREATE UNIQUE INDEX uq_current_active_paid_membership ON membership_accounts(user_id) WHERE source_type <> 'free_default' AND status IN ('active','trialing','grace_period','past_due','cancel_scheduled');
    CREATE UNIQUE INDEX uq_free_fallback_membership ON membership_accounts(user_id) WHERE source_type = 'free_default' AND status = 'active';
    CREATE UNIQUE INDEX uq_membership_commerce_subscription ON membership_accounts(commerce_subscription_id) WHERE commerce_subscription_id IS NOT NULL;
    CREATE TABLE membership_cycles (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      membership_account_id UUID NOT NULL REFERENCES membership_accounts(id) ON DELETE CASCADE,
      cycle_number INTEGER NOT NULL CHECK (cycle_number > 0),
      status VARCHAR(32) NOT NULL,
      starts_at TIMESTAMPTZ NOT NULL,
      ends_at TIMESTAMPTZ NOT NULL,
      source_subscription_period_start TIMESTAMPTZ,
      source_subscription_period_end TIMESTAMPTZ,
      quota_allocated_at TIMESTAMPTZ,
      closed_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(membership_account_id, cycle_number),
      CHECK (status IN ('scheduled','active','closed','expired','superseded')),
      CHECK (starts_at < ends_at)
    );
    ALTER TABLE membership_accounts ADD CONSTRAINT fk_membership_current_cycle FOREIGN KEY (current_cycle_id) REFERENCES membership_cycles(id);
    CREATE TABLE membership_benefit_grants (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      membership_account_id UUID NOT NULL REFERENCES membership_accounts(id) ON DELETE CASCADE,
      membership_cycle_id UUID REFERENCES membership_cycles(id),
      benefit_definition_id UUID NOT NULL REFERENCES membership_benefit_definitions(id),
      benefit_value JSONB NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      starts_at TIMESTAMPTZ NOT NULL,
      expires_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(membership_account_id, benefit_definition_id, starts_at),
      CHECK (status IN ('scheduled','active','closed','revoked'))
    );
    CREATE TABLE membership_inbox_events (
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
      UNIQUE(source_module, source_event_id),
      CHECK (status IN ('received','processing','processed','retry','dead_letter'))
    );
    CREATE INDEX ix_membership_accounts_user ON membership_accounts(user_id, status);
    CREATE INDEX ix_membership_inbox_pending ON membership_inbox_events(status, received_at);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE membership_inbox_events;
    DROP TABLE membership_benefit_grants;
    ALTER TABLE membership_accounts DROP CONSTRAINT fk_membership_current_cycle;
    DROP TABLE membership_cycles;
    DROP TABLE membership_accounts;
    DROP TABLE membership_sku_mappings;
    """)
