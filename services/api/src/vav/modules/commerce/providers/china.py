"""WeChat Pay and Alipay: contract and refusal, deliberately not an integration.

Neither channel can be built yet, and the blocker is not engineering. Chinese
merchant accounts settle to a named domestic legal entity, and which entity
collects on VAV's behalf — and what the US company's international collection
responsibilities are — is still open as DEC-005. Writing a live integration
against unknown merchant IDs would produce code that looks finished, passes a
smoke test against a sandbox, and is wrong about who receives the money.

So these are stubs with three jobs:

1. Make the boundary real. They implement the same ``PaymentProvider``
   protocol as Stripe and PayPal, so wiring the actual channel later is a
   change inside one file rather than a change to the payment surface.
2. Refuse loudly and specifically. Every method raises a typed error naming
   DEC-005, so an operator who reaches one learns *why* it is closed instead
   of seeing a generic failure.
3. Refuse to be faked. ``FakePaymentProvider`` exists so local development can
   exercise a card checkout without credentials; applying that fallback here
   would let a developer complete a WeChat "payment" that never existed and
   leave an order marked paid. The factory therefore never substitutes the
   fake for these two.

The safe default recorded against DEC-005 is "Stripe/PayPal sandbox only;
WeChat Pay/Alipay and live channels remain disabled", and this is that default
expressed in code rather than in a document.
"""

from __future__ import annotations

from collections.abc import Mapping

from vav.common.exceptions import VavError
from vav.modules.commerce.providers.base import (
    CreateProviderPaymentRequest,
    ProviderPaymentResult,
    ProviderRefundRequest,
    ProviderRefundResult,
    VerifiedWebhookEvent,
)

#: The decision that gates both channels. Referenced by the release manifest so
#: the dependency is visible in the release report rather than only in code.
CHINA_PAYMENT_DECISION = "DEC-005"

#: Channel names reserved for the Chinese rails. Kept here so configuration
#: validation, the factory and the release manifest agree on one list.
CHINA_PAYMENT_PROVIDERS = ("wechat_pay", "alipay")


class ChinaChannelPendingDecision(VavError):
    """Raised whenever a Chinese channel is reached before DEC-005 is settled.

    503 rather than 4xx: the request is well formed and the channel is
    expected to exist later, so this is an upstream dependency that is not
    ready, not a caller mistake.
    """

    def __init__(self, provider: str, action: str) -> None:
        super().__init__(
            "PAYMENT_CHANNEL_PENDING_DECISION",
            (
                f"{provider} cannot {action}: the Chinese collection entity and "
                f"merchant accounts are undecided ({CHINA_PAYMENT_DECISION}). "
                "Stripe and PayPal remain the supported channels."
            ),
            status_code=503,
            details=[
                {
                    "provider": provider,
                    "decision": CHINA_PAYMENT_DECISION,
                    "decision_title": "China and international payment entities",
                    "status": "PROPOSED",
                }
            ],
        )


class _PendingChinaProvider:
    """Shared refusal behaviour for both Chinese channels."""

    name: str
    #: Never "live". The environment is reported so a release report can state
    #: the channel's status without special-casing it.
    environment = "pending_decision"

    async def create_payment(self, request: CreateProviderPaymentRequest) -> ProviderPaymentResult:
        raise ChinaChannelPendingDecision(self.name, "create a payment")

    async def create_refund(self, request: ProviderRefundRequest) -> ProviderRefundResult:
        raise ChinaChannelPendingDecision(self.name, "create a refund")

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> VerifiedWebhookEvent:
        # Refusing to verify matters more than refusing to charge: a webhook
        # that were accepted without a merchant key would mark orders paid on
        # nothing but an attacker's say-so.
        raise ChinaChannelPendingDecision(self.name, "verify a webhook")


class WeChatPayProvider(_PendingChinaProvider):
    name = "wechat_pay"


class AlipayProvider(_PendingChinaProvider):
    name = "alipay"
