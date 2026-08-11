"""Membership plan, lifecycle and access-decision services.

All writes are transactional. Plan versions are immutable once approved, paid
access fails closed when its Commerce entitlement is not active, and the
membership layer never grants a safety or privacy bypass.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.memberships.domain import (
    REGISTERED_BENEFIT_CODES,
    effective_policy,
    validate_benefit,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _mapping(result: Any) -> dict[str, Any] | None:
    row = result.mappings().first()
    return dict(row) if row else None


def _enabled() -> None:
    if not getattr(get_settings(), "membership_enabled", True):
        raise VavError(
            "MEMBERSHIP_DISABLED", "Membership services are unavailable.", status_code=503
        )


async def _publish(
    session: AsyncSession,
    topic: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,'membership_account',:aggregate_id,CAST(:payload AS jsonb))"
        ),
        {"topic": topic, "aggregate_id": str(aggregate_id), "payload": _json(payload)},
    )


async def _audit(
    session: AsyncSession,
    event_type: str,
    *,
    actor_id: UUID | None,
    account_id: UUID | None = None,
    reason_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO membership_audit_events "
            "(actor_user_id,membership_account_id,event_type,reason_code,safe_metadata) "
            "VALUES (:actor,:account,:event,:reason,CAST(:metadata AS jsonb))"
        ),
        {
            "actor": actor_id,
            "account": account_id,
            "event": event_type,
            "reason": reason_code,
            "metadata": _json(metadata or {}),
        },
    )


async def list_public_plans(session: AsyncSession, locale: str) -> list[dict[str, Any]]:
    _enabled()
    rows = (
        await session.execute(
            text(
                "SELECT p.id,p.plan_code,p.plan_type,p.featured,p.display_order,v.id AS version_id,"
                "COALESCE(l.name,p.internal_name) AS name,l.short_description,l.benefit_summary,l.limitation_summary "
                "FROM membership_plans p JOIN membership_plan_versions v ON v.id=p.current_version_id "
                "LEFT JOIN membership_plan_localizations l ON l.membership_plan_version_id=v.id "
                "AND l.locale=COALESCE(:locale,p.default_locale) "
                "WHERE p.status='active' AND v.status='active' "
                "AND v.valid_from <= now() AND (v.valid_until IS NULL OR v.valid_until > now()) "
                "ORDER BY p.display_order,p.plan_code"
            ),
            {"locale": locale},
        )
    ).mappings()
    return [dict(row) for row in rows]


async def get_public_plan(session: AsyncSession, plan_code: str, locale: str) -> dict[str, Any]:
    plans = await list_public_plans(session, locale)
    plan = next((item for item in plans if item["plan_code"] == plan_code), None)
    if plan is None:
        raise VavError(
            "MEMBERSHIP_PLAN_NOT_FOUND", "Membership plan was not found.", status_code=404
        )
    benefits = (
        await session.execute(
            text(
                "SELECT d.benefit_code,d.benefit_type,b.benefit_value,b.sort_order "
                "FROM membership_plan_benefits b JOIN membership_benefit_definitions d "
                "ON d.id=b.benefit_definition_id WHERE b.membership_plan_version_id=:version "
                "AND d.status='active' ORDER BY b.sort_order,d.benefit_code"
            ),
            {"version": plan["version_id"]},
        )
    ).mappings()
    plan["benefits"] = [dict(row) for row in benefits]
    return plan


async def _effective_account(
    session: AsyncSession, user_id: UUID, *, lock: bool = False
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE OF a" if lock else ""
    return _mapping(
        await session.execute(
            text(
                "SELECT a.*,p.plan_code,p.plan_type,p.internal_name,v.semantic_version,"
                "c.ends_at AS current_cycle_ends_at "
                "FROM membership_accounts a JOIN membership_plans p ON p.id=a.membership_plan_id "
                "JOIN membership_plan_versions v ON v.id=a.membership_plan_version_id "
                "LEFT JOIN membership_cycles c ON c.id=a.current_cycle_id "
                "WHERE a.user_id=:user_id AND a.status IN ('active','trialing','grace_period','past_due','cancel_scheduled') "
                "ORDER BY CASE WHEN a.source_type='free_default' THEN 1 ELSE 0 END,a.created_at DESC LIMIT 1"
                + suffix
            ),
            {"user_id": user_id},
        )
    )


async def membership_summary(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    _enabled()
    account = await _effective_account(session, user_id)
    if account is None:
        raise VavError("MEMBERSHIP_NOT_FOUND", "No active membership was found.", status_code=404)
    benefits = (
        await session.execute(
            text(
                "SELECT d.benefit_code,d.benefit_type,g.benefit_value,g.starts_at,g.expires_at "
                "FROM membership_benefit_grants g JOIN membership_benefit_definitions d "
                "ON d.id=g.benefit_definition_id WHERE g.membership_account_id=:account "
                "AND g.status='active' AND g.starts_at <= now() AND (g.expires_at IS NULL OR g.expires_at > now()) "
                "ORDER BY d.benefit_code"
            ),
            {"account": account["id"]},
        )
    ).mappings()
    quotas = (
        await session.execute(
            text(
                "SELECT id,benefit_code,period_type,period_starts_at,period_ends_at,allocated_quantity,"
                "consumed_quantity,reserved_quantity,rollover_quantity,"
                "allocated_quantity+rollover_quantity-consumed_quantity-reserved_quantity AS remaining_quantity "
                "FROM membership_quota_buckets WHERE membership_account_id=:account AND status='active' "
                "AND period_starts_at <= now() AND (period_ends_at IS NULL OR period_ends_at > now()) "
                "ORDER BY benefit_code"
            ),
            {"account": account["id"]},
        )
    ).mappings()
    return {
        "membership_account_id": account["id"],
        "plan_code": account["plan_code"],
        "plan_name": account["internal_name"],
        "plan_version": account["semantic_version"],
        "status": account["status"],
        "source_type": account["source_type"],
        "starts_at": account["starts_at"],
        "expires_at": account["expires_at"],
        "current_cycle_ends_at": account["current_cycle_ends_at"],
        "cancel_at_period_end": account["cancel_at_period_end"],
        "grace_period_ends_at": account["grace_period_ends_at"],
        "benefits": [dict(row) for row in benefits],
        "quotas": [dict(row) for row in quotas],
    }


async def membership_history(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT a.id,p.plan_code,p.internal_name,a.status,a.source_type,a.starts_at,a.expires_at,"
                "a.cancel_at_period_end,a.created_at,a.updated_at FROM membership_accounts a "
                "JOIN membership_plans p ON p.id=a.membership_plan_id WHERE a.user_id=:user "
                "ORDER BY a.created_at DESC"
            ),
            {"user": user_id},
        )
    ).mappings()
    return [dict(row) for row in rows]


def _scope_allows(
    value: dict[str, Any], resource_type: str | None, resource_id: UUID | None
) -> bool:
    if resource_id is None:
        return True
    if value.get("scope_type") in {None, "all"}:
        return True
    resource_ids = {str(item) for item in value.get("resource_ids", [])}
    typed_ids = {str(item) for item in value.get(f"{resource_type}_ids", [])}
    return str(resource_id) in resource_ids | typed_ids


async def decide_access(
    session: AsyncSession,
    *,
    user_id: UUID,
    capability_code: str,
    resource_type: str | None,
    resource_id: UUID | None,
    requested_quantity: int,
) -> dict[str, Any]:
    """Fail-closed membership-only decision; owning modules still enforce eligibility."""
    _enabled()
    account = await _effective_account(session, user_id)
    decision: dict[str, Any] = {
        "allowed": False,
        "reason_code": "MEMBERSHIP_REQUIRED",
        "membership_account_id": None,
        "membership_plan_version_id": None,
        "benefit_code": capability_code,
        "benefit_value": None,
        "quota_required": False,
        "quota_remaining": None,
        "valid_until": None,
        "decision_version": "membership-access-v1",
    }
    if account is None:
        return decision
    decision.update(
        membership_account_id=account["id"],
        membership_plan_version_id=account["membership_plan_version_id"],
        valid_until=account["expires_at"],
    )
    if account["status"] not in {"active", "trialing", "grace_period", "cancel_scheduled"}:
        decision["reason_code"] = "MEMBERSHIP_INACTIVE"
        return decision
    if account["expires_at"] is not None and account["expires_at"] <= datetime.now(UTC):
        decision["reason_code"] = "MEMBERSHIP_EXPIRED"
        return decision
    if account["source_type"] != "free_default":
        entitlement = _mapping(
            await session.execute(
                text(
                    "SELECT status,starts_at,expires_at FROM entitlements WHERE id=:id AND user_id=:user"
                ),
                {"id": account["entitlement_id"], "user": user_id},
            )
        )
        if (
            entitlement is None
            or entitlement["status"] != "active"
            or (entitlement["starts_at"] and entitlement["starts_at"] > datetime.now(UTC))
            or (entitlement["expires_at"] and entitlement["expires_at"] <= datetime.now(UTC))
        ):
            decision["reason_code"] = "ENTITLEMENT_INACTIVE"
            return decision
    benefit = _mapping(
        await session.execute(
            text(
                "SELECT d.benefit_type,g.benefit_value,g.expires_at FROM membership_benefit_grants g "
                "JOIN membership_benefit_definitions d ON d.id=g.benefit_definition_id "
                "WHERE g.membership_account_id=:account AND d.benefit_code=:code AND d.status='active' "
                "AND g.status='active' AND g.starts_at <= now() AND (g.expires_at IS NULL OR g.expires_at > now()) "
                "ORDER BY g.starts_at DESC LIMIT 1"
            ),
            {"account": account["id"], "code": capability_code},
        )
    )
    if benefit is None:
        decision["reason_code"] = "BENEFIT_NOT_INCLUDED"
        return decision
    value = benefit["benefit_value"] or {}
    decision["benefit_value"] = value
    if not _scope_allows(value, resource_type, resource_id):
        decision["reason_code"] = "RESOURCE_NOT_INCLUDED"
        return decision
    if benefit["benefit_type"] == "quota":
        decision["quota_required"] = True
        quota = _mapping(
            await session.execute(
                text(
                    "SELECT allocated_quantity+rollover_quantity-consumed_quantity-reserved_quantity AS remaining "
                    "FROM membership_quota_buckets WHERE membership_account_id=:account AND benefit_code=:code "
                    "AND status='active' AND period_starts_at <= now() "
                    "AND (period_ends_at IS NULL OR period_ends_at > now()) ORDER BY period_starts_at DESC LIMIT 1"
                ),
                {"account": account["id"], "code": capability_code},
            )
        )
        remaining = int(quota["remaining"]) if quota else 0
        decision["quota_remaining"] = remaining
        if remaining < requested_quantity:
            decision["reason_code"] = "QUOTA_EXHAUSTED"
            return decision
    decision["allowed"] = True
    decision["reason_code"] = None
    return decision


async def change_preview(
    session: AsyncSession, user_id: UUID, to_plan_code: str, change_type: str
) -> dict[str, Any]:
    account = await _effective_account(session, user_id)
    if account is None:
        raise VavError("MEMBERSHIP_NOT_FOUND", "No active membership was found.", status_code=404)
    target = _mapping(
        await session.execute(
            text(
                "SELECT p.id AS plan_id,p.plan_code,p.internal_name,p.plan_type,v.id AS version_id,v.semantic_version "
                "FROM membership_plans p JOIN membership_plan_versions v ON v.id=p.current_version_id "
                "WHERE p.plan_code=:code AND p.status='active' AND v.status='active'"
            ),
            {"code": to_plan_code},
        )
    )
    if target is None:
        raise VavError(
            "MEMBERSHIP_PLAN_NOT_FOUND",
            "Target membership plan was not found.",
            status_code=404,
        )
    if target["version_id"] == account["membership_plan_version_id"] and change_type not in {
        "cancel",
        "reactivate",
    }:
        raise VavError(
            "MEMBERSHIP_PLAN_UNCHANGED", "The target plan is already active.", status_code=409
        )
    current_codes = set(
        (
            await session.execute(
                text(
                    "SELECT d.benefit_code FROM membership_plan_benefits b JOIN membership_benefit_definitions d "
                    "ON d.id=b.benefit_definition_id WHERE b.membership_plan_version_id=:version"
                ),
                {"version": account["membership_plan_version_id"]},
            )
        ).scalars()
    )
    target_codes = set(
        (
            await session.execute(
                text(
                    "SELECT d.benefit_code FROM membership_plan_benefits b JOIN membership_benefit_definitions d "
                    "ON d.id=b.benefit_definition_id WHERE b.membership_plan_version_id=:version"
                ),
                {"version": target["version_id"]},
            )
        ).scalars()
    )
    policy = effective_policy(change_type)
    return {
        "membership_account_id": account["id"],
        "from_plan": {"code": account["plan_code"], "name": account["internal_name"]},
        "to_plan": {"code": target["plan_code"], "name": target["internal_name"]},
        "to_plan_version_id": target["version_id"],
        "change_type": change_type,
        "effective_policy": policy,
        "effective_at": account["current_cycle_ends_at"]
        if policy == "next_cycle"
        else datetime.now(UTC),
        "benefit_diff": {
            "added": sorted(target_codes - current_codes),
            "removed": sorted(current_codes - target_codes),
            "retained": sorted(current_codes & target_codes),
        },
        "quota_transition": {"preserve_consumed": True, "negative_debt": False},
        "pricing": {"source": "commerce_quote_required", "amount": None},
        "confirmation_required": True,
    }


async def create_change_request(
    session: AsyncSession,
    *,
    user_id: UUID,
    to_plan_code: str,
    change_type: str,
    idempotency_key: str,
) -> dict[str, Any]:
    existing = _mapping(
        await session.execute(
            text(
                "SELECT * FROM membership_change_requests WHERE user_id=:user AND idempotency_key=:key"
            ),
            {"user": user_id, "key": idempotency_key},
        )
    )
    if existing:
        return existing
    preview = await change_preview(session, user_id, to_plan_code, change_type)
    account = await _effective_account(session, user_id, lock=True)
    assert account is not None
    change_id = uuid4()
    row = _mapping(
        await session.execute(
            text(
                "INSERT INTO membership_change_requests "
                "(id,membership_account_id,user_id,change_type,from_plan_version_id,to_plan_version_id,effective_policy,status,benefit_diff_snapshot,quota_transition_snapshot,idempotency_key,effective_at) "
                "VALUES (:id,:account,:user,:type,:from_version,:to_version,:policy,'confirmation_required',CAST(:benefits AS jsonb),CAST(:quota AS jsonb),:key,:effective_at) RETURNING *"
            ),
            {
                "id": change_id,
                "account": account["id"],
                "user": user_id,
                "type": change_type,
                "from_version": account["membership_plan_version_id"],
                "to_version": preview["to_plan_version_id"],
                "policy": preview["effective_policy"],
                "benefits": _json(preview["benefit_diff"]),
                "quota": _json(preview["quota_transition"]),
                "key": idempotency_key,
                "effective_at": preview["effective_at"],
            },
        )
    )
    assert row is not None
    await _audit(
        session,
        "membership.change.requested",
        actor_id=user_id,
        account_id=account["id"],
        metadata={"change_id": str(change_id), "change_type": change_type},
    )
    await _publish(
        session,
        "membership.upgrade.requested"
        if change_type == "upgrade"
        else "membership.change.requested",
        account["id"],
        {"user_id": str(user_id), "change_request_id": str(change_id), "change_type": change_type},
    )
    await session.commit()
    return row


async def get_change_request(
    session: AsyncSession, user_id: UUID, change_id: UUID, *, lock: bool = False
) -> dict[str, Any]:
    row = _mapping(
        await session.execute(
            text(
                "SELECT * FROM membership_change_requests WHERE id=:id AND user_id=:user"
                + (" FOR UPDATE" if lock else "")
            ),
            {"id": change_id, "user": user_id},
        )
    )
    if row is None:
        raise VavError(
            "MEMBERSHIP_CHANGE_NOT_FOUND",
            "Membership change was not found.",
            status_code=404,
        )
    return row


async def decide_change(
    session: AsyncSession,
    *,
    user_id: UUID,
    change_id: UUID,
    expected_version: int,
    confirm: bool,
) -> dict[str, Any]:
    row = await get_change_request(session, user_id, change_id, lock=True)
    if row["version"] != expected_version:
        raise VavError(
            "MEMBERSHIP_CHANGE_CONFLICT",
            "Membership change has been updated.",
            status_code=409,
        )
    if row["status"] not in {"confirmation_required", "quoted"}:
        raise VavError(
            "MEMBERSHIP_CHANGE_NOT_ACTIONABLE",
            "Membership change is not actionable.",
            status_code=409,
        )
    status = (
        "confirmed"
        if confirm and row["effective_policy"] == "immediate"
        else "scheduled"
        if confirm
        else "cancelled"
    )
    updated = _mapping(
        await session.execute(
            text(
                "UPDATE membership_change_requests SET status=:status,confirmed_at=CASE WHEN :confirm THEN now() ELSE confirmed_at END,version=version+1,updated_at=now() WHERE id=:id RETURNING *"
            ),
            {"status": status, "confirm": confirm, "id": change_id},
        )
    )
    event = "membership.change.confirmed" if confirm else "membership.change.cancelled"
    await _audit(
        session,
        event,
        actor_id=user_id,
        account_id=row["membership_account_id"],
        metadata={"change_id": str(change_id)},
    )
    await _publish(
        session,
        event,
        row["membership_account_id"],
        {"user_id": str(user_id), "change_request_id": str(change_id)},
    )
    await session.commit()
    assert updated is not None
    return updated


async def list_admin_plans(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT p.*,v.semantic_version AS current_semantic_version FROM membership_plans p "
                "LEFT JOIN membership_plan_versions v ON v.id=p.current_version_id ORDER BY p.display_order,p.created_at"
            )
        )
    ).mappings()
    return [dict(row) for row in rows]


async def create_plan(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    _enabled()
    row = _mapping(
        await session.execute(
            text(
                "INSERT INTO membership_plans (plan_code,internal_name,plan_type,default_locale,display_order,featured,created_by,updated_by) "
                "VALUES (:plan_code,:internal_name,:plan_type,:default_locale,:display_order,:featured,:actor,:actor) RETURNING *"
            ),
            {**payload, "actor": actor_id},
        )
    )
    assert row is not None
    await _audit(
        session,
        "membership.plan.created",
        actor_id=actor_id,
        metadata={"plan_id": str(row["id"]), "plan_code": row["plan_code"]},
    )
    await session.commit()
    return row


async def update_plan(
    session: AsyncSession, plan_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    fields = {key: value for key, value in payload.items() if value is not None}
    if not fields:
        raise VavError(
            "MEMBERSHIP_PLAN_UPDATE_EMPTY",
            "No plan fields were supplied.",
            status_code=422,
        )
    assignments = ",".join(f"{key}=:{key}" for key in fields)
    row = _mapping(
        await session.execute(
            text(
                f"UPDATE membership_plans SET {assignments},updated_by=:actor,updated_at=now() WHERE id=:id AND status<>'archived' RETURNING *"
            ),
            {**fields, "actor": actor_id, "id": plan_id},
        )
    )
    if row is None:
        raise VavError(
            "MEMBERSHIP_PLAN_NOT_FOUND", "Membership plan was not found.", status_code=404
        )
    await _audit(
        session,
        "membership.plan.updated",
        actor_id=actor_id,
        metadata={"plan_id": str(plan_id), "changed_fields": sorted(fields)},
    )
    await session.commit()
    return row


async def create_plan_version(
    session: AsyncSession,
    *,
    plan_id: UUID,
    actor_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    plan = _mapping(
        await session.execute(
            text("SELECT * FROM membership_plans WHERE id=:id FOR UPDATE"), {"id": plan_id}
        )
    )
    if plan is None:
        raise VavError(
            "MEMBERSHIP_PLAN_NOT_FOUND", "Membership plan was not found.", status_code=404
        )
    number = int(
        (
            await session.execute(
                text(
                    "SELECT COALESCE(MAX(version_number),0)+1 FROM membership_plan_versions WHERE membership_plan_id=:plan"
                ),
                {"plan": plan_id},
            )
        ).scalar_one()
    )
    benefits: list[dict[str, Any]] = payload.pop("benefits")
    localizations: list[dict[str, Any]] = payload.pop("localizations")
    version_id = uuid4()
    resolved: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    for benefit in benefits:
        code = str(benefit.get("benefit_code", ""))
        if code in seen:
            raise VavError(
                "MEMBERSHIP_BENEFIT_DUPLICATE",
                "A benefit appears more than once.",
                status_code=422,
            )
        definition = _mapping(
            await session.execute(
                text(
                    "SELECT * FROM membership_benefit_definitions WHERE benefit_code=:code AND status='active' ORDER BY created_at DESC LIMIT 1"
                ),
                {"code": code},
            )
        )
        if definition is None:
            raise VavError(
                "MEMBERSHIP_BENEFIT_UNKNOWN",
                "A benefit is not registered.",
                status_code=422,
            )
        try:
            validate_benefit(code, definition["benefit_type"], benefit.get("value", {}))
        except ValueError as exc:
            raise VavError("MEMBERSHIP_BENEFIT_INVALID", str(exc), status_code=422) from exc
        seen.add(code)
        resolved.append((benefit, definition))
    await session.execute(
        text(
            "INSERT INTO membership_plan_versions (id,membership_plan_id,version_number,semantic_version,status,benefit_manifest,access_policy_snapshot,quota_policy_snapshot,valid_from,valid_until,created_by) "
            "VALUES (:id,:plan,:number,:semantic,'draft',CAST(:manifest AS jsonb),CAST(:access AS jsonb),CAST(:quota AS jsonb),:valid_from,:valid_until,:actor)"
        ),
        {
            "id": version_id,
            "plan": plan_id,
            "number": number,
            "semantic": payload["semantic_version"],
            "manifest": _json(benefits),
            "access": _json(payload["access_policy_snapshot"]),
            "quota": _json(payload["quota_policy_snapshot"]),
            "valid_from": payload["valid_from"],
            "valid_until": payload["valid_until"],
            "actor": actor_id,
        },
    )
    locales: set[str] = set()
    for localization in localizations:
        locale = str(localization.get("locale", ""))
        if not locale or locale in locales:
            raise VavError(
                "MEMBERSHIP_LOCALIZATION_INVALID",
                "Plan locales must be unique and non-empty.",
                status_code=422,
            )
        locales.add(locale)
        await session.execute(
            text(
                "INSERT INTO membership_plan_localizations (membership_plan_version_id,locale,name,short_description,description_blocks,benefit_summary,limitation_summary) "
                "VALUES (:version,:locale,:name,:short,CAST(:blocks AS jsonb),CAST(:benefits AS jsonb),CAST(:limitations AS jsonb))"
            ),
            {
                "version": version_id,
                "locale": locale,
                "name": localization.get("name"),
                "short": localization.get("short_description"),
                "blocks": _json(localization.get("description_blocks", [])),
                "benefits": _json(localization.get("benefit_summary", [])),
                "limitations": _json(localization.get("limitation_summary", [])),
            },
        )
    if plan["default_locale"] not in locales:
        raise VavError(
            "MEMBERSHIP_DEFAULT_LOCALE_MISSING",
            "The default locale is required.",
            status_code=422,
        )
    for index, (benefit, definition) in enumerate(resolved):
        await session.execute(
            text(
                "INSERT INTO membership_plan_benefits (membership_plan_version_id,benefit_definition_id,benefit_value,sort_order) "
                "VALUES (:version,:definition,CAST(:value AS jsonb),:sort)"
            ),
            {
                "version": version_id,
                "definition": definition["id"],
                "value": _json(benefit.get("value", {})),
                "sort": benefit.get("sort_order", index),
            },
        )
    await _audit(
        session,
        "membership.plan.version_created",
        actor_id=actor_id,
        metadata={"plan_id": str(plan_id), "version_id": str(version_id), "version_number": number},
    )
    await session.commit()
    return {
        "id": version_id,
        "membership_plan_id": plan_id,
        "version_number": number,
        "status": "draft",
    }


async def transition_plan_version(
    session: AsyncSession, version_id: UUID, actor_id: UUID, action: str
) -> dict[str, Any]:
    version = _mapping(
        await session.execute(
            text(
                "SELECT v.*,p.plan_type,p.default_locale FROM membership_plan_versions v "
                "JOIN membership_plans p ON p.id=v.membership_plan_id WHERE v.id=:id FOR UPDATE"
            ),
            {"id": version_id},
        )
    )
    if version is None:
        raise VavError(
            "MEMBERSHIP_PLAN_VERSION_NOT_FOUND",
            "Plan version was not found.",
            status_code=404,
        )
    target_by_action = {
        "submit-review": "review",
        "approve": "approved",
        "activate": "active",
        "retire": "retired",
    }
    expected_by_action = {
        "submit-review": "draft",
        "approve": "review",
        "activate": "approved",
        "retire": "active",
    }
    if action not in target_by_action or version["status"] != expected_by_action[action]:
        raise VavError(
            "MEMBERSHIP_PLAN_VERSION_TRANSITION_INVALID",
            "Plan version transition is invalid.",
            status_code=409,
        )
    if action == "approve" and version["created_by"] == actor_id:
        raise VavError(
            "MEMBERSHIP_SELF_APPROVAL_FORBIDDEN",
            "Plan authors cannot approve their own version.",
            status_code=403,
        )
    if action == "activate":
        locale_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM membership_plan_localizations WHERE membership_plan_version_id=:id AND locale=:locale"
                ),
                {"id": version_id, "locale": version["default_locale"]},
            )
        ).first()
        if not locale_exists:
            raise VavError(
                "MEMBERSHIP_DEFAULT_LOCALE_MISSING",
                "The default locale is required.",
                status_code=422,
            )
        if version["plan_type"] == "paid":
            mapping = (
                await session.execute(
                    text(
                        "SELECT 1 FROM membership_sku_mappings WHERE membership_plan_version_id=:id AND valid_from <= now() AND (valid_until IS NULL OR valid_until > now())"
                    ),
                    {"id": version_id},
                )
            ).first()
            if not mapping:
                raise VavError(
                    "MEMBERSHIP_SKU_MAPPING_REQUIRED",
                    "Paid plans require an active SKU mapping.",
                    status_code=422,
                )
        await session.execute(
            text(
                "UPDATE membership_plan_versions SET status='retired' WHERE membership_plan_id=:plan AND status='active' AND id<>:id"
            ),
            {"plan": version["membership_plan_id"], "id": version_id},
        )
    target = target_by_action[action]
    row = _mapping(
        await session.execute(
            text(
                "UPDATE membership_plan_versions SET status=:target,approved_by=CASE WHEN :action='approve' THEN :actor ELSE approved_by END,"
                "approved_at=CASE WHEN :action='approve' THEN now() ELSE approved_at END,activated_at=CASE WHEN :action='activate' THEN now() ELSE activated_at END "
                "WHERE id=:id RETURNING *"
            ),
            {"target": target, "action": action, "actor": actor_id, "id": version_id},
        )
    )
    if action == "activate":
        await session.execute(
            text(
                "UPDATE membership_plans SET current_version_id=:version,status='active',updated_by=:actor,updated_at=now() WHERE id=:plan"
            ),
            {"version": version_id, "actor": actor_id, "plan": version["membership_plan_id"]},
        )
    await _audit(
        session,
        f"membership.plan.{action.replace('-', '_')}",
        actor_id=actor_id,
        metadata={"version_id": str(version_id)},
    )
    await session.commit()
    assert row is not None
    return row


async def create_sku_mapping(
    session: AsyncSession, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    row = _mapping(
        await session.execute(
            text(
                "INSERT INTO membership_sku_mappings (catalog_sku_id,membership_plan_id,membership_plan_version_id,billing_period,trial_policy,grace_period_policy,valid_from,valid_until) "
                "VALUES (:catalog_sku_id,:membership_plan_id,:membership_plan_version_id,:billing_period,CAST(:trial AS jsonb),CAST(:grace AS jsonb),:valid_from,:valid_until) RETURNING *"
            ),
            {
                **payload,
                "trial": _json(payload.get("trial_policy")),
                "grace": _json(payload.get("grace_period_policy")),
            },
        )
    )
    assert row is not None
    await _audit(
        session,
        "membership.sku_mapping.changed",
        actor_id=actor_id,
        metadata={"mapping_id": str(row["id"])},
    )
    await session.commit()
    return row


async def admin_dashboard(session: AsyncSession) -> dict[str, Any]:
    status_rows = (
        await session.execute(
            text("SELECT status,count(*) AS count FROM membership_accounts GROUP BY status")
        )
    ).mappings()
    source_rows = (
        await session.execute(
            text(
                "SELECT source_type,count(*) AS count FROM membership_accounts GROUP BY source_type"
            )
        )
    ).mappings()
    issues = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM membership_reconciliation_issues WHERE status IN ('open','investigating')"
                )
            )
        ).scalar_one()
    )
    return {
        "accounts_by_status": {row["status"]: row["count"] for row in status_rows},
        "accounts_by_source": {row["source_type"]: row["count"] for row in source_rows},
        "open_reconciliation_issues": issues,
    }


async def list_benefits(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT * FROM membership_benefit_definitions ORDER BY benefit_code,created_at DESC"
            )
        )
    ).mappings()
    return [dict(row) for row in rows]


async def create_benefit(
    session: AsyncSession, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    code = payload["benefit_code"]
    if code not in REGISTERED_BENEFIT_CODES:
        raise VavError(
            "MEMBERSHIP_BENEFIT_UNGOVERNED",
            "Benefit code is not in the governed platform registry.",
            status_code=422,
        )
    row = _mapping(
        await session.execute(
            text(
                "INSERT INTO membership_benefit_definitions "
                "(benefit_code,semantic_version,benefit_type,value_schema,owning_module,sensitivity,status) "
                "VALUES (:benefit_code,:semantic_version,:benefit_type,CAST(:schema AS jsonb),:owning_module,:sensitivity,'active') RETURNING *"
            ),
            {**payload, "schema": _json(payload["value_schema"])},
        )
    )
    assert row is not None
    await _audit(
        session,
        "membership.benefit.created",
        actor_id=actor_id,
        metadata={"benefit_id": str(row["id"]), "benefit_code": code},
    )
    await session.commit()
    return row


async def list_reconciliation_issues(
    session: AsyncSession, status: str | None = None
) -> list[dict[str, Any]]:
    status_filter = ""
    parameters: dict[str, Any] = {}
    if status is not None:
        status_filter = " WHERE status=:status"
        parameters["status"] = status
    rows = (
        await session.execute(
            text(
                "SELECT * FROM membership_reconciliation_issues "
                f"{status_filter} ORDER BY detected_at DESC LIMIT 500"
            ),
            parameters,
        )
    ).mappings()
    return [dict(row) for row in rows]


async def resolve_reconciliation_issue(
    session: AsyncSession,
    issue_id: UUID,
    actor_id: UUID,
    summary: str,
) -> dict[str, Any]:
    row = _mapping(
        await session.execute(
            text(
                "UPDATE membership_reconciliation_issues SET status='resolved',resolved_at=now(),"
                "resolved_by=:actor,resolution_summary=:summary WHERE id=:id "
                "AND status IN ('open','investigating') RETURNING *"
            ),
            {"actor": actor_id, "summary": summary, "id": issue_id},
        )
    )
    if row is None:
        raise VavError(
            "MEMBERSHIP_RECONCILIATION_NOT_FOUND",
            "Open reconciliation issue was not found.",
            status_code=404,
        )
    await _audit(
        session,
        "membership.reconciliation.resolved",
        actor_id=actor_id,
        account_id=row["membership_account_id"],
        metadata={"issue_id": str(issue_id)},
    )
    await session.commit()
    return row


ADMIN_LIST_QUERIES = {
    "accounts": "SELECT id,user_id,membership_plan_id,status,source_type,starts_at,expires_at,cancel_at_period_end,created_at,updated_at FROM membership_accounts ORDER BY created_at DESC LIMIT 500",
    "cycles": "SELECT * FROM membership_cycles ORDER BY created_at DESC LIMIT 500",
    "changes": "SELECT * FROM membership_change_requests ORDER BY created_at DESC LIMIT 500",
    "quotas": "SELECT id,membership_account_id,membership_cycle_id,benefit_code,period_type,period_starts_at,period_ends_at,allocated_quantity,consumed_quantity,reserved_quantity,rollover_quantity,status,version FROM membership_quota_buckets ORDER BY created_at DESC LIMIT 500",
    "usage": "SELECT id,quota_bucket_id,user_id,operation,quantity,source_module,source_reference_id,occurred_at FROM membership_quota_ledger ORDER BY occurred_at DESC LIMIT 500",
    "adjustments": "SELECT id,quota_bucket_id,adjustment_type,quantity,reason_code,created_by,approved_by,status,applied_at,created_at FROM membership_quota_adjustments ORDER BY created_at DESC LIMIT 500",
    "manual-grants": "SELECT id,user_id,membership_plan_version_id,grant_type,reason_code,starts_at,expires_at,status,granted_by,approved_by,membership_account_id,created_at,revoked_at FROM membership_manual_grants ORDER BY created_at DESC LIMIT 500",
    "trials": "SELECT * FROM membership_trial_policies ORDER BY created_at DESC LIMIT 500",
    "audit": "SELECT id,actor_user_id,membership_account_id,event_type,reason_code,safe_metadata,request_id,created_at FROM membership_audit_events ORDER BY created_at DESC LIMIT 500",
}


async def admin_list(session: AsyncSession, resource: str) -> list[dict[str, Any]]:
    query = ADMIN_LIST_QUERIES.get(resource)
    if query is None:
        raise VavError(
            "MEMBERSHIP_ADMIN_RESOURCE_INVALID",
            "Membership administration resource is invalid.",
            status_code=404,
        )
    rows = (await session.execute(text(query))).mappings()
    return [dict(row) for row in rows]


async def create_trial_policy(
    session: AsyncSession, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    if payload["auto_converts"] and not payload["requires_payment_method"]:
        raise VavError(
            "MEMBERSHIP_TRIAL_CONVERSION_INVALID",
            "Auto-converting trials require an explicit payment method policy.",
            status_code=422,
        )
    row = _mapping(
        await session.execute(
            text(
                "INSERT INTO membership_trial_policies "
                "(policy_code,semantic_version,membership_plan_version_id,duration_days,eligibility_policy,requires_payment_method,auto_converts,status) "
                "VALUES (:policy_code,:semantic_version,:membership_plan_version_id,:duration_days,CAST(:eligibility AS jsonb),:requires_payment_method,:auto_converts,'active') RETURNING *"
            ),
            {**payload, "eligibility": _json(payload["eligibility_policy"])},
        )
    )
    assert row is not None
    await _audit(
        session,
        "membership.trial_policy.created",
        actor_id=actor_id,
        metadata={"policy_id": str(row["id"]), "policy_code": row["policy_code"]},
    )
    await session.commit()
    return row
