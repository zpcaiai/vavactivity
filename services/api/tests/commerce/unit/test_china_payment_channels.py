"""PAY-003: WeChat Pay and Alipay stay closed until DEC-005 is settled.

The requirement is deliberately narrow — stubs, contracts and flags only — so
these tests assert refusal rather than behaviour. What matters is that the
refusal cannot be bypassed by configuration, cannot be silently satisfied by
the local fake, and says *why* it refuses.
"""

from __future__ import annotations

import uuid

import pytest

from vav.common.exceptions import VavError
from vav.core.config import Settings
from vav.modules.commerce.providers.base import (
    ChinaPaymentContext,
    CreateProviderPaymentRequest,
    ProviderRefundRequest,
)
from vav.modules.commerce.providers.china import (
    CHINA_PAYMENT_DECISION,
    CHINA_PAYMENT_PROVIDERS,
    AlipayProvider,
    WeChatPayProvider,
)
from vav.modules.commerce.providers.factory import get_payment_provider


def _payment_request() -> CreateProviderPaymentRequest:
    return CreateProviderPaymentRequest(
        order_id=uuid.uuid4(),
        order_number="ORD-TEST-001",
        user_id=uuid.uuid4(),
        amount_minor=2900,
        currency="CNY",
        idempotency_key="key-1",
        recurring=False,
        china=ChinaPaymentContext(trade_type="NATIVE"),
    )


def _refund_request() -> ProviderRefundRequest:
    return ProviderRefundRequest(
        payment_id="pay-1",
        order_id=uuid.uuid4(),
        amount_minor=2900,
        currency="CNY",
        idempotency_key="key-2",
    )


@pytest.mark.parametrize("provider", [WeChatPayProvider(), AlipayProvider()])
@pytest.mark.asyncio
async def test_every_money_moving_method_refuses(provider: object) -> None:
    for coroutine, label in (
        (provider.create_payment(_payment_request()), "create_payment"),
        (provider.create_refund(_refund_request()), "create_refund"),
        (provider.verify_webhook({}, b"{}"), "verify_webhook"),
    ):
        with pytest.raises(VavError) as raised:
            await coroutine
        assert raised.value.code == "PAYMENT_CHANNEL_PENDING_DECISION", label
        # 503, not 4xx: the caller did nothing wrong, the dependency is absent.
        assert raised.value.status_code == 503, label
        assert CHINA_PAYMENT_DECISION in raised.value.message, label


@pytest.mark.asyncio
async def test_webhook_verification_refuses_rather_than_trusting_the_payload() -> None:
    # The most dangerous method to leave permissive: a webhook accepted without
    # a merchant key would mark an order paid on an attacker's say-so.
    with pytest.raises(VavError) as raised:
        await WeChatPayProvider().verify_webhook(
            {"wechatpay-signature": "anything"}, b'{"event_type": "TRANSACTION.SUCCESS"}'
        )
    assert raised.value.code == "PAYMENT_CHANNEL_PENDING_DECISION"


def test_factory_returns_the_stub_rather_than_the_local_fake() -> None:
    # `FakePaymentProvider` exists so card checkout works without credentials.
    # Applying it here would let a developer complete a WeChat "payment" that
    # never happened and leave the order marked paid.
    for name in CHINA_PAYMENT_PROVIDERS:
        provider = get_payment_provider(name)
        assert type(provider).__name__ in {"WeChatPayProvider", "AlipayProvider"}
        assert provider.environment == "pending_decision"


def test_settings_only_populate_by_alias() -> None:
    """Guards the two tests below, which would otherwise assert nothing.

    ``payment_enabled_providers`` carries ``validation_alias`` and the model
    does not set ``populate_by_name``, so passing the *field name* is silently
    ignored and the default list is used instead. A first draft of these tests
    did exactly that: it constructed ``Settings(payment_enabled_providers=...)``,
    never actually enabled the channel, and still passed — for the wrong
    reason. Asserting the alias-only behaviour keeps that mistake from
    reappearing quietly.
    """

    field = Settings.model_fields["payment_enabled_providers"]
    assert field.validation_alias == "PAYMENT_ENABLED_PROVIDERS"
    assert not Settings.model_config.get("populate_by_name")
    ignored = Settings(payment_enabled_providers=["stripe", "wechat_pay"])
    assert ignored.payment_enabled_providers == ["stripe", "paypal"]


def test_configuration_refuses_to_offer_the_channels_at_all() -> None:
    # The checkout builds its buttons from `payment_enabled_providers`, so a
    # name that cannot be listed cannot become a button. Startup is also a far
    # better place to fail than a member's payment. The alias is used here
    # because it is also how a deployment actually sets this.
    for name in ("wechat_pay", "alipay"):
        with pytest.raises(ValueError) as raised:
            Settings(PAYMENT_ENABLED_PROVIDERS=["stripe", name])
        assert CHINA_PAYMENT_DECISION in str(raised.value)


def test_the_supported_channels_are_unaffected() -> None:
    settings = Settings(PAYMENT_ENABLED_PROVIDERS=["stripe", "paypal"])
    assert settings.payment_enabled_providers == ["stripe", "paypal"]


def test_contract_carries_china_specific_extension_points() -> None:
    # Acceptance: "Provider contract has China-specific metadata extension
    # points". Both channels need a trade type and a channel-scoped payer id
    # that this platform's identity model does not have, plus the settlement
    # entity that DEC-005 is about.
    context = ChinaPaymentContext(
        trade_type="JSAPI",
        payer_channel_id="openid-abc",
        settlement_entity_code=None,
        goods_tag="VAV",
        attach="activity=ACT-1",
    )
    request = CreateProviderPaymentRequest(
        order_id=uuid.uuid4(),
        order_number="ORD-TEST-002",
        user_id=uuid.uuid4(),
        amount_minor=100,
        currency="CNY",
        idempotency_key="key-3",
        recurring=False,
        china=context,
    )
    assert request.china is context
    # The undecided value is a visible None rather than an invented default.
    assert request.china.settlement_entity_code is None


def test_card_providers_do_not_carry_china_context_by_default() -> None:
    request = CreateProviderPaymentRequest(
        order_id=uuid.uuid4(),
        order_number="ORD-TEST-003",
        user_id=uuid.uuid4(),
        amount_minor=100,
        currency="USD",
        idempotency_key="key-4",
        recurring=False,
    )
    assert request.china is None
