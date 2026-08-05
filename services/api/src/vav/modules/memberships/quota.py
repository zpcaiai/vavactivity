"""Atomic, idempotent membership quota reservation and consumption."""

# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.memberships.service import (
    _audit,
    _effective_account,
    _json,
    _mapping,
    _publish,
)


def _snapshot(bucket: dict[str, Any]) -> dict[str, int]:
    return {
        "allocated": int(bucket["allocated_quantity"]),
        "rollover": int(bucket["rollover_quantity"]),
        "consumed": int(bucket["consumed_quantity"]),
        "reserved": int(bucket["reserved_quantity"]),
    }


async def reserve(
    session: AsyncSession,
    *,
    user_id: UUID,
    benefit_code: str,
    quantity: int,
    source_module: str,
    source_reference_id: UUID,
    idempotency_key: str,
) -> dict[str, Any]:
    account = await _effective_account(session, user_id, lock=True)
    if account is None or account["status"] not in {
        "active",
        "trialing",
        "grace_period",
        "cancel_scheduled",
    }:
        raise VavError("MEMBERSHIP_INACTIVE", "An active membership is required.", status_code=403)
    bucket = _mapping(
        await session.execute(
            text(
                "SELECT * FROM membership_quota_buckets WHERE membership_account_id=:account "
                "AND benefit_code=:benefit AND status='active' AND period_starts_at <= now() "
                "AND (period_ends_at IS NULL OR period_ends_at > now()) "
                "ORDER BY period_starts_at DESC LIMIT 1 FOR UPDATE"
            ),
            {"account": account["id"], "benefit": benefit_code},
        )
    )
    if bucket is None:
        raise VavError("QUOTA_NOT_ALLOCATED", "No active quota is allocated.", status_code=403)
    existing = _mapping(
        await session.execute(
            text(
                "SELECT * FROM membership_quota_reservations WHERE quota_bucket_id=:bucket AND idempotency_key=:key"
            ),
            {"bucket": bucket["id"], "key": idempotency_key},
        )
    )
    if existing:
        return existing
    before = _snapshot(bucket)
    updated = _mapping(
        await session.execute(
            text(
                "UPDATE membership_quota_buckets SET reserved_quantity=reserved_quantity+:quantity,"
                "version=version+1,updated_at=now() WHERE id=:id AND status='active' "
                "AND allocated_quantity+rollover_quantity-consumed_quantity-reserved_quantity >= :quantity RETURNING *"
            ),
            {"quantity": quantity, "id": bucket["id"]},
        )
    )
    if updated is None:
        await _publish(
            session,
            "membership.quota.exhausted",
            account["id"],
            {"user_id": str(user_id), "benefit_code": benefit_code},
        )
        await session.commit()
        raise VavError("QUOTA_EXHAUSTED", "Membership quota is exhausted.", status_code=409)
    reservation_id = uuid4()
    ttl = int(getattr(get_settings(), "membership_quota_reservation_ttl_minutes", 15))
    reservation = _mapping(
        await session.execute(
            text(
                "INSERT INTO membership_quota_reservations "
                "(id,quota_bucket_id,user_id,source_module,source_reference_id,quantity,status,idempotency_key,expires_at) "
                "VALUES (:id,:bucket,:user,:module,:reference,:quantity,'reserved',:key,:expires_at) RETURNING *"
            ),
            {
                "id": reservation_id,
                "bucket": bucket["id"],
                "user": user_id,
                "module": source_module,
                "reference": source_reference_id,
                "quantity": quantity,
                "key": idempotency_key,
                "expires_at": datetime.now(UTC) + timedelta(minutes=ttl),
            },
        )
    )
    await session.execute(
        text(
            "INSERT INTO membership_quota_ledger "
            "(quota_bucket_id,user_id,operation,quantity,source_module,source_reference_id,idempotency_key,before_snapshot,after_snapshot) "
            "VALUES (:bucket,:user,'reserve',:quantity,:module,:reference,:key,CAST(:before AS jsonb),CAST(:after AS jsonb))"
        ),
        {
            "bucket": bucket["id"],
            "user": user_id,
            "quantity": quantity,
            "module": source_module,
            "reference": source_reference_id,
            "key": f"reserve:{idempotency_key}",
            "before": _json(before),
            "after": _json(_snapshot(updated)),
        },
    )
    await _publish(
        session,
        "membership.quota.reserved",
        account["id"],
        {
            "user_id": str(user_id),
            "benefit_code": benefit_code,
            "reservation_id": str(reservation_id),
            "quantity": quantity,
        },
    )
    await session.commit()
    assert reservation is not None
    return reservation


async def finalize_reservation(
    session: AsyncSession,
    *,
    user_id: UUID,
    reservation_id: UUID,
    idempotency_key: str,
    consume: bool,
) -> dict[str, Any]:
    reservation = _mapping(
        await session.execute(
            text(
                "SELECT r.*,b.membership_account_id,b.benefit_code FROM membership_quota_reservations r "
                "JOIN membership_quota_buckets b ON b.id=r.quota_bucket_id "
                "WHERE r.id=:id AND r.user_id=:user FOR UPDATE"
            ),
            {"id": reservation_id, "user": user_id},
        )
    )
    if reservation is None:
        raise VavError(
            "QUOTA_RESERVATION_NOT_FOUND", "Quota reservation was not found.", status_code=404
        )
    target = "consumed" if consume else "released"
    if reservation["status"] == target:
        return reservation
    if reservation["status"] != "reserved":
        raise VavError(
            "QUOTA_RESERVATION_FINAL", "Quota reservation is already final.", status_code=409
        )
    if consume and reservation["expires_at"] and reservation["expires_at"] <= datetime.now(UTC):
        consume = False
        target = "expired"
    bucket = _mapping(
        await session.execute(
            text("SELECT * FROM membership_quota_buckets WHERE id=:id FOR UPDATE"),
            {"id": reservation["quota_bucket_id"]},
        )
    )
    assert bucket is not None
    before = _snapshot(bucket)
    consumed_delta = reservation["quantity"] if consume else 0
    updated = _mapping(
        await session.execute(
            text(
                "UPDATE membership_quota_buckets SET reserved_quantity=reserved_quantity-:quantity,"
                "consumed_quantity=consumed_quantity+:consumed,version=version+1,updated_at=now() "
                "WHERE id=:id AND reserved_quantity >= :quantity RETURNING *"
            ),
            {"quantity": reservation["quantity"], "consumed": consumed_delta, "id": bucket["id"]},
        )
    )
    if updated is None:
        raise VavError(
            "QUOTA_INVARIANT_VIOLATION", "Quota reservation state is inconsistent.", status_code=409
        )
    finalized = _mapping(
        await session.execute(
            text(
                "UPDATE membership_quota_reservations SET status=:status,"
                "consumed_at=CASE WHEN :status='consumed' THEN now() ELSE consumed_at END,"
                "released_at=CASE WHEN :status IN ('released','expired') THEN now() ELSE released_at END "
                "WHERE id=:id RETURNING *"
            ),
            {"status": target, "id": reservation_id},
        )
    )
    operation = "consume" if consume else "release"
    await session.execute(
        text(
            "INSERT INTO membership_quota_ledger "
            "(quota_bucket_id,user_id,operation,quantity,source_module,source_reference_id,idempotency_key,before_snapshot,after_snapshot) "
            "VALUES (:bucket,:user,:operation,:quantity,:module,:reference,:key,CAST(:before AS jsonb),CAST(:after AS jsonb)) "
            "ON CONFLICT (quota_bucket_id,idempotency_key) DO NOTHING"
        ),
        {
            "bucket": bucket["id"],
            "user": user_id,
            "operation": operation,
            "quantity": reservation["quantity"],
            "module": reservation["source_module"],
            "reference": reservation["source_reference_id"],
            "key": f"{operation}:{idempotency_key}",
            "before": _json(before),
            "after": _json(_snapshot(updated)),
        },
    )
    topic = "membership.quota.consumed" if consume else "membership.quota.released"
    await _publish(
        session,
        topic,
        reservation["membership_account_id"],
        {
            "user_id": str(user_id),
            "benefit_code": reservation["benefit_code"],
            "reservation_id": str(reservation_id),
            "quantity": reservation["quantity"],
        },
    )
    await session.commit()
    assert finalized is not None
    return finalized


async def release_expired(session: AsyncSession, limit: int = 500) -> int:
    ids = list(
        (
            await session.execute(
                text(
                    "SELECT id,user_id FROM membership_quota_reservations WHERE status='reserved' "
                    "AND expires_at <= now() ORDER BY expires_at LIMIT :limit FOR UPDATE SKIP LOCKED"
                ),
                {"limit": limit},
            )
        ).mappings()
    )
    for row in ids:
        await finalize_reservation(
            session,
            user_id=row["user_id"],
            reservation_id=row["id"],
            idempotency_key=f"expiry-{row['id']}",
            consume=False,
        )
    return len(ids)


async def adjust_quota(
    session: AsyncSession,
    *,
    actor_id: UUID,
    bucket_id: UUID,
    quantity: int,
    adjustment_type: str,
    reason_code: str,
    reason_encrypted: str | None,
    idempotency_key: str,
) -> dict[str, Any]:
    bucket = _mapping(
        await session.execute(
            text("SELECT * FROM membership_quota_buckets WHERE id=:id FOR UPDATE"),
            {"id": bucket_id},
        )
    )
    if bucket is None:
        raise VavError("QUOTA_BUCKET_NOT_FOUND", "Quota bucket was not found.", status_code=404)
    existing = _mapping(
        await session.execute(
            text(
                "SELECT * FROM membership_quota_adjustments WHERE quota_bucket_id=:bucket AND idempotency_key=:key"
            ),
            {"bucket": bucket_id, "key": idempotency_key},
        )
    )
    if existing:
        return existing
    threshold = int(getattr(get_settings(), "membership_quota_max_adjustment_without_approval", 10))
    auto_apply = abs(quantity) <= threshold
    adjustment = _mapping(
        await session.execute(
            text(
                "INSERT INTO membership_quota_adjustments "
                "(quota_bucket_id,adjustment_type,quantity,reason_code,reason_encrypted,created_by,idempotency_key,status,applied_at) "
                "VALUES (:bucket,:type,:quantity,:reason_code,:reason,:actor,:key,:status,CASE WHEN :applied THEN now() END) RETURNING *"
            ),
            {
                "bucket": bucket_id,
                "type": adjustment_type,
                "quantity": quantity,
                "reason_code": reason_code,
                "reason": reason_encrypted,
                "actor": actor_id,
                "key": idempotency_key,
                "status": "applied" if auto_apply else "pending_approval",
                "applied": auto_apply,
            },
        )
    )
    if auto_apply:
        new_allocated = int(bucket["allocated_quantity"]) + quantity
        if new_allocated < int(bucket["consumed_quantity"]) + int(bucket["reserved_quantity"]):
            raise VavError(
                "QUOTA_ADJUSTMENT_INVALID",
                "Adjustment would violate consumed quota history.",
                status_code=409,
            )
        await session.execute(
            text(
                "UPDATE membership_quota_buckets SET allocated_quantity=:allocated,version=version+1,updated_at=now() WHERE id=:id"
            ),
            {"allocated": new_allocated, "id": bucket_id},
        )
    await _audit(
        session,
        "membership.quota.adjusted",
        actor_id=actor_id,
        account_id=bucket["membership_account_id"],
        reason_code=reason_code,
        metadata={
            "bucket_id": str(bucket_id),
            "quantity": quantity,
            "status": "applied" if auto_apply else "pending_approval",
        },
    )
    await session.commit()
    assert adjustment is not None
    return adjustment
