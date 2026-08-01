from __future__ import annotations

from vav.modules.ai_assistant.crypto import decrypt_ai_data, encrypt_ai_data
from vav.modules.ai_assistant.safety import assess_risk


def test_conversation_content_is_encrypted_at_rest() -> None:
    plaintext = "private relationship conversation fixture"
    encrypted = encrypt_ai_data({"content": plaintext})
    assert plaintext not in encrypted
    assert decrypt_ai_data(encrypted) == {"content": plaintext}


def test_medical_and_legal_requests_are_not_routed_to_ordinary_advice() -> None:
    for message in ("请给我医疗诊断和处方。", "请给我法律意见并保证结果。"):
        risk = assess_risk(message)
        assert risk.level.value == "moderate"
        assert risk.ordinary_advice_allowed is False
        assert risk.human_referral_required is True
