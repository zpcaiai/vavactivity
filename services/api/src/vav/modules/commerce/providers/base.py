from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ChinaPaymentContext:
    """Extension points the Chinese channels need and the card rails do not.

    WeChat Pay and Alipay cannot be modelled as "Stripe with a different key".
    Both require the caller to declare *how* the payer is reaching them
    (``trade_type``: JSAPI inside WeChat, NATIVE for a scanned QR, H5, APP) and
    to identify the payer by a channel-scoped id issued by that channel — an
    ``openid`` for WeChat, a ``buyer_id`` for Alipay — neither of which exists
    anywhere in this platform's own identity model.

    ``settlement_entity_code`` is the part blocked on a business decision
    rather than on code: Chinese merchant accounts settle to a named domestic
    legal entity, and which entity that is remains open (DEC-005). The field
    exists so the contract is complete and the missing value is a visible
    ``None`` rather than an unasked question.
    """

    trade_type: str | None = None
    payer_channel_id: str | None = None
    settlement_entity_code: str | None = None
    goods_tag: str | None = None
    attach: str | None = None


@dataclass(frozen=True, slots=True)
class CreateProviderPaymentRequest:
    order_id: UUID
    order_number: str
    user_id: UUID
    amount_minor: int
    currency: str
    idempotency_key: str
    recurring: bool
    billing_interval: str | None = None
    billing_interval_count: int | None = None
    # Optional, so the card providers are untouched. Populated only by the
    # Chinese channels, which cannot construct a charge without it.
    china: ChinaPaymentContext | None = None


@dataclass(frozen=True, slots=True)
class ProviderPaymentResult:
    provider_payment_id: str
    status: str
    client_action: dict[str, object]
    provider_customer_id: str | None = None
    provider_subscription_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderRefundRequest:
    payment_id: str
    order_id: UUID
    amount_minor: int
    currency: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ProviderRefundResult:
    provider_refund_id: str
    status: str


@dataclass(frozen=True, slots=True)
class VerifiedWebhookEvent:
    provider_event_id: str
    event_type: str
    data: dict[str, object]
    payload: dict[str, object]


class PaymentProvider(Protocol):
    name: str
    environment: str

    async def create_payment(
        self, request: CreateProviderPaymentRequest
    ) -> ProviderPaymentResult: ...

    async def create_refund(self, request: ProviderRefundRequest) -> ProviderRefundResult: ...

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> VerifiedWebhookEvent: ...
