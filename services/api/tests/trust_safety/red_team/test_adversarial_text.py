import base64

import pytest

from vav.modules.trust_safety.domain import classify_text, evaluate_condition


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("请转\u200b账给我", "money_request"),
        ("加 密 货 币投资保证收益", "money_request"),
        ("www.example-pay.invalid/checkout", "external_link"),
        ("我是 VAV 客服，请点击链接付款", "impersonation"),
        ("user (at) example (dot) com", "contact_information_bypass"),
    ],
)
def test_adversarial_scam_variants(payload: str, expected: str | None) -> None:
    hits = classify_text(payload)
    if expected is not None:
        assert expected in hits


def test_base64_encoded_money_request_is_still_detected() -> None:
    encoded = base64.b64encode("请转账给我".encode()).decode()
    assert "money_request" in classify_text(encoded)


def test_prompt_injection_cannot_escape_rule_dsl() -> None:
    with pytest.raises(ValueError):
        evaluate_condition(
            {"signal": "__import__('os').system('id')", "operator": "eq", "value": True},
            {},
        )
