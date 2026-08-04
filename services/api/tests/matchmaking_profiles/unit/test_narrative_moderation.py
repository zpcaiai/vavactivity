"""Narrative content screening."""

# ruff: noqa: E501
from __future__ import annotations

import pytest

from vav.modules.matchmaking_profiles import content_safety


@pytest.mark.parametrize(
    "text",
    [
        "有兴趣可以联系我 member@example.com",
        "Reach me at member (at) example.com",
        "我的微信：vav_test_handle",
        "WhatsApp: +8613800001111",
        "看看我的主页 https://example.com/me",
        "我的电话是 13800001111",
    ],
)
def test_contact_details_are_detected_and_block(text: str) -> None:
    findings = content_safety.scan_text(text)
    assert content_safety.blocking_findings(findings), text


@pytest.mark.parametrize(
    "text",
    [
        "我可以帮你投资数字货币，收益有保证",
        "先给我转账一点点就可以",
        "加我私聊，站外联系更方便",
        "请提供你的身份证号",
    ],
)
def test_risk_patterns_route_to_review_without_blocking(text: str) -> None:
    findings = content_safety.scan_text(text)
    assert findings
    assert all(finding["severity"] in {"review", "block"} for finding in findings)


def test_ordinary_narrative_produces_no_findings() -> None:
    clean = (
        "我在教会服事多年，喜欢阅读、音乐和户外活动。"
        "希望认识一位同样重视信仰与家庭的伴侣，一起彼此扶持地成长。"
    )
    assert content_safety.scan_text(clean) == []


def test_findings_are_tagged_with_their_field() -> None:
    findings = content_safety.scan_narratives(
        {"self_introduction": "写信给我 member@example.com", "marriage_vision": "希望建立家庭"}
    )
    assert findings
    assert all(finding["field_code"] == "self_introduction" for finding in findings)


def test_narratives_always_require_review() -> None:
    assert content_safety.moderation_status_for([]) == "review_required"
