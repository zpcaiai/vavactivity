from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping

import httpx

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.commerce.providers.base import (
    CreateProviderPaymentRequest,
    ProviderPaymentResult,
    ProviderRefundRequest,
    ProviderRefundResult,
    VerifiedWebhookEvent,
)


class StripePaymentProvider:
    name = "stripe"

    def __init__(self) -> None:
        settings = get_settings()
        self.environment: str = settings.payment_environment
        self.secret = settings.stripe_secret_key.get_secret_value()
        self.webhook_secret = settings.stripe_webhook_secret.get_secret_value()
        if not self.secret or not settings.stripe_api_version:
            raise VavError(
                "PAYMENT_PROVIDER_CONFIGURATION_REQUIRED",
                "Stripe test credentials and a pinned API version are required.",
                status_code=503,
            )

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.secret}",
            "Stripe-Version": get_settings().stripe_api_version,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def create_payment(self, request: CreateProviderPaymentRequest) -> ProviderPaymentResult:
        settings = get_settings()
        line_item: dict[str, str] = {
            "line_items[0][price_data][currency]": request.currency.lower(),
            "line_items[0][price_data][unit_amount]": str(request.amount_minor),
            "line_items[0][price_data][product_data][name]": request.order_number,
            "line_items[0][quantity]": "1",
        }
        if request.recurring:
            line_item["mode"] = "subscription"
            line_item["line_items[0][price_data][recurring][interval]"] = (
                request.billing_interval or "month"
            )
            line_item["line_items[0][price_data][recurring][interval_count]"] = str(
                request.billing_interval_count or 1
            )
        else:
            line_item["mode"] = "payment"
        form = {
            **line_item,
            "success_url": settings.stripe_success_url,
            "cancel_url": settings.stripe_cancel_url,
            "metadata[vav_order_id]": str(request.order_id),
            "metadata[vav_order_number]": request.order_number,
            "metadata[vav_user_id]": str(request.user_id),
            "metadata[environment]": self.environment,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                headers=self._headers(request.idempotency_key),
                data=form,
            )
        if response.status_code >= 400:
            raise VavError(
                "PAYMENT_PROVIDER_ERROR",
                "Stripe could not create the payment.",
                status_code=502,
            )
        payload = response.json()
        return ProviderPaymentResult(
            provider_payment_id=str(payload["id"]),
            provider_subscription_id=(
                str(payload["subscription"]) if payload.get("subscription") else None
            ),
            status="requires_action",
            client_action={"type": "redirect", "url": str(payload["url"])},
        )

    async def create_refund(self, request: ProviderRefundRequest) -> ProviderRefundResult:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.stripe.com/v1/refunds",
                headers=self._headers(request.idempotency_key),
                data={
                    "payment_intent": request.payment_id,
                    "amount": str(request.amount_minor),
                    "metadata[vav_order_id]": str(request.order_id),
                },
            )
        if response.status_code >= 400:
            raise VavError(
                "REFUND_PROVIDER_ERROR", "Stripe could not submit the refund.", status_code=502
            )
        payload = response.json()
        return ProviderRefundResult(
            provider_refund_id=str(payload["id"]), status=str(payload["status"])
        )

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> VerifiedWebhookEvent:
        signature = headers.get("stripe-signature", "")
        components = {
            key: value
            for part in signature.split(",")
            if "=" in part
            for key, value in [part.split("=", 1)]
        }
        timestamp = components.get("t", "")
        supplied = components.get("v1", "")
        if not self.webhook_secret or not timestamp or not supplied:
            raise self._invalid_signature()
        try:
            if abs(time.time() - int(timestamp)) > 300:
                raise self._invalid_signature()
        except ValueError as error:
            raise self._invalid_signature() from error
        expected = hmac.new(
            self.webhook_secret.encode(),
            timestamp.encode() + b"." + raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise self._invalid_signature()
        payload = json.loads(raw_body)
        data_object = payload.get("data", {}).get("object", {})
        if not isinstance(data_object, dict):
            raise VavError(
                "WEBHOOK_PAYLOAD_INVALID", "Webhook payload is invalid.", status_code=400
            )
        metadata = data_object.get("metadata", {})
        normalized: dict[str, object] = {
            "provider_payment_id": data_object.get("id"),
            "order_id": metadata.get("vav_order_id") if isinstance(metadata, dict) else None,
            "amount_minor": data_object.get("amount_total") or data_object.get("amount"),
            "currency": data_object.get("currency"),
            "provider_subscription_id": data_object.get("subscription"),
        }
        return VerifiedWebhookEvent(
            provider_event_id=str(payload["id"]),
            event_type=str(payload["type"]),
            data=normalized,
            payload=payload,
        )

    @staticmethod
    def _invalid_signature() -> VavError:
        return VavError(
            "WEBHOOK_SIGNATURE_INVALID",
            "Webhook signature verification failed.",
            status_code=400,
        )
