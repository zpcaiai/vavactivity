from types import SimpleNamespace
from uuid import uuid4

from vav.models.commerce import Order
from vav.modules.commerce import service


def test_order_payload_exposes_server_enabled_payment_providers(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(payment_enabled_providers=["stripe", "paypal"]),
    )
    order = Order(
        id=uuid4(),
        order_number="ORD-ACTIVITY-1",
        user_id=uuid4(),
        status="pending_payment",
        currency_code="USD",
        subtotal_minor=4900,
        discount_total_minor=0,
        tax_total_minor=0,
        total_minor=4900,
        refunded_total_minor=0,
        pricing_quote_id=uuid4(),
        billing_email="member@example.com",
        locale="zh-CN",
    )

    payload = service.order_payload(order)

    assert payload["available_payment_providers"] == ["stripe", "paypal"]
