"""Create commerce, payments, subscriptions and entitlements.

Revision ID: 20260731_0016
Revises: 20260731_0015
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0016"
down_revision: str | None = "20260731_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_statements(sql: str) -> None:
    """Execute portable single-statement DDL for asyncpg-backed Alembic."""
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _execute_statements(
        """
        CREATE TABLE orders (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          order_number VARCHAR(64) NOT NULL UNIQUE,
          user_id UUID NOT NULL REFERENCES users(id),
          status VARCHAR(32) NOT NULL,
          currency_code CHAR(3) NOT NULL,
          subtotal_minor BIGINT NOT NULL CHECK (subtotal_minor >= 0),
          discount_total_minor BIGINT NOT NULL CHECK (discount_total_minor >= 0),
          tax_total_minor BIGINT NOT NULL DEFAULT 0 CHECK (tax_total_minor >= 0),
          total_minor BIGINT NOT NULL CHECK (total_minor >= 0),
          refunded_total_minor BIGINT NOT NULL DEFAULT 0
            CHECK (refunded_total_minor >= 0 AND refunded_total_minor <= total_minor),
          pricing_quote_id UUID NOT NULL UNIQUE REFERENCES pricing_quotes(id),
          billing_email CITEXT NOT NULL,
          billing_name VARCHAR(200),
          locale VARCHAR(16) NOT NULL,
          region_code VARCHAR(64),
          placed_at TIMESTAMPTZ,
          paid_at TIMESTAMPTZ,
          fulfilled_at TIMESTAMPTZ,
          cancelled_at TIMESTAMPTZ,
          expired_at TIMESTAMPTZ,
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE carts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID REFERENCES users(id),
          anonymous_session_id UUID,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          currency_code CHAR(3) NOT NULL,
          expires_at TIMESTAMPTZ,
          converted_order_id UUID REFERENCES orders(id),
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK ((user_id IS NOT NULL) <> (anonymous_session_id IS NOT NULL))
        );
        CREATE UNIQUE INDEX uq_carts_active_user_currency
          ON carts(user_id, currency_code)
          WHERE status IN ('active', 'checkout_started') AND user_id IS NOT NULL;
        CREATE UNIQUE INDEX uq_carts_active_anonymous_currency
          ON carts(anonymous_session_id, currency_code)
          WHERE status IN ('active', 'checkout_started') AND anonymous_session_id IS NOT NULL;

        CREATE TABLE cart_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          cart_id UUID NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
          sku_id UUID NOT NULL REFERENCES product_skus(id),
          quantity INTEGER NOT NULL CHECK (quantity > 0),
          coupon_code VARCHAR(128),
          last_quote_id UUID REFERENCES pricing_quotes(id),
          added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(cart_id, sku_id)
        );

        CREATE TABLE order_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
          product_id UUID NOT NULL,
          sku_id UUID NOT NULL,
          price_id UUID NOT NULL,
          pricing_quote_id UUID NOT NULL UNIQUE REFERENCES pricing_quotes(id),
          product_code VARCHAR(128) NOT NULL,
          sku_code VARCHAR(128) NOT NULL,
          product_name_snapshot VARCHAR(300) NOT NULL,
          sku_name_snapshot VARCHAR(300) NOT NULL,
          product_type VARCHAR(64) NOT NULL,
          fulfillment_type VARCHAR(64) NOT NULL,
          quantity INTEGER NOT NULL CHECK (quantity > 0),
          unit_amount_minor BIGINT NOT NULL CHECK (unit_amount_minor >= 0),
          subtotal_minor BIGINT NOT NULL CHECK (subtotal_minor >= 0),
          discount_total_minor BIGINT NOT NULL CHECK (discount_total_minor >= 0),
          total_minor BIGINT NOT NULL CHECK (total_minor >= 0),
          fulfillment_snapshot JSONB NOT NULL,
          promotion_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(order_id, pricing_quote_id)
        );

        CREATE TABLE order_status_history (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
          from_status VARCHAR(32),
          to_status VARCHAR(32) NOT NULL,
          reason_code VARCHAR(128),
          reason TEXT,
          actor_type VARCHAR(32) NOT NULL,
          actor_user_id UUID,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_order_status_history_order_created
          ON order_status_history(order_id, created_at);

        ALTER TABLE inventory_reservations
          ADD COLUMN order_id UUID REFERENCES orders(id);
        ALTER TABLE coupon_redemption_reservations
          ADD COLUMN order_id UUID REFERENCES orders(id);
        CREATE UNIQUE INDEX uq_inventory_reservation_order_sku
          ON inventory_reservations(order_id, sku_id) WHERE order_id IS NOT NULL;
        CREATE UNIQUE INDEX uq_coupon_reservation_order_promotion
          ON coupon_redemption_reservations(order_id, promotion_id)
          WHERE order_id IS NOT NULL;

        CREATE TABLE payment_customers (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          provider VARCHAR(32) NOT NULL,
          provider_environment VARCHAR(16) NOT NULL,
          provider_customer_id VARCHAR(255) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(user_id, provider, provider_environment),
          UNIQUE(provider, provider_environment, provider_customer_id)
        );

        CREATE TABLE payment_attempts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          order_id UUID NOT NULL REFERENCES orders(id),
          provider VARCHAR(32) NOT NULL,
          provider_environment VARCHAR(16) NOT NULL,
          provider_payment_id VARCHAR(255),
          provider_customer_id VARCHAR(255),
          status VARCHAR(32) NOT NULL,
          amount_minor BIGINT NOT NULL CHECK (amount_minor >= 0),
          currency_code CHAR(3) NOT NULL,
          client_action JSONB,
          failure_code VARCHAR(128),
          failure_message_safe VARCHAR(500),
          idempotency_key VARCHAR(255) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(provider, provider_environment, idempotency_key),
          UNIQUE(provider, provider_environment, provider_payment_id)
        );

        CREATE TABLE payment_webhook_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          provider VARCHAR(32) NOT NULL,
          provider_environment VARCHAR(16) NOT NULL,
          provider_event_id VARCHAR(255) NOT NULL,
          event_type VARCHAR(255) NOT NULL,
          signature_verified BOOLEAN NOT NULL,
          payload JSONB NOT NULL,
          payload_hash VARCHAR(64) NOT NULL,
          processing_status VARCHAR(32) NOT NULL,
          received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          processed_at TIMESTAMPTZ,
          processing_attempts INTEGER NOT NULL DEFAULT 0,
          last_error_code VARCHAR(128),
          last_error_safe TEXT,
          UNIQUE(provider, provider_environment, provider_event_id)
        );

        CREATE TABLE subscriptions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          sku_id UUID NOT NULL REFERENCES product_skus(id),
          provider VARCHAR(32) NOT NULL,
          provider_environment VARCHAR(16) NOT NULL,
          provider_subscription_id VARCHAR(255) NOT NULL,
          status VARCHAR(32) NOT NULL,
          currency_code CHAR(3) NOT NULL,
          recurring_amount_minor BIGINT NOT NULL CHECK (recurring_amount_minor >= 0),
          billing_interval VARCHAR(32) NOT NULL,
          billing_interval_count INTEGER NOT NULL CHECK (billing_interval_count > 0),
          current_period_start TIMESTAMPTZ,
          current_period_end TIMESTAMPTZ,
          cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
          cancelled_at TIMESTAMPTZ,
          ended_at TIMESTAMPTZ,
          latest_order_id UUID REFERENCES orders(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(provider, provider_environment, provider_subscription_id)
        );

        CREATE TABLE subscription_billing_cycles (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          subscription_id UUID NOT NULL REFERENCES subscriptions(id),
          order_id UUID REFERENCES orders(id),
          provider_event_id VARCHAR(255) NOT NULL,
          status VARCHAR(32) NOT NULL,
          amount_minor BIGINT NOT NULL CHECK (amount_minor >= 0),
          currency_code CHAR(3) NOT NULL,
          period_start TIMESTAMPTZ,
          period_end TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(subscription_id, provider_event_id)
        );

        CREATE TABLE refunds (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          refund_number VARCHAR(64) NOT NULL UNIQUE,
          order_id UUID NOT NULL REFERENCES orders(id),
          payment_attempt_id UUID NOT NULL REFERENCES payment_attempts(id),
          provider VARCHAR(32) NOT NULL,
          provider_environment VARCHAR(16) NOT NULL,
          provider_refund_id VARCHAR(255),
          status VARCHAR(32) NOT NULL,
          amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
          currency_code CHAR(3) NOT NULL,
          reason_code VARCHAR(128) NOT NULL,
          reason TEXT NOT NULL,
          idempotency_key VARCHAR(255) NOT NULL,
          requested_by UUID NOT NULL REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          provider_submitted_at TIMESTAMPTZ,
          succeeded_at TIMESTAMPTZ,
          failed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(provider, provider_environment, idempotency_key),
          UNIQUE(provider, provider_environment, provider_refund_id)
        );

        CREATE TABLE refund_policy_snapshots (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          order_item_id UUID NOT NULL UNIQUE REFERENCES order_items(id),
          policy_code VARCHAR(128) NOT NULL,
          policy_version VARCHAR(32) NOT NULL,
          policy_snapshot JSONB NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE entitlements (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          order_id UUID NOT NULL REFERENCES orders(id),
          order_item_id UUID NOT NULL REFERENCES order_items(id),
          entitlement_type VARCHAR(64) NOT NULL,
          status VARCHAR(32) NOT NULL,
          resource_type VARCHAR(64),
          resource_id UUID,
          quantity_granted INTEGER,
          quantity_consumed INTEGER NOT NULL DEFAULT 0 CHECK (quantity_consumed >= 0),
          starts_at TIMESTAMPTZ,
          expires_at TIMESTAMPTZ,
          configuration_snapshot JSONB NOT NULL,
          activated_at TIMESTAMPTZ,
          suspended_at TIMESTAMPTZ,
          revoked_at TIMESTAMPTZ,
          revoke_reason VARCHAR(128),
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(order_item_id, entitlement_type),
          CHECK (quantity_granted IS NULL OR quantity_consumed <= quantity_granted)
        );

        CREATE TABLE entitlement_activation_jobs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          order_item_id UUID NOT NULL UNIQUE REFERENCES order_items(id),
          status VARCHAR(32) NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TIMESTAMPTZ,
          last_error_code VARCHAR(128),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE entitlement_consumptions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entitlement_id UUID NOT NULL REFERENCES entitlements(id),
          idempotency_key VARCHAR(255) NOT NULL,
          quantity INTEGER NOT NULL CHECK (quantity > 0),
          status VARCHAR(32) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(entitlement_id, idempotency_key)
        );

        CREATE TABLE payment_ledger_entries (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_type VARCHAR(64) NOT NULL,
          order_id UUID REFERENCES orders(id),
          payment_attempt_id UUID REFERENCES payment_attempts(id),
          refund_id UUID REFERENCES refunds(id),
          subscription_id UUID REFERENCES subscriptions(id),
          provider VARCHAR(32),
          provider_reference VARCHAR(255),
          currency_code CHAR(3) NOT NULL,
          amount_minor BIGINT NOT NULL,
          effective_at TIMESTAMPTZ NOT NULL,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE reconciliation_discrepancies (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          discrepancy_type VARCHAR(128) NOT NULL,
          severity VARCHAR(32) NOT NULL,
          provider VARCHAR(32),
          internal_reference_type VARCHAR(64),
          internal_reference_id UUID,
          provider_reference VARCHAR(255),
          expected_snapshot JSONB,
          actual_snapshot JSONB,
          status VARCHAR(32) NOT NULL DEFAULT 'open',
          assigned_to UUID REFERENCES users(id),
          detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ,
          resolution_reason TEXT
        );
        """
    )


def downgrade() -> None:
    _execute_statements(
        """
        DROP TABLE reconciliation_discrepancies;
        DROP TABLE payment_ledger_entries;
        DROP TABLE entitlement_consumptions;
        DROP TABLE entitlement_activation_jobs;
        DROP TABLE entitlements;
        DROP TABLE refund_policy_snapshots;
        DROP TABLE refunds;
        DROP TABLE subscription_billing_cycles;
        DROP TABLE subscriptions;
        DROP TABLE payment_webhook_events;
        DROP TABLE payment_attempts;
        DROP TABLE payment_customers;
        DROP INDEX uq_coupon_reservation_order_promotion;
        DROP INDEX uq_inventory_reservation_order_sku;
        ALTER TABLE coupon_redemption_reservations DROP COLUMN order_id;
        ALTER TABLE inventory_reservations DROP COLUMN order_id;
        DROP TABLE order_status_history;
        DROP TABLE order_items;
        DROP TABLE cart_items;
        DROP TABLE carts;
        DROP TABLE orders;
        """
    )
