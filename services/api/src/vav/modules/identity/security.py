from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from vav.common.exceptions import VavError
from vav.core.config import Settings, get_settings

COMMON_PASSWORDS = {
    "123456789012",
    "correcthorsebatterystaple",
    "passwordpassword",
    "qwertyuiopasdf",
}


class PasswordPolicy:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def validate(self, password: str, email: str) -> None:
        if (
            not self.settings.auth_password_min_length
            <= len(password)
            <= (self.settings.auth_password_max_length)
        ):
            raise VavError(
                "PASSWORD_POLICY_VIOLATION",
                "Password length does not meet policy.",
                details=[
                    {
                        "minimum": self.settings.auth_password_min_length,
                        "maximum": self.settings.auth_password_max_length,
                    }
                ],
            )
        normalized = password.strip().casefold()
        if normalized == email.strip().casefold() or normalized in COMMON_PASSWORDS:
            raise VavError("PASSWORD_POLICY_VIOLATION", "Choose a less common password.")


class PasswordHasher:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.hasher = Argon2PasswordHasher(
            time_cost=self.settings.auth_argon2_time_cost,
            memory_cost=self.settings.auth_argon2_memory_cost,
            parallelism=self.settings.auth_argon2_parallelism,
        )

    def hash(self, password: str) -> str:
        return self.hasher.hash(password)

    def verify(self, password_hash: str | None, password: str) -> bool:
        if not password_hash:
            return False
        try:
            return self.hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False


def opaque_token(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def sha256_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def hmac_token(raw_token: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    return hmac.new(
        active_settings.auth_refresh_token_pepper.get_secret_value().encode(),
        raw_token.encode(),
        hashlib.sha256,
    ).hexdigest()


def privacy_hash(value: str, settings: Settings | None = None) -> str:
    return hmac_token(value.strip().casefold(), settings)


@dataclass(frozen=True)
class AccessClaims:
    user_id: UUID
    session_id: UUID
    audience: str
    auth_version: int
    rbac_version: int


class AccessTokenService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _read_key(self, path: str) -> str:
        key_path = Path(path)
        if not key_path.is_file():
            raise VavError(
                "AUTH_KEY_UNAVAILABLE",
                "Authentication key material is unavailable.",
                status_code=503,
            )
        return key_path.read_text(encoding="utf-8")

    def issue(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        audience: str,
        auth_version: int,
        rbac_version: int,
    ) -> str:
        now = datetime.now(UTC)
        payload = {
            "iss": self.settings.auth_issuer,
            "aud": audience,
            "sub": str(user_id),
            "sid": str(session_id),
            "jti": str(uuid4()),
            "typ": "access",
            "auth_version": auth_version,
            "rbac_version": rbac_version,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=self.settings.auth_access_token_ttl_seconds),
        }
        return jwt.encode(
            payload,
            self._read_key(self.settings.auth_private_key_file),
            algorithm="EdDSA",
            headers={"kid": self.settings.auth_active_key_id},
        )

    def decode(self, token: str, audience: str) -> AccessClaims:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("kid") != self.settings.auth_active_key_id:
                raise VavError(
                    "TOKEN_KEY_INVALID", "Access token key is not accepted.", status_code=401
                )
            payload: dict[str, Any] = jwt.decode(
                token,
                self._read_key(self.settings.auth_public_key_file),
                algorithms=["EdDSA"],
                audience=audience,
                issuer=self.settings.auth_issuer,
                leeway=self.settings.auth_clock_skew_seconds,
                options={"require": ["exp", "iat", "nbf", "sub", "sid", "typ"]},
            )
            if payload.get("typ") != "access":
                raise VavError(
                    "TOKEN_TYPE_INVALID", "Access token type is invalid.", status_code=401
                )
            return AccessClaims(
                user_id=UUID(str(payload["sub"])),
                session_id=UUID(str(payload["sid"])),
                audience=str(payload["aud"]),
                auth_version=int(payload["auth_version"]),
                rbac_version=int(payload["rbac_version"]),
            )
        except VavError:
            raise
        except jwt.ExpiredSignatureError as exc:
            raise VavError("TOKEN_EXPIRED", "Access token has expired.", status_code=401) from exc
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise VavError("TOKEN_INVALID", "Access token is invalid.", status_code=401) from exc
