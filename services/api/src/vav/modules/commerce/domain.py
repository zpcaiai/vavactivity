from __future__ import annotations

from enum import StrEnum

from vav.common.exceptions import VavError


class CartStatus(StrEnum):
    ACTIVE = "active"
    CHECKOUT_STARTED = "checkout_started"
    CONVERTED = "converted"
    ABANDONED = "abandoned"
    EXPIRED = "expired"


class OrderStatus(StrEnum):
    DRAFT = "draft"
    PENDING_PAYMENT = "pending_payment"
    PAYMENT_PROCESSING = "payment_processing"
    PAID = "paid"
    FULFILLING = "fulfilling"
    FULFILLED = "fulfilled"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"
    PAYMENT_FAILED = "payment_failed"
    EXPIRED = "expired"
    MANUAL_REVIEW = "manual_review"


class PaymentStatus(StrEnum):
    CREATED = "created"
    REQUIRES_ACTION = "requires_action"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    DISPUTED = "disputed"


class SubscriptionStatus(StrEnum):
    INCOMPLETE = "incomplete"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    PAUSED = "paused"
    CANCEL_AT_PERIOD_END = "cancel_at_period_end"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EntitlementStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXHAUSTED = "exhausted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class EntitlementType(StrEnum):
    ACTIVITY_ADMISSION = "activity_admission"
    COURSE_ACCESS = "course_access"
    COUNSELING_CREDITS = "counseling_credits"
    AI_CREDITS = "ai_credits"
    AI_SUBSCRIPTION = "ai_subscription"
    MEMBERSHIP = "membership"
    MANUAL_SERVICE = "manual_service"


class WebhookProcessingStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    IGNORED = "ignored"
    RETRY_PENDING = "retry_pending"
    FAILED = "failed"


ORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.DRAFT: frozenset({OrderStatus.PENDING_PAYMENT, OrderStatus.CANCELLED}),
    OrderStatus.PENDING_PAYMENT: frozenset(
        {
            OrderStatus.PAYMENT_PROCESSING,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.PAYMENT_FAILED,
        }
    ),
    OrderStatus.PAYMENT_PROCESSING: frozenset(
        {
            OrderStatus.PAID,
            OrderStatus.PAYMENT_FAILED,
            OrderStatus.MANUAL_REVIEW,
        }
    ),
    OrderStatus.PAYMENT_FAILED: frozenset(
        {OrderStatus.PENDING_PAYMENT, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
    OrderStatus.PAID: frozenset(
        {
            OrderStatus.FULFILLING,
            OrderStatus.PARTIALLY_REFUNDED,
            OrderStatus.REFUNDED,
            OrderStatus.MANUAL_REVIEW,
        }
    ),
    OrderStatus.FULFILLING: frozenset(
        {
            OrderStatus.FULFILLED,
            OrderStatus.PARTIALLY_REFUNDED,
            OrderStatus.REFUNDED,
            OrderStatus.MANUAL_REVIEW,
        }
    ),
    OrderStatus.FULFILLED: frozenset(
        {
            OrderStatus.PARTIALLY_REFUNDED,
            OrderStatus.REFUNDED,
            OrderStatus.MANUAL_REVIEW,
        }
    ),
    OrderStatus.PARTIALLY_REFUNDED: frozenset({OrderStatus.REFUNDED, OrderStatus.MANUAL_REVIEW}),
    OrderStatus.MANUAL_REVIEW: frozenset(
        {
            OrderStatus.PAID,
            OrderStatus.FULFILLING,
            OrderStatus.FULFILLED,
            OrderStatus.PARTIALLY_REFUNDED,
            OrderStatus.REFUNDED,
        }
    ),
    OrderStatus.REFUNDED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}


def ensure_order_transition(current: str, target: OrderStatus) -> None:
    try:
        current_status = OrderStatus(current)
    except ValueError as error:
        raise VavError(
            "ORDER_STATE_INVALID", "Order has an unknown state.", status_code=409
        ) from error
    if target not in ORDER_TRANSITIONS[current_status]:
        raise VavError(
            "ORDER_STATE_TRANSITION_INVALID",
            f"Order cannot transition from {current_status} to {target}.",
            status_code=409,
        )


FULFILLMENT_ENTITLEMENTS: dict[str, EntitlementType] = {
    "event_admission": EntitlementType.ACTIVITY_ADMISSION,
    "digital_access": EntitlementType.COURSE_ACCESS,
    "appointment_credits": EntitlementType.COUNSELING_CREDITS,
    "ai_credits": EntitlementType.AI_CREDITS,
    "membership_entitlement": EntitlementType.MEMBERSHIP,
    "manual_fulfillment": EntitlementType.MANUAL_SERVICE,
}


def entitlement_type_for(fulfillment_type: str, product_type: str) -> EntitlementType:
    if product_type == "ai_subscription":
        return EntitlementType.AI_SUBSCRIPTION
    try:
        return FULFILLMENT_ENTITLEMENTS[fulfillment_type]
    except KeyError as error:
        raise VavError(
            "ENTITLEMENT_MAPPING_MISSING",
            "No entitlement mapping exists for this order item.",
            status_code=409,
        ) from error
