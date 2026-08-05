"""Idempotency for member writes.

A member tapping "like" twice, or two devices replaying the same request, must
produce one record and one notification. The key plus a hash of the request
body is what makes a retry recognisable; the stored response is what makes the
retry return the same answer instead of a confusing error.
"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.privacy.crypto import decrypt_private, encrypt_private


class IdempotencyOperation:
    LIKE = "like"
    SKIP = "skip"
    WITHDRAW_LIKE = "withdraw_like"
    WITHDRAW_SKIP = "withdraw_skip"
    CLOSE_MATCH = "close_match"
    SEND_INVITATION = "send_invitation"
    ACCEPT_INVITATION = "accept_invitation"
    DECLINE_INVITATION = "decline_invitation"
    CANCEL_INVITATION = "cancel_invitation"
    REQUEST_CONTACT_EXCHANGE = "request_contact_exchange"
    SUBMIT_CONTACT_CONSENT = "submit_contact_consent"
    WITHDRAW_CONTACT_CONSENT = "withdraw_contact_consent"


@dataclass(frozen=True)
class ReplayedResult:
    """A previous response for the same key and the same request."""

    payload: dict[str, Any]


def request_hash(payload: Any) -> str:
    """Stable hash of a request body.

    Sorted keys mean that a client reordering its JSON is still the same
    request, while any genuine change in what is being asked for produces a
    different hash and is refused.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalise_key(raw: str | None) -> str:
    if raw is None or not raw.strip():
        raise VavError(
            "IDEMPOTENCY_KEY_REQUIRED",
            "This operation requires an Idempotency-Key header.",
            status_code=400,
        )
    key = raw.strip()
    if len(key) > 128:
        raise VavError(
            "IDEMPOTENCY_KEY_INVALID",
            "An idempotency key may not exceed 128 characters.",
            status_code=400,
        )
    return key


async def begin(
    session: AsyncSession,
    *,
    user_id: UUID,
    operation: str,
    key: str,
    payload: Any,
) -> ReplayedResult | None:
    """Claim the key, or return the earlier result for an identical retry.

    A completed record replays. An in-progress record means the first request
    is still running, which is what a double tap looks like, so the second one
    is refused rather than allowed to race.
    """
    settings = get_settings()
    digest = request_hash(payload)
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=settings.matchmaking_idempotency_ttl_hours)

    existing = (
        await session.execute(
            text(
                "SELECT status, request_hash, response_snapshot_encrypted, expires_at "
                "FROM matchmaking_idempotency_records "
                "WHERE user_id=:user AND operation=:op AND idempotency_key=:key"
            ),
            {"user": user_id, "op": operation, "key": key},
        )
    ).mappings()
    record = existing.first()

    if record is not None and record["expires_at"] > now:
        if str(record["request_hash"]) != digest:
            raise VavError(
                "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST",
                "This idempotency key was already used for a different request.",
                status_code=409,
            )
        if str(record["status"]) == "completed":
            snapshot = record["response_snapshot_encrypted"]
            if snapshot is None:
                return ReplayedResult(payload={})
            stored = snapshot.get("ciphertext") if isinstance(snapshot, dict) else None
            if stored is None:
                return ReplayedResult(payload={})
            return ReplayedResult(payload=decrypt_private(stored))
        raise VavError(
            "IDEMPOTENT_REQUEST_IN_PROGRESS",
            "An identical request is still being processed.",
            status_code=409,
        )

    await session.execute(
        text(
            "INSERT INTO matchmaking_idempotency_records "
            "(user_id,operation,idempotency_key,request_hash,status,expires_at) "
            "VALUES (:user,:op,:key,:hash,'in_progress',:expires) "
            "ON CONFLICT (user_id,operation,idempotency_key) DO UPDATE SET "
            "request_hash=EXCLUDED.request_hash, status='in_progress', "
            "response_snapshot_encrypted=NULL, created_at=now(), completed_at=NULL, "
            "expires_at=EXCLUDED.expires_at"
        ),
        {"user": user_id, "op": operation, "key": key, "hash": digest, "expires": expires_at},
    )
    return None


async def complete(
    session: AsyncSession,
    *,
    user_id: UUID,
    operation: str,
    key: str,
    response: dict[str, Any],
) -> None:
    """Store the response so an identical retry replays it.

    The snapshot is encrypted because a stored response can contain a match
    identifier or an invitation state that should not sit in plaintext beside
    the key that unlocks it.
    """
    await session.execute(
        text(
            "UPDATE matchmaking_idempotency_records SET status='completed', "
            "response_snapshot_encrypted=CAST(:snapshot AS jsonb), completed_at=now() "
            "WHERE user_id=:user AND operation=:op AND idempotency_key=:key"
        ),
        {
            "user": user_id,
            "op": operation,
            "key": key,
            "snapshot": json.dumps({"ciphertext": encrypt_private(response)}),
        },
    )


async def abandon(session: AsyncSession, *, user_id: UUID, operation: str, key: str) -> None:
    """Release a claimed key after a failed attempt so the member can retry."""
    await session.execute(
        text(
            "DELETE FROM matchmaking_idempotency_records "
            "WHERE user_id=:user AND operation=:op AND idempotency_key=:key "
            "AND status='in_progress'"
        ),
        {"user": user_id, "op": operation, "key": key},
    )
