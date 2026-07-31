from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.commerce.providers.base import (
    CreateProviderPaymentRequest,
    ProviderPaymentResult,
    ProviderRefundRequest,
    ProviderRefundResult,
    VerifiedWebhookEvent,
)


class FakePaymentProvider:
    """Local deterministic Provider boundary; never enabled in production."""

    def __init__(self, name: str) -> None:
        settings = get_settings()
        if settings.environment == "production" or not settings.payment_test_fake_enabled:
            raise VavError(
                "PAYMENT_PROVIDER_CONFIGURATION_REQUIRED",
                f"{name} Provider credentials are required.",
                status_code=503,
            )
        self.name = name
        self.environment = "test"

    async def create_payment(self, request: CreateProviderPaymentRequest) -> ProviderPaymentResult:
        digest = hashlib.sha256(
            f"{self.name}:{request.idempotency_key}:{request.order_id}".encode()
        ).hexdigest()[:24]
        provider_id = f"fake_{self.name}_{digest}"
        subscription_id = f"fake_sub_{digest}" if request.recurring else None
        return ProviderPaymentResult(
            provider_payment_id=provider_id,
            provider_subscription_id=subscription_id,
            status="requires_action",
            client_action={
                "type": "redirect",
                "url": (
                    f"{get_settings().user_web_url}/zh-CN/checkout/processing"
                    f"?order={request.order_number}&provider={self.name}"
                ),
                "test_only": True,
            },
        )

    async def create_refund(self, request: ProviderRefundRequest) -> ProviderRefundResult:
        digest = hashlib.sha256(
            f"{self.name}:refund:{request.idempotency_key}:{request.payment_id}".encode()
        ).hexdigest()[:24]
        return ProviderRefundResult(provider_refund_id=f"fake_re_{digest}", status="submitted")

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> VerifiedWebhookEvent:
        supplied = headers.get("x-vav-test-signature", "")
        expected = hmac.new(
            get_settings().payment_test_webhook_secret.get_secret_value().encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise VavError(
                "WEBHOOK_SIGNATURE_INVALID",
                "Webhook signature verification failed.",
                status_code=400,
            )
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as error:
            raise VavError(
                "WEBHOOK_PAYLOAD_INVALID", "Webhook payload is invalid.", status_code=400
            ) from error
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("id"), str)
            or not str(payload["id"]).startswith("evt_test_")
            or not isinstance(payload.get("type"), str)
            or not isinstance(payload.get("data"), dict)
        ):
            raise VavError(
                "WEBHOOK_PAYLOAD_INVALID", "Webhook payload is invalid.", status_code=400
            )
        return VerifiedWebhookEvent(
            provider_event_id=str(payload["id"]),
            event_type=str(payload["type"]),
            data=dict(payload["data"]),
            payload=payload,
        )
