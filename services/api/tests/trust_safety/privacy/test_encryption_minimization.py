from vav.modules.trust_safety.crypto import decrypt_sensitive, encrypt_sensitive


def test_sensitive_report_and_appeal_text_is_encrypted() -> None:
    plain = {"description": "private safety details"}
    encrypted = encrypt_sensitive(plain)
    assert "private safety details" not in encrypted
    assert decrypt_sensitive(encrypted) == plain


def test_evidence_policy_does_not_default_to_full_private_records() -> None:
    allowed_snapshots = {
        "reported_content",
        "invitation_message",
        "profile_version",
        "photo_review_version",
        "access_log_summary",
        "behavior_frequency_summary",
    }
    assert "full_ai_conversation" not in allowed_snapshots
    assert "full_counseling_record" not in allowed_snapshots
    assert "payment_card_data" not in allowed_snapshots
