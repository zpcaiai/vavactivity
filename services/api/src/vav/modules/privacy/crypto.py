from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from vav.common.exceptions import VavError
from vav.core.config import get_settings


def _key() -> bytes:
    secret = get_settings().auth_refresh_token_pepper.get_secret_value()
    return base64.urlsafe_b64encode(hashlib.sha256(f"vav:privacy:{secret}".encode()).digest())


def encrypt_private(payload: Any) -> str:
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return Fernet(_key()).encrypt(value).decode()


def decrypt_private(ciphertext: str) -> Any:
    try:
        return json.loads(Fernet(_key()).decrypt(ciphertext.encode()))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise VavError(
            "PRIVACY_ENCRYPTED_DATA_INVALID",
            "Encrypted private data could not be read.",
            status_code=409,
        ) from exc


def searchable_hmac(value: str) -> str:
    pepper = get_settings().privacy_search_hmac_pepper.get_secret_value()
    return hmac.new(pepper.encode(), value.strip().casefold().encode(), hashlib.sha256).hexdigest()


def mask_email(value: str) -> str:
    local, separator, domain = value.partition("@")
    if not separator:
        return "***"
    return f"{local[:1]}***@{domain}"


def mask_phone(value: str) -> str:
    normalized = "".join(
        character for character in value if character.isdigit() or character == "+"
    )
    return f"{normalized[:4]}******{normalized[-3:]}" if len(normalized) >= 8 else "***"
