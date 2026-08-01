from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from vav.common.exceptions import VavError
from vav.core.config import get_settings


def _key() -> bytes:
    pepper = get_settings().auth_refresh_token_pepper.get_secret_value()
    digest = hashlib.sha256(f"vav:ai-assistant:conversation:{pepper}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_ai_data(payload: Any) -> str:
    return Fernet(_key()).encrypt(json.dumps(payload, ensure_ascii=False).encode()).decode()


def decrypt_ai_data(ciphertext: str) -> Any:
    try:
        return json.loads(Fernet(_key()).decrypt(ciphertext.encode()))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise VavError(
            "AI_ENCRYPTED_DATA_INVALID",
            "Encrypted AI data could not be read.",
            status_code=409,
        ) from exc


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
