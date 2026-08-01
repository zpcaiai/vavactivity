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
    digest = hashlib.sha256(f"vav:notifications:{pepper}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_notification_data(payload: Any) -> str:
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return Fernet(_key()).encrypt(value).decode()


def decrypt_notification_data(ciphertext: str) -> Any:
    try:
        return json.loads(Fernet(_key()).decrypt(ciphertext.encode()))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise VavError(
            "NOTIFICATION_ENCRYPTED_DATA_INVALID",
            "Encrypted notification data could not be read.",
            status_code=409,
        ) from exc


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()
