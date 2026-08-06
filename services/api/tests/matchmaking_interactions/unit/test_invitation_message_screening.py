"""Invitation text cannot smuggle contact details past the exchange consent."""

from __future__ import annotations

import pytest

from vav.modules.matchmaking_interactions.domain import screen_invitation_message

POLITE = [
    "I am glad we chose each other. I would like to get to know you.",
    "很高兴我们互相选择。我愿意进一步认识你。",
    "Thank you for choosing me too. Shall we talk here first?",
    "I appreciated what you wrote about your family and your church.",
]


@pytest.mark.parametrize("message", POLITE)
def test_an_ordinary_message_passes(message: str) -> None:
    assert screen_invitation_message(message) == []


@pytest.mark.parametrize(
    "message",
    [
        "my email is stephen.zhao@example.com",
        "reach me at stephen (at) example dot com",
        "写信到 zhao123@qq.com",
    ],
)
def test_an_email_address_is_caught(message: str) -> None:
    assert "email_address" in screen_invitation_message(message)


@pytest.mark.parametrize(
    "message",
    ["call me on 138-0013-8000", "my number is +86 138 0013 8000", "13800138000"],
)
def test_a_phone_number_is_caught(message: str) -> None:
    assert "phone_number" in screen_invitation_message(message)


@pytest.mark.parametrize(
    "message",
    ["加我微信：zhaoxx", "my wechat id is zhaoxx", "telegram: @zhaoxx", "add me on WhatsApp"],
)
def test_a_messaging_handle_is_caught(message: str) -> None:
    assert "messaging_handle" in screen_invitation_message(message)


@pytest.mark.parametrize(
    "message", ["see https://example.com/me", "look at www.example.com", "visit example.com"]
)
def test_an_external_link_is_caught(message: str) -> None:
    assert "external_link" in screen_invitation_message(message)


@pytest.mark.parametrize(
    "message",
    [
        "could you 转账 a small amount first",
        "I can teach you 投资 with USDT",
        "send money via Western Union",
    ],
)
def test_payment_and_investment_solicitation_is_caught(message: str) -> None:
    """Romance fraud opens exactly this way, so it is screened at the door."""
    assert "payment_or_investment" in screen_invitation_message(message)


def test_a_year_is_not_mistaken_for_a_phone_number() -> None:
    """Over-blocking would push members to work around the screen."""
    assert screen_invitation_message("I was born in 1993 and moved here in 2019") == []


def test_multiple_violations_are_all_reported() -> None:
    violations = screen_invitation_message("email me at a@b.com or call 13800138000")
    assert {"email_address", "phone_number"} <= set(violations)
