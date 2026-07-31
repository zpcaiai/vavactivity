from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


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
