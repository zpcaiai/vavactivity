import hashlib
import hmac
import json

import pytest

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.commerce.providers.fake import FakePaymentProvider


@pytest.mark.asyncio
async def test_fake_provider_accepts_only_signed_namespaced_events() -> None:
    provider = FakePaymentProvider("stripe")
    body = json.dumps(
        {
            "id": "evt_test_signature",
            "type": "payment.succeeded",
            "data": {"provider_payment_id": "fake_stripe_1"},
        }
    ).encode()
    signature = hmac.new(
        get_settings().payment_test_webhook_secret.get_secret_value().encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    event = await provider.verify_webhook({"x-vav-test-signature": signature}, body)
    assert event.provider_event_id == "evt_test_signature"

    with pytest.raises(VavError) as raised:
        await provider.verify_webhook({"x-vav-test-signature": "invalid"}, body)
    assert raised.value.code == "WEBHOOK_SIGNATURE_INVALID"
