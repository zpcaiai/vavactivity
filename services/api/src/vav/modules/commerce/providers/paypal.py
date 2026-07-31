from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

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


class PayPalPaymentProvider:
    name = "paypal"

    def __init__(self) -> None:
        settings = get_settings()
        self.environment: str = settings.paypal_environment
        self.client_id = settings.paypal_client_id.get_secret_value()
        self.client_secret = settings.paypal_client_secret.get_secret_value()
        self.webhook_id = settings.paypal_webhook_id.get_secret_value()
        self.base_url = (
            "https://api-m.paypal.com"
            if self.environment == "live"
            else "https://api-m.sandbox.paypal.com"
        )
        if not self.client_id or not self.client_secret:
            raise VavError(
                "PAYMENT_PROVIDER_CONFIGURATION_REQUIRED",
                "PayPal sandbox credentials are required.",
                status_code=503,
            )

    async def _token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{self.base_url}/v1/oauth2/token",
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
        )
        if response.status_code >= 400:
            raise VavError(
                "PAYMENT_PROVIDER_ERROR", "PayPal authentication failed.", status_code=502
            )
        return str(response.json()["access_token"])

    async def create_payment(self, request: CreateProviderPaymentRequest) -> ProviderPaymentResult:
        if request.recurring:
            raise VavError(
                "PAYMENT_PROVIDER_CONFIGURATION_REQUIRED",
                "PayPal subscriptions require an approved Provider plan mapping.",
                status_code=503,
            )
        settings = get_settings()
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._token(client)
            response = await client.post(
                f"{self.base_url}/v2/checkout/orders",
                headers={
                    "Authorization": f"Bearer {token}",
                    "PayPal-Request-Id": request.idempotency_key,
                    "Content-Type": "application/json",
                },
                json={
                    "intent": "CAPTURE",
                    "purchase_units": [
                        {
                            "custom_id": str(request.order_id),
                            "invoice_id": request.order_number,
                            "amount": {
                                "currency_code": request.currency,
                                "value": self._major_amount(request.amount_minor),
                            },
                        }
                    ],
                    "payment_source": {
                        "paypal": {
                            "experience_context": {
                                "return_url": settings.paypal_return_url,
                                "cancel_url": settings.paypal_cancel_url,
                            }
                        }
                    },
                },
            )
        if response.status_code >= 400:
            raise VavError(
                "PAYMENT_PROVIDER_ERROR",
                "PayPal could not create the payment.",
                status_code=502,
            )
        payload = response.json()
        approval = next(
            (
                link["href"]
                for link in payload.get("links", [])
                if link.get("rel") == "payer-action"
            ),
            None,
        )
        if not approval:
            raise VavError(
                "PAYMENT_PROVIDER_ERROR",
                "PayPal did not return an approval URL.",
                status_code=502,
            )
        return ProviderPaymentResult(
            provider_payment_id=str(payload["id"]),
            status="requires_action",
            client_action={"type": "redirect", "url": str(approval)},
        )

    async def create_refund(self, request: ProviderRefundRequest) -> ProviderRefundResult:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._token(client)
            response = await client.post(
                f"{self.base_url}/v2/payments/captures/{request.payment_id}/refund",
                headers={
                    "Authorization": f"Bearer {token}",
                    "PayPal-Request-Id": request.idempotency_key,
                    "Content-Type": "application/json",
                },
                json={
                    "amount": {
                        "currency_code": request.currency,
                        "value": self._major_amount(request.amount_minor),
                    }
                },
            )
        if response.status_code >= 400:
            raise VavError(
                "REFUND_PROVIDER_ERROR", "PayPal could not submit the refund.", status_code=502
            )
        payload = response.json()
        return ProviderRefundResult(
            provider_refund_id=str(payload["id"]), status=str(payload["status"]).lower()
        )

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> VerifiedWebhookEvent:
        if not self.webhook_id:
            raise VavError(
                "PAYMENT_PROVIDER_CONFIGURATION_REQUIRED",
                "PayPal Webhook ID is required.",
                status_code=503,
            )
        payload = json.loads(raw_body)
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._token(client)
            response = await client.post(
                f"{self.base_url}/v1/notifications/verify-webhook-signature",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "auth_algo": headers.get("paypal-auth-algo"),
                    "cert_url": headers.get("paypal-cert-url"),
                    "transmission_id": headers.get("paypal-transmission-id"),
                    "transmission_sig": headers.get("paypal-transmission-sig"),
                    "transmission_time": headers.get("paypal-transmission-time"),
                    "webhook_id": self.webhook_id,
                    "webhook_event": payload,
                },
            )
        if response.status_code >= 400 or response.json().get("verification_status") != "SUCCESS":
            raise VavError(
                "WEBHOOK_SIGNATURE_INVALID",
                "Webhook signature verification failed.",
                status_code=400,
            )
        resource = payload.get("resource", {})
        custom_id = resource.get("custom_id")
        amount = resource.get("amount", {})
        normalized: dict[str, object] = {
            "provider_payment_id": resource.get("id"),
            "order_id": custom_id,
            "amount_minor": self._minor_amount(amount.get("value")),
            "currency": amount.get("currency_code"),
            "provider_subscription_id": resource.get("billing_agreement_id"),
        }
        return VerifiedWebhookEvent(
            provider_event_id=str(payload["id"]),
            event_type=str(payload["event_type"]),
            data=normalized,
            payload=payload,
        )

    @staticmethod
    def _minor_amount(value: object) -> int | None:
        try:
            return int((Decimal(str(value)) * 100).to_integral_exact())
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _major_amount(value: int) -> str:
        return format(Decimal(value).scaleb(-2), ".2f")
