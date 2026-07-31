from __future__ import annotations

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.commerce.providers.base import PaymentProvider
from vav.modules.commerce.providers.fake import FakePaymentProvider
from vav.modules.commerce.providers.paypal import PayPalPaymentProvider
from vav.modules.commerce.providers.stripe import StripePaymentProvider


def get_payment_provider(name: str) -> PaymentProvider:
    settings = get_settings()
    normalized = name.casefold()
    if normalized not in settings.payment_enabled_providers:
        raise VavError(
            "PAYMENT_PROVIDER_DISABLED",
            "The requested payment Provider is disabled.",
            status_code=409,
        )
    try:
        if normalized == "stripe":
            return StripePaymentProvider()
        if normalized == "paypal":
            return PayPalPaymentProvider()
    except VavError as error:
        if (
            error.code == "PAYMENT_PROVIDER_CONFIGURATION_REQUIRED"
            and settings.payment_test_fake_enabled
            and settings.environment in {"development", "test"}
        ):
            return FakePaymentProvider(normalized)
        raise
    raise VavError(
        "PAYMENT_PROVIDER_UNSUPPORTED",
        "The requested payment Provider is unsupported.",
        status_code=422,
    )
