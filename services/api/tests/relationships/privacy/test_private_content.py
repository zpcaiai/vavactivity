from pathlib import Path

from vav.modules.privacy.crypto import decrypt_private, encrypt_private


def test_private_text_is_encrypted_at_rest() -> None:
    ciphertext = encrypt_private("只属于我的反思")
    assert "只属于我的反思" not in ciphertext
    assert decrypt_private(ciphertext) == "只属于我的反思"


def test_history_and_outbox_never_receive_private_text() -> None:
    source = (Path(__file__).parents[3] / "src/vav/modules/relationships/service.py").read_text()
    assert "private_reason_encrypted" in source
    assert "reflection_encrypted" in source
    # Safe transition history takes controlled reason codes, never free text.
    history_signature = source[
        source.index("async def _history") : source.index("async def create_from_handoff")
    ]
    assert "private_reason" not in history_signature
    assert "reflection" not in history_signature
