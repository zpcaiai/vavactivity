import pytest

from vav.common.exceptions import VavError
from vav.modules.commerce.domain import (
    EntitlementType,
    OrderStatus,
    ensure_order_transition,
    entitlement_type_for,
)


def test_happy_path_order_transitions_are_explicit() -> None:
    ensure_order_transition(OrderStatus.DRAFT, OrderStatus.PENDING_PAYMENT)
    ensure_order_transition(OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_PROCESSING)
    ensure_order_transition(OrderStatus.PAYMENT_PROCESSING, OrderStatus.PAID)
    ensure_order_transition(OrderStatus.PAID, OrderStatus.FULFILLING)
    ensure_order_transition(OrderStatus.FULFILLING, OrderStatus.FULFILLED)


def test_browser_return_cannot_skip_payment_states() -> None:
    with pytest.raises(VavError) as raised:
        ensure_order_transition(OrderStatus.PENDING_PAYMENT, OrderStatus.FULFILLED)
    assert raised.value.code == "ORDER_STATE_TRANSITION_INVALID"


def test_fulfillment_mapping_is_fail_closed() -> None:
    assert (
        entitlement_type_for("appointment_credits", "counseling_package")
        == EntitlementType.COUNSELING_CREDITS
    )
    with pytest.raises(VavError) as raised:
        entitlement_type_for("unknown", "unknown")
    assert raised.value.code == "ENTITLEMENT_MAPPING_MISSING"
