from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from vav.common.exceptions import VavError
from vav.core.config import get_settings


def _secret(purpose: str) -> bytes:
    raw = f"{purpose}:{get_settings().auth_refresh_token_pepper}".encode()
    return hashlib.sha256(raw).digest()


def encrypt_private(payload: dict[str, Any]) -> str:
    key = base64.urlsafe_b64encode(_secret("activity-private"))
    return Fernet(key).encrypt(json.dumps(payload, ensure_ascii=False).encode()).decode()


def decrypt_private(ciphertext: str) -> dict[str, Any]:
    try:
        plain = Fernet(base64.urlsafe_b64encode(_secret("activity-private"))).decrypt(
            ciphertext.encode()
        )
        value = json.loads(plain)
    except (InvalidToken, ValueError, TypeError) as error:
        raise VavError(
            "ACTIVITY_PRIVATE_DATA_INVALID",
            "Encrypted activity data could not be read.",
            status_code=409,
        ) from error
    if not isinstance(value, dict):
        raise VavError("ACTIVITY_PRIVATE_DATA_INVALID", "Encrypted activity data is invalid.")
    return value


def issue_checkin_token(public_reference: str, *, expires_at: int) -> str:
    payload = f"{public_reference}.{expires_at}"
    signature = hmac.new(_secret("activity-checkin"), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_checkin_token(token: str, *, now: int | None = None) -> str:
    try:
        reference, expires_raw, signature = token.rsplit(".", 2)
        expires_at = int(expires_raw)
    except (ValueError, TypeError) as error:
        raise VavError(
            "CHECKIN_TOKEN_INVALID", "Check-in token is invalid.", status_code=422
        ) from error
    payload = f"{reference}.{expires_at}"
    expected = hmac.new(_secret("activity-checkin"), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise VavError("CHECKIN_TOKEN_INVALID", "Check-in token is invalid.", status_code=422)
    if expires_at < (now if now is not None else int(time.time())):
        raise VavError("CHECKIN_TOKEN_EXPIRED", "Check-in token has expired.", status_code=410)
    return reference
