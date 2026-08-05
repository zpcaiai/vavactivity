"""Four-eyes manual membership grant workflow."""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.modules.memberships.projection import _allocate_plan
from vav.modules.memberships.service import _audit, _mapping, _publish


async def create_manual_grant(
    session: AsyncSession,
    *,
    actor_id: UUID,
    user_id: UUID,
    plan_version_id: UUID,
    grant_type: str,
    reason_code: str,
    reason_encrypted: str | None,
    starts_at: Any,
    expires_at: Any,
) -> dict[str, Any]:
    grant = _mapping(
        await session.execute(
            text(
                "INSERT INTO membership_manual_grants "
                "(user_id,membership_plan_version_id,grant_type,reason_code,reason_encrypted,starts_at,expires_at,status,granted_by) "
                "VALUES (:user,:version,:type,:reason_code,:reason,:starts,:expires,'pending_approval',:actor) RETURNING *"
            ),
            {
                "user": user_id,
                "version": plan_version_id,
                "type": grant_type,
                "reason_code": reason_code,
                "reason": reason_encrypted,
                "starts": starts_at,
                "expires": expires_at,
                "actor": actor_id,
            },
        )
    )
    assert grant is not None
    await _audit(
        session,
        "membership.manual_grant.created",
        actor_id=actor_id,
        reason_code=reason_code,
        metadata={
            "grant_id": str(grant["id"]),
            "user_id": str(user_id),
            "expires_at": str(expires_at),
        },
    )
    await session.commit()
    return grant


async def approve_manual_grant(
    session: AsyncSession, grant_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    grant = _mapping(
        await session.execute(
            text("SELECT * FROM membership_manual_grants WHERE id=:id FOR UPDATE"), {"id": grant_id}
        )
    )
    if grant is None:
        raise VavError("MEMBERSHIP_GRANT_NOT_FOUND", "Manual grant was not found.", status_code=404)
    if grant["status"] != "pending_approval":
        raise VavError(
            "MEMBERSHIP_GRANT_NOT_ACTIONABLE",
            "Manual grant is not awaiting approval.",
            status_code=409,
        )
    if grant["granted_by"] == actor_id:
        raise VavError(
            "MEMBERSHIP_SELF_APPROVAL_FORBIDDEN",
            "Grant creators cannot approve their own grant.",
            status_code=403,
        )
    version = _mapping(
        await session.execute(
            text(
                "SELECT v.*,p.id AS plan_id FROM membership_plan_versions v JOIN membership_plans p ON p.id=v.membership_plan_id WHERE v.id=:id AND v.status='active'"
            ),
            {"id": grant["membership_plan_version_id"]},
        )
    )
    if version is None:
        raise VavError(
            "MEMBERSHIP_PLAN_VERSION_INACTIVE", "Grant plan version is not active.", status_code=409
        )
    conflicting = await session.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM membership_accounts WHERE user_id=:user "
            "AND source_type<>'free_default' AND status IN "
            "('active','trialing','grace_period','past_due','cancel_scheduled'))"
        ),
        {"user": grant["user_id"]},
    )
    if conflicting:
        raise VavError(
            "MEMBERSHIP_ACTIVE_ACCOUNT_CONFLICT",
            "The member already has an effective paid, trial or grant account.",
            status_code=409,
        )
    account_id = uuid4()
    cycle_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO membership_accounts "
            "(id,user_id,membership_plan_id,membership_plan_version_id,status,source_type,starts_at,expires_at,current_cycle_id) "
            "VALUES (:id,:user,:plan,:version,'active','admin_grant',:starts,:expires,NULL)"
        ),
        {
            "id": account_id,
            "user": grant["user_id"],
            "plan": version["plan_id"],
            "version": version["id"],
            "starts": grant["starts_at"],
            "expires": grant["expires_at"],
        },
    )
    await session.execute(
        text(
            "INSERT INTO membership_cycles (id,membership_account_id,cycle_number,status,starts_at,ends_at) "
            "VALUES (:id,:account,1,'active',:starts,:ends)"
        ),
        {
            "id": cycle_id,
            "account": account_id,
            "starts": grant["starts_at"],
            "ends": grant["expires_at"],
        },
    )
    await session.execute(
        text("UPDATE membership_accounts SET current_cycle_id=:cycle WHERE id=:account"),
        {"cycle": cycle_id, "account": account_id},
    )
    await _allocate_plan(
        session,
        account_id=account_id,
        cycle_id=cycle_id,
        plan_version_id=version["id"],
        starts_at=grant["starts_at"],
        ends_at=grant["expires_at"],
    )
    approved = _mapping(
        await session.execute(
            text(
                "UPDATE membership_manual_grants SET status='active',approved_by=:actor,membership_account_id=:account WHERE id=:id RETURNING *"
            ),
            {"actor": actor_id, "account": account_id, "id": grant_id},
        )
    )
    await _audit(
        session,
        "membership.manual_grant.approved",
        actor_id=actor_id,
        account_id=account_id,
        metadata={"grant_id": str(grant_id)},
    )
    await _publish(
        session,
        "membership.manual_grant.created",
        account_id,
        {
            "user_id": str(grant["user_id"]),
            "grant_id": str(grant_id),
            "expires_at": str(grant["expires_at"]),
        },
    )
    await session.commit()
    assert approved is not None
    return approved


async def revoke_manual_grant(
    session: AsyncSession, grant_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    grant = _mapping(
        await session.execute(
            text("SELECT * FROM membership_manual_grants WHERE id=:id FOR UPDATE"), {"id": grant_id}
        )
    )
    if grant is None or grant["status"] not in {"approved", "active"}:
        raise VavError(
            "MEMBERSHIP_GRANT_NOT_ACTIONABLE", "Active manual grant was not found.", status_code=404
        )
    if grant["membership_account_id"]:
        await session.execute(
            text(
                "UPDATE membership_accounts SET status='revoked',version=version+1,updated_at=now() WHERE id=:id"
            ),
            {"id": grant["membership_account_id"]},
        )
        await session.execute(
            text(
                "UPDATE membership_benefit_grants SET status='revoked' WHERE membership_account_id=:id AND status='active'"
            ),
            {"id": grant["membership_account_id"]},
        )
        await session.execute(
            text(
                "UPDATE membership_quota_buckets SET status='closed',updated_at=now() WHERE membership_account_id=:id AND status='active'"
            ),
            {"id": grant["membership_account_id"]},
        )
    revoked = _mapping(
        await session.execute(
            text(
                "UPDATE membership_manual_grants SET status='revoked',revoked_at=now() WHERE id=:id RETURNING *"
            ),
            {"id": grant_id},
        )
    )
    await _audit(
        session,
        "membership.manual_grant.revoked",
        actor_id=actor_id,
        account_id=grant["membership_account_id"],
        metadata={"grant_id": str(grant_id)},
    )
    if grant["membership_account_id"]:
        await _publish(
            session,
            "membership.manual_grant.revoked",
            grant["membership_account_id"],
            {"user_id": str(grant["user_id"]), "grant_id": str(grant_id)},
        )
    await session.commit()
    assert revoked is not None
    return revoked
