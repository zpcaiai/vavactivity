from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column

from vav.models.base import Base


def uuid_pk() -> MappedColumn[UUID]:
    return mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def created_at() -> MappedColumn[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def updated_at() -> MappedColumn[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Cart(Base):
    __tablename__ = "carts"
    __table_args__ = (
        Index(
            "uq_carts_active_user_currency",
            "user_id",
            "currency_code",
            unique=True,
            postgresql_where=text(
                "status IN ('active', 'checkout_started') AND user_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_carts_active_anonymous_currency",
            "anonymous_session_id",
            "currency_code",
            unique=True,
            postgresql_where=text(
                "status IN ('active', 'checkout_started') AND anonymous_session_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    anonymous_session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    converted_order_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id", use_alter=True)
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "sku_id"),)

    id: Mapped[UUID] = uuid_pk()
    cart_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_skus.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    coupon_code: Mapped[str | None] = mapped_column(String(128))
    last_quote_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pricing_quotes.id")
    )
    added_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[UUID] = uuid_pk()
    order_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_total_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refunded_total_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    pricing_quote_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pricing_quotes.id"), nullable=False, unique=True
    )
    billing_email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    billing_name: Mapped[str | None] = mapped_column(String(200))
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    region_code: Mapped[str | None] = mapped_column(String(64))
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (UniqueConstraint("order_id", "pricing_quote_id"),)

    id: Mapped[UUID] = uuid_pk()
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    sku_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    price_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pricing_quote_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pricing_quotes.id"), nullable=False, unique=True
    )
    product_code: Mapped[str] = mapped_column(String(128), nullable=False)
    sku_code: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(300), nullable=False)
    sku_name_snapshot: Mapped[str] = mapped_column(String(300), nullable=False)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    fulfillment_type: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fulfillment_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    promotion_snapshot: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"
    __table_args__ = (Index("ix_order_status_history_order_created", "order_id", "created_at"),)

    id: Mapped[UUID] = uuid_pk()
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    history_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()


class PaymentCustomer(Base):
    __tablename__ = "payment_customers"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "provider_environment"),
        UniqueConstraint("provider", "provider_environment", "provider_customer_id"),
    )

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_environment: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_environment", "idempotency_key"),
        UniqueConstraint("provider", "provider_environment", "provider_payment_id"),
    )

    id: Mapped[UUID] = uuid_pk()
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_environment: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255))
    provider_customer_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    client_action: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_message_safe: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (UniqueConstraint("provider", "provider_environment", "provider_event_id"),)

    id: Mapped[UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_environment: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = created_at()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    last_error_safe: Mapped[str | None] = mapped_column(Text)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("provider", "provider_environment", "provider_subscription_id"),
    )

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    sku_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_skus.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_environment: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_subscription_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    recurring_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    billing_interval: Mapped[str] = mapped_column(String(32), nullable=False)
    billing_interval_count: Mapped[int] = mapped_column(Integer, nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_order_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class SubscriptionBillingCycle(Base):
    __tablename__ = "subscription_billing_cycles"
    __table_args__ = (UniqueConstraint("subscription_id", "provider_event_id"),)

    id: Mapped[UUID] = uuid_pk()
    subscription_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=False
    )
    order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("orders.id"))
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("provider", "provider_environment", "idempotency_key"),
        UniqueConstraint("provider", "provider_environment", "provider_refund_id"),
    )

    id: Mapped[UUID] = uuid_pk()
    refund_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    payment_attempt_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payment_attempts.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_environment: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    requested_at: Mapped[datetime] = created_at()
    provider_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class RefundPolicySnapshot(Base):
    __tablename__ = "refund_policy_snapshots"

    id: Mapped[UUID] = uuid_pk()
    order_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("order_items.id"), nullable=False, unique=True
    )
    policy_code: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at()


class Entitlement(Base):
    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("order_item_id", "entitlement_type"),)

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    order_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("order_items.id"), nullable=False
    )
    entitlement_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    quantity_granted: Mapped[int | None] = mapped_column(Integer)
    quantity_consumed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    configuration_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class EntitlementActivationJob(Base):
    __tablename__ = "entitlement_activation_jobs"

    id: Mapped[UUID] = uuid_pk()
    order_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("order_items.id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class EntitlementConsumption(Base):
    __tablename__ = "entitlement_consumptions"
    __table_args__ = (UniqueConstraint("entitlement_id", "idempotency_key"),)

    id: Mapped[UUID] = uuid_pk()
    entitlement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entitlements.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = created_at()


class PaymentLedgerEntry(Base):
    __tablename__ = "payment_ledger_entries"

    id: Mapped[UUID] = uuid_pk()
    entry_type: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("orders.id"))
    payment_attempt_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payment_attempts.id")
    )
    refund_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("refunds.id"))
    subscription_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subscriptions.id")
    )
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_reference: Mapped[str | None] = mapped_column(String(255))
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ledger_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()


class ReconciliationDiscrepancy(Base):
    __tablename__ = "reconciliation_discrepancies"

    id: Mapped[UUID] = uuid_pk()
    discrepancy_type: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    internal_reference_type: Mapped[str | None] = mapped_column(String(64))
    internal_reference_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    provider_reference: Mapped[str | None] = mapped_column(String(255))
    expected_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    actual_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'open'"))
    assigned_to: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    detected_at: Mapped[datetime] = created_at()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_reason: Mapped[str | None] = mapped_column(Text)
