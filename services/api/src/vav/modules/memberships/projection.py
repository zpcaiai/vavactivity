"""Idempotent Commerce/Entitlement to membership projection."""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.memberships.service import _audit, _json, _mapping, _publish


def _quota_window(
    period: str, starts_at: datetime, ends_at: datetime | None
) -> tuple[datetime, datetime | None]:
    moment = starts_at.astimezone(UTC)
    if period == "calendar_day":
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    if period == "calendar_week":
        start = (moment - timedelta(days=moment.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return start, start + timedelta(days=7)
    if period == "calendar_month":
        start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
        return start, next_month
    return moment, ends_at


async def _allocate_plan(
    session: AsyncSession,
    *,
    account_id: UUID,
    cycle_id: UUID | None,
    plan_version_id: UUID,
    starts_at: datetime,
    ends_at: datetime | None,
) -> None:
    benefits = list(
        (
            await session.execute(
                text(
                    "SELECT b.benefit_definition_id,b.benefit_value,d.benefit_code,d.benefit_type "
                    "FROM membership_plan_benefits b JOIN membership_benefit_definitions d "
                    "ON d.id=b.benefit_definition_id WHERE b.membership_plan_version_id=:version AND d.status='active'"
                ),
                {"version": plan_version_id},
            )
        ).mappings()
    )
    for benefit in benefits:
        await session.execute(
            text(
                "INSERT INTO membership_benefit_grants "
                "(membership_account_id,membership_cycle_id,benefit_definition_id,benefit_value,status,starts_at,expires_at) "
                "VALUES (:account,:cycle,:definition,CAST(:value AS jsonb),'active',:starts,:ends) "
                "ON CONFLICT (membership_account_id,benefit_definition_id,starts_at) DO NOTHING"
            ),
            {
                "account": account_id,
                "cycle": cycle_id,
                "definition": benefit["benefit_definition_id"],
                "value": _json(benefit["benefit_value"]),
                "starts": starts_at,
                "ends": ends_at,
            },
        )
        value = benefit["benefit_value"] or {}
        if benefit["benefit_type"] != "quota":
            continue
        limit = int(value.get("limit", 0))
        period = str(value.get("period", "membership_cycle"))
        quota_starts, quota_ends = _quota_window(period, starts_at, ends_at)
        await session.execute(
            text(
                "INSERT INTO membership_quota_buckets "
                "(membership_account_id,membership_cycle_id,benefit_code,period_type,period_starts_at,period_ends_at,allocated_quantity,status) "
                "VALUES (:account,:cycle,:code,:period,:starts,:ends,:quantity,'active') "
                "ON CONFLICT (membership_account_id,benefit_code,period_starts_at) DO NOTHING"
            ),
            {
                "account": account_id,
                "cycle": cycle_id,
                "code": benefit["benefit_code"],
                "period": period,
                "starts": quota_starts,
                "ends": quota_ends,
                "quantity": limit,
            },
        )


async def refresh_periodic_quotas(session: AsyncSession) -> int:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT a.id AS account_id,a.current_cycle_id,b.benefit_value,d.benefit_code "
                    "FROM membership_accounts a JOIN membership_plan_benefits b "
                    "ON b.membership_plan_version_id=a.membership_plan_version_id "
                    "JOIN membership_benefit_definitions d ON d.id=b.benefit_definition_id "
                    "WHERE a.status IN ('active','trialing','grace_period','cancel_scheduled') "
                    "AND d.benefit_type='quota' AND d.status='active'"
                )
            )
        ).mappings()
    )
    created = 0
    now = datetime.now(UTC)
    for row in rows:
        value = row["benefit_value"] or {}
        period = str(value.get("period", "membership_cycle"))
        if period not in {"calendar_day", "calendar_week", "calendar_month"}:
            continue
        starts, ends = _quota_window(period, now, None)
        result = await session.execute(
            text(
                "INSERT INTO membership_quota_buckets "
                "(membership_account_id,membership_cycle_id,benefit_code,period_type,period_starts_at,period_ends_at,allocated_quantity,status) "
                "VALUES (:account,:cycle,:code,:period,:starts,:ends,:quantity,'active') "
                "ON CONFLICT (membership_account_id,benefit_code,period_starts_at) DO NOTHING RETURNING id"
            ),
            {
                "account": row["account_id"],
                "cycle": row["current_cycle_id"],
                "code": row["benefit_code"],
                "period": period,
                "starts": starts,
                "ends": ends,
                "quantity": int(value.get("limit", 0)),
            },
        )
        created += int(result.first() is not None)
    await session.execute(
        text(
            "UPDATE membership_quota_buckets SET status='expired',updated_at=now() "
            "WHERE status='active' AND period_ends_at IS NOT NULL AND period_ends_at <= now()"
        )
    )
    await session.commit()
    return created


async def ensure_free_membership(
    session: AsyncSession, user_id: UUID, *, commit: bool = True
) -> dict[str, Any]:
    existing = _mapping(
        await session.execute(
            text(
                "SELECT * FROM membership_accounts WHERE user_id=:user AND source_type='free_default' AND status='active' FOR UPDATE"
            ),
            {"user": user_id},
        )
    )
    if existing:
        return existing
    plan = _mapping(
        await session.execute(
            text(
                "SELECT p.id AS plan_id,p.current_version_id FROM membership_plans p "
                "JOIN membership_plan_versions v ON v.id=p.current_version_id "
                "WHERE p.plan_type='free' AND p.status='active' AND v.status='active' ORDER BY p.display_order LIMIT 1"
            )
        )
    )
    if plan is None:
        raise VavError(
            "MEMBERSHIP_FREE_PLAN_MISSING",
            "The default free membership plan is unavailable.",
            status_code=503,
        )
    now = datetime.now(UTC)
    account_id = uuid4()
    account = _mapping(
        await session.execute(
            text(
                "INSERT INTO membership_accounts (id,user_id,membership_plan_id,membership_plan_version_id,status,source_type,starts_at) "
                "VALUES (:id,:user,:plan,:version,'active','free_default',:starts) RETURNING *"
            ),
            {
                "id": account_id,
                "user": user_id,
                "plan": plan["plan_id"],
                "version": plan["current_version_id"],
                "starts": now,
            },
        )
    )
    await _allocate_plan(
        session,
        account_id=account_id,
        cycle_id=None,
        plan_version_id=plan["current_version_id"],
        starts_at=now,
        ends_at=None,
    )
    await _audit(
        session,
        "membership.account.created",
        actor_id=user_id,
        account_id=account_id,
        metadata={"source_type": "free_default"},
    )
    await _publish(
        session, "membership.free_account.created", account_id, {"user_id": str(user_id)}
    )
    if commit:
        await session.commit()
    assert account is not None
    return account


async def _active_entitlement(
    session: AsyncSession, user_id: UUID, entitlement_id: UUID | None
) -> dict[str, Any] | None:
    if entitlement_id:
        clause = "id=:id"
    else:
        clause = "user_id=:user AND lower(entitlement_type)='membership_access' ORDER BY updated_at DESC LIMIT 1"
    return _mapping(
        await session.execute(
            text(f"SELECT * FROM entitlements WHERE {clause}"),
            {"id": entitlement_id, "user": user_id},
        )
    )


async def _activate_subscription(
    session: AsyncSession,
    subscription_id: UUID,
    entitlement_id: UUID | None,
    *,
    renewed: bool,
) -> dict[str, Any]:
    subscription = _mapping(
        await session.execute(
            text("SELECT * FROM subscriptions WHERE id=:id FOR UPDATE"), {"id": subscription_id}
        )
    )
    if subscription is None:
        raise VavError(
            "MEMBERSHIP_SUBSCRIPTION_NOT_FOUND",
            "Commerce subscription was not found.",
            status_code=404,
        )
    mapping = _mapping(
        await session.execute(
            text(
                "SELECT * FROM membership_sku_mappings WHERE catalog_sku_id=:sku AND valid_from <= now() "
                "AND (valid_until IS NULL OR valid_until > now()) ORDER BY valid_from DESC LIMIT 1"
            ),
            {"sku": subscription["sku_id"]},
        )
    )
    if mapping is None:
        raise VavError(
            "MEMBERSHIP_SKU_MAPPING_MISSING",
            "Subscription SKU is not mapped to a membership plan.",
            status_code=409,
        )
    entitlement = await _active_entitlement(session, subscription["user_id"], entitlement_id)
    entitlement_active = bool(
        entitlement
        and entitlement["status"] == "active"
        and (entitlement["starts_at"] is None or entitlement["starts_at"] <= datetime.now(UTC))
        and (entitlement["expires_at"] is None or entitlement["expires_at"] > datetime.now(UTC))
    )
    subscription_active = subscription["status"] in {"active", "trialing"}
    status = (
        "trialing"
        if subscription["status"] == "trialing" and entitlement_active
        else "active"
        if subscription_active and entitlement_active
        else "pending"
    )
    account = _mapping(
        await session.execute(
            text(
                "SELECT * FROM membership_accounts WHERE commerce_subscription_id=:subscription FOR UPDATE"
            ),
            {"subscription": subscription_id},
        )
    )
    if account is None:
        account_id = uuid4()
        account = _mapping(
            await session.execute(
                text(
                    "INSERT INTO membership_accounts "
                    "(id,user_id,membership_plan_id,membership_plan_version_id,status,source_type,catalog_sku_id,commerce_subscription_id,entitlement_id,starts_at,expires_at,cancel_at_period_end) "
                    "VALUES (:id,:user,:plan,:version,:status,'paid_subscription',:sku,:subscription,:entitlement,:starts,:ends,:cancel) RETURNING *"
                ),
                {
                    "id": account_id,
                    "user": subscription["user_id"],
                    "plan": mapping["membership_plan_id"],
                    "version": mapping["membership_plan_version_id"],
                    "status": status,
                    "sku": subscription["sku_id"],
                    "subscription": subscription_id,
                    "entitlement": entitlement["id"] if entitlement else None,
                    "starts": subscription["current_period_start"] or datetime.now(UTC),
                    "ends": subscription["current_period_end"],
                    "cancel": subscription["cancel_at_period_end"],
                },
            )
        )
    else:
        account = _mapping(
            await session.execute(
                text(
                    "UPDATE membership_accounts SET membership_plan_id=:plan,membership_plan_version_id=:version,status=:status,"
                    "entitlement_id=:entitlement,expires_at=:ends,cancel_at_period_end=:cancel,version=version+1,updated_at=now() "
                    "WHERE id=:id RETURNING *"
                ),
                {
                    "plan": mapping["membership_plan_id"],
                    "version": mapping["membership_plan_version_id"],
                    "status": status,
                    "entitlement": entitlement["id"] if entitlement else None,
                    "ends": subscription["current_period_end"],
                    "cancel": subscription["cancel_at_period_end"],
                    "id": account["id"],
                },
            )
        )
    assert account is not None
    await ensure_free_membership(session, subscription["user_id"], commit=False)
    if status == "pending":
        return account
    assert entitlement is not None
    starts = subscription["current_period_start"] or datetime.now(UTC)
    ends = subscription["current_period_end"] or starts + timedelta(days=31)
    current_cycle = (
        _mapping(
            await session.execute(
                text("SELECT * FROM membership_cycles WHERE id=:id FOR UPDATE"),
                {"id": account["current_cycle_id"]},
            )
        )
        if account["current_cycle_id"]
        else None
    )
    if renewed and current_cycle and current_cycle["ends_at"] <= starts:
        await session.execute(
            text(
                "UPDATE membership_cycles SET status='closed',closed_at=now(),updated_at=now() WHERE id=:id"
            ),
            {"id": current_cycle["id"]},
        )
        await session.execute(
            text(
                "UPDATE membership_quota_buckets SET status='closed',updated_at=now() WHERE membership_cycle_id=:cycle AND status='active'"
            ),
            {"cycle": current_cycle["id"]},
        )
        current_cycle = None
    if (
        current_cycle is None
        or current_cycle["starts_at"] != starts
        or current_cycle["ends_at"] != ends
    ):
        cycle_id = uuid4()
        cycle_number = int(
            (
                await session.execute(
                    text(
                        "SELECT COALESCE(MAX(cycle_number),0)+1 FROM membership_cycles WHERE membership_account_id=:account"
                    ),
                    {"account": account["id"]},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                "INSERT INTO membership_cycles (id,membership_account_id,cycle_number,status,starts_at,ends_at,source_subscription_period_start,source_subscription_period_end) "
                "VALUES (:id,:account,:number,'active',:starts,:ends,:starts,:ends)"
            ),
            {
                "id": cycle_id,
                "account": account["id"],
                "number": cycle_number,
                "starts": starts,
                "ends": ends,
            },
        )
        await session.execute(
            text("UPDATE membership_accounts SET current_cycle_id=:cycle WHERE id=:account"),
            {"cycle": cycle_id, "account": account["id"]},
        )
        await _allocate_plan(
            session,
            account_id=account["id"],
            cycle_id=cycle_id,
            plan_version_id=mapping["membership_plan_version_id"],
            starts_at=starts,
            ends_at=ends,
        )
        await session.execute(
            text("UPDATE membership_cycles SET quota_allocated_at=now() WHERE id=:cycle"),
            {"cycle": cycle_id},
        )
        await _publish(
            session,
            "membership.cycle.started",
            account["id"],
            {"user_id": str(subscription["user_id"]), "cycle_id": str(cycle_id)},
        )
    topic = "membership.renewed" if renewed else "membership.activated"
    await _publish(
        session,
        topic,
        account["id"],
        {
            "user_id": str(subscription["user_id"]),
            "subscription_id": str(subscription_id),
            "entitlement_id": str(entitlement["id"]),
        },
    )
    return account


async def project_event(
    session: AsyncSession,
    *,
    source_module: str,
    source_event_id: UUID,
    event_type: str,
    event_version: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Project one authoritative source event exactly once."""
    inserted = _mapping(
        await session.execute(
            text(
                "INSERT INTO membership_inbox_events (source_module,source_event_id,event_type,event_version,payload,status) "
                "VALUES (:source,:event_id,:event_type,:version,CAST(:payload AS jsonb),'processing') "
                "ON CONFLICT (source_module,source_event_id) DO NOTHING RETURNING *"
            ),
            {
                "source": source_module,
                "event_id": source_event_id,
                "event_type": event_type,
                "version": event_version,
                "payload": json.dumps(payload, default=str),
            },
        )
    )
    if inserted is None:
        existing = _mapping(
            await session.execute(
                text(
                    "SELECT * FROM membership_inbox_events WHERE source_module=:source AND source_event_id=:event"
                ),
                {"source": source_module, "event": source_event_id},
            )
        )
        return {"duplicate": True, "status": existing["status"] if existing else "unknown"}
    try:
        subscription_id = (
            UUID(str(payload["subscription_id"])) if payload.get("subscription_id") else None
        )
        entitlement_id = (
            UUID(str(payload["entitlement_id"])) if payload.get("entitlement_id") else None
        )
        account: dict[str, Any] | None = None
        if event_type in {
            "commerce.subscription.activated",
            "commerce.subscription.updated",
            "commerce.subscription.renewed",
            "entitlement.activated",
        }:
            if subscription_id is None and entitlement_id is not None:
                account = _mapping(
                    await session.execute(
                        text(
                            "SELECT * FROM membership_accounts WHERE entitlement_id=:entitlement FOR UPDATE"
                        ),
                        {"entitlement": entitlement_id},
                    )
                )
                subscription_id = account["commerce_subscription_id"] if account else None
            if subscription_id is None:
                raise VavError(
                    "MEMBERSHIP_EVENT_INVALID",
                    "An authoritative subscription id is required.",
                    status_code=422,
                )
            account = await _activate_subscription(
                session,
                subscription_id,
                entitlement_id,
                renewed=event_type == "commerce.subscription.renewed",
            )
        elif subscription_id is not None:
            account = _mapping(
                await session.execute(
                    text(
                        "SELECT * FROM membership_accounts WHERE commerce_subscription_id=:subscription FOR UPDATE"
                    ),
                    {"subscription": subscription_id},
                )
            )
            if account is None:
                raise VavError(
                    "MEMBERSHIP_ACCOUNT_NOT_FOUND",
                    "Membership projection does not exist.",
                    status_code=404,
                )
            target = {
                "commerce.subscription.payment_failed": "past_due",
                "commerce.subscription.cancel_scheduled": "cancel_scheduled",
                "commerce.subscription.cancelled": "cancelled",
                "commerce.subscription.expired": "expired",
            }.get(event_type)
            if target:
                grace_end = None
                if target == "past_due":
                    target = "grace_period"
                    grace_end = datetime.now(UTC) + timedelta(days=3)
                await session.execute(
                    text(
                        "UPDATE membership_accounts SET status=:status,grace_period_ends_at=:grace,version=version+1,updated_at=now() WHERE id=:id"
                    ),
                    {"status": target, "grace": grace_end, "id": account["id"]},
                )
                await _publish(
                    session,
                    f"membership.{target}",
                    account["id"],
                    {"user_id": str(account["user_id"]), "subscription_id": str(subscription_id)},
                )
        await session.execute(
            text(
                "UPDATE membership_inbox_events SET status='processed',processed_at=now(),attempts=attempts+1 WHERE id=:id"
            ),
            {"id": inserted["id"]},
        )
        await session.commit()
        return {
            "duplicate": False,
            "status": "processed",
            "membership_account_id": account["id"] if account else None,
        }
    except Exception:
        await session.rollback()
        await session.execute(
            text(
                "INSERT INTO membership_inbox_events (source_module,source_event_id,event_type,event_version,payload,status,attempts,error_code) "
                "VALUES (:source,:event_id,:event_type,:version,CAST(:payload AS jsonb),'retry',1,'PROJECTION_FAILED') "
                "ON CONFLICT (source_module,source_event_id) DO UPDATE SET status='retry',attempts=membership_inbox_events.attempts+1,error_code='PROJECTION_FAILED'"
            ),
            {
                "source": source_module,
                "event_id": source_event_id,
                "event_type": event_type,
                "version": event_version,
                "payload": json.dumps(payload, default=str),
            },
        )
        await session.commit()
        raise
