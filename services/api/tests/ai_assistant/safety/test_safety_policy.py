from __future__ import annotations

import pytest

from vav.modules.ai_assistant.safety import assess_risk, safety_response


@pytest.mark.parametrize(
    ("message", "expected"),
    (
        ("我现在计划结束生命。", "immediate"),
        ("伴侣殴打我，这是家暴。", "high"),
        ("请给我法律意见。", "moderate"),
        ("How can I communicate a healthy boundary?", "none"),
    ),
)
def test_independent_risk_prescreen(message: str, expected: str) -> None:
    risk = assess_risk(message)
    assert risk.level.value == expected
    assert risk.ordinary_advice_allowed is (expected == "none")


def test_immediate_risk_response_pauses_ordinary_advice() -> None:
    risk = assess_risk("他正在追我，我现在有危险。")
    response = safety_response(risk, "zh-CN")
    assert risk.immediate_danger_possible is True
    assert risk.human_referral_required is True
    assert "紧急" in response.final_text
    assert "人工复核" in response.final_text
    assert "关系建议" in response.final_text
