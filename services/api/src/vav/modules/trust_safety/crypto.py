from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from vav.common.exceptions import VavError
from vav.core.config import get_settings


def _key() -> bytes:
    secret = get_settings().auth_refresh_token_pepper.get_secret_value()
    digest = hashlib.sha256(f"vav:trust-safety:{secret}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_sensitive(payload: Any) -> str:
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return Fernet(_key()).encrypt(value).decode()


def decrypt_sensitive(ciphertext: str) -> Any:
    try:
        return json.loads(Fernet(_key()).decrypt(ciphertext.encode()))
    except (InvalidToken, TypeError, ValueError) as exc:
        raise VavError(
            "SAFETY_ENCRYPTED_DATA_INVALID",
            "Encrypted safety data could not be read.",
            status_code=409,
        ) from exc
