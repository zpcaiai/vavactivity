from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from vav.common.exceptions import VavError
from vav.core.config import get_settings


def _secret(purpose: str) -> bytes:
    pepper = get_settings().auth_refresh_token_pepper
    return hashlib.sha256(f"course:{purpose}:{pepper}".encode()).digest()


def encrypt_sensitive(payload: Any) -> str:
    key = base64.urlsafe_b64encode(_secret("sensitive"))
    return Fernet(key).encrypt(json.dumps(payload, ensure_ascii=False).encode()).decode()


def decrypt_sensitive(ciphertext: str) -> Any:
    try:
        raw = Fernet(base64.urlsafe_b64encode(_secret("sensitive"))).decrypt(ciphertext.encode())
        return json.loads(raw)
    except (InvalidToken, ValueError, TypeError) as error:
        raise VavError(
            "COURSE_SENSITIVE_DATA_INVALID",
            "Encrypted course data could not be read.",
            status_code=409,
        ) from error


def issue_playback_token(session_id: str, *, expires_at: int) -> str:
    nonce = secrets.token_urlsafe(18)
    payload = f"{session_id}.{expires_at}.{nonce}"
    signature = hmac.new(_secret("playback"), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_playback_token(token: str, *, session_id: str, now: int | None = None) -> None:
    try:
        token_session, expires_raw, nonce, signature = token.rsplit(".", 3)
        expires_at = int(expires_raw)
    except (TypeError, ValueError) as error:
        raise VavError(
            "PLAYBACK_TOKEN_INVALID", "Playback token is invalid.", status_code=401
        ) from error
    payload = f"{token_session}.{expires_at}.{nonce}"
    expected = hmac.new(_secret("playback"), payload.encode(), hashlib.sha256).hexdigest()
    if token_session != session_id or not hmac.compare_digest(signature, expected):
        raise VavError("PLAYBACK_TOKEN_INVALID", "Playback token is invalid.", status_code=401)
    if expires_at < (int(time.time()) if now is None else now):
        raise VavError("PLAYBACK_TOKEN_EXPIRED", "Playback token has expired.", status_code=410)


def token_hash(token: str) -> str:
    return hmac.new(_secret("hash"), token.encode(), hashlib.sha256).hexdigest()
