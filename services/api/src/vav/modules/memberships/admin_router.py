"""Governed membership administration APIs."""

# ruff: noqa: B008

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_admin_principal
from vav.modules.identity.permissions import require_permission
from vav.modules.memberships import grants, quota, service
from vav.modules.memberships.schemas import (
    BenefitCreateRequest,
    ManualGrantRequest,
    PlanCreateRequest,
    PlanUpdateRequest,
    PlanVersionCreateRequest,
    QuotaAdjustmentRequest,
    ReconciliationResolveRequest,
    SkuMappingRequest,
    TrialPolicyRequest,
)
from vav.modules.privacy.crypto import encrypt_private

router = APIRouter(prefix="/admin/memberships")
version_router = APIRouter(prefix="/admin/membership-plan-versions")


class EmptyAction(BaseModel):
    pass


@router.get("/dashboard")
async def dashboard(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("memberships.analytics.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.admin_dashboard(session), request_id_from_request(request))


@router.get("/plans")
async def plans(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("memberships.plans.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.list_admin_plans(session), request_id_from_request(request))


@router.post("/plans")
async def create_plan(
    payload: PlanCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("memberships.plans.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_plan(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("memberships.plans.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    plans = await service.list_admin_plans(session)
    plan = next((item for item in plans if item["id"] == plan_id), None)
    if plan is None:
        raise VavError(
            "MEMBERSHIP_PLAN_NOT_FOUND",
            "Membership plan was not found.",
            status_code=404,
        )
    return success(plan, request_id_from_request(request))


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: UUID,
    payload: PlanUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("memberships.plans.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.update_plan(session, plan_id, principal.user.id, payload.model_dump()),
        request_id_from_request(request),
    )


@router.post("/plans/{plan_id}/versions")
async def create_version(
    plan_id: UUID,
    payload: PlanVersionCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("memberships.plans.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_plan_version(
            session,
            plan_id=plan_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


async def _transition(
    version_id: UUID,
    action: str,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    return success(
        await service.transition_plan_version(session, version_id, principal.user.id, action),
        request_id_from_request(request),
    )


@router.post("/membership-plan-versions/{version_id}/submit-review")
async def submit_review(
    version_id: UUID,
    _payload: EmptyAction,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("memberships.plans.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _transition(version_id, "submit-review", request, principal, session)


@router.post("/membership-plan-versions/{version_id}/approve")
async def approve_version(
    version_id: UUID,
    _payload: EmptyAction,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("memberships.plans.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _transition(version_id, "approve", request, principal, session)


@router.post("/membership-plan-versions/{version_id}/activate")
async def activate_version(
    version_id: UUID,
    _payload: EmptyAction,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("memberships.plans.activate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _transition(version_id, "activate", request, principal, session)


@router.post("/membership-plan-versions/{version_id}/retire")
async def retire_version(
    version_id: UUID,
    _payload: EmptyAction,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("memberships.plans.retire")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _transition(version_id, "retire", request, principal, session)


version_router.add_api_route(
    "/{version_id}/submit-review",
    submit_review,
    methods=["POST"],
)
version_router.add_api_route("/{version_id}/approve", approve_version, methods=["POST"])
version_router.add_api_route("/{version_id}/activate", activate_version, methods=["POST"])
version_router.add_api_route("/{version_id}/retire", retire_version, methods=["POST"])


@router.get("/benefits")
async def benefits(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("memberships.benefits.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.list_benefits(session), request_id_from_request(request))


@router.post("/benefits")
async def create_benefit(
    payload: BenefitCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("memberships.benefits.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_benefit(session, principal.user.id, payload.model_dump()),
        request_id_from_request(request),
    )


@router.post("/sku-mappings")
async def create_sku_mapping(
    payload: SkuMappingRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("memberships.sku_mappings.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_sku_mapping(session, principal.user.id, payload.model_dump()),
        request_id_from_request(request),
    )


@router.post("/quota-buckets/{bucket_id}/adjustments")
async def quota_adjustment(
    bucket_id: UUID,
    payload: QuotaAdjustmentRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("memberships.quotas.adjust")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    encrypted = encrypt_private(payload.reason) if payload.reason else None
    return success(
        await quota.adjust_quota(
            session,
            actor_id=principal.user.id,
            bucket_id=bucket_id,
            quantity=payload.quantity,
            adjustment_type=payload.adjustment_type,
            reason_code=payload.reason_code,
            reason_encrypted=encrypted,
            idempotency_key=payload.idempotency_key,
        ),
        request_id_from_request(request),
    )


@router.get("/reconciliation")
async def reconciliation(
    request: Request,
    status: str | None = Query(default=None),
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("memberships.reconciliation.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_reconciliation_issues(session, status),
        request_id_from_request(request),
    )


@router.post("/reconciliation/{issue_id}/resolve")
async def resolve_reconciliation(
    issue_id: UUID,
    payload: ReconciliationResolveRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("memberships.reconciliation.resolve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.resolve_reconciliation_issue(
            session, issue_id, principal.user.id, payload.resolution_summary
        ),
        request_id_from_request(request),
    )


@router.post("/manual-grants")
async def create_manual_grant(
    payload: ManualGrantRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("memberships.manual_grants.create")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    encrypted = encrypt_private(payload.reason) if payload.reason else None
    return success(
        await grants.create_manual_grant(
            session,
            actor_id=principal.user.id,
            user_id=payload.user_id,
            plan_version_id=payload.membership_plan_version_id,
            grant_type=payload.grant_type,
            reason_code=payload.reason_code,
            reason_encrypted=encrypted,
            starts_at=payload.starts_at,
            expires_at=payload.expires_at,
        ),
        request_id_from_request(request),
    )


@router.post("/manual-grants/{grant_id}/approve")
async def approve_manual_grant(
    grant_id: UUID,
    _payload: EmptyAction,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("memberships.manual_grants.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await grants.approve_manual_grant(session, grant_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/manual-grants/{grant_id}/revoke")
async def revoke_manual_grant(
    grant_id: UUID,
    _payload: EmptyAction,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("memberships.manual_grants.revoke")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await grants.revoke_manual_grant(session, grant_id, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/trials")
async def create_trial_policy(
    payload: TrialPolicyRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("memberships.trials.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_trial_policy(session, principal.user.id, payload.model_dump()),
        request_id_from_request(request),
    )


ADMIN_RESOURCE_PERMISSIONS = {
    "accounts": "memberships.accounts.read",
    "cycles": "memberships.accounts.read",
    "changes": "memberships.changes.read",
    "quotas": "memberships.quotas.read",
    "usage": "memberships.quotas.read",
    "adjustments": "memberships.quotas.read",
    "manual-grants": "memberships.manual_grants.read",
    "trials": "memberships.trials.read",
    "audit": "memberships.audit.read",
}


@router.get("/{resource}")
async def admin_resource(
    resource: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    permission = ADMIN_RESOURCE_PERMISSIONS.get(resource)
    if permission is None:
        raise VavError(
            "MEMBERSHIP_ADMIN_RESOURCE_INVALID",
            "Membership administration resource is invalid.",
            status_code=404,
        )
    principal.require(permission)
    return success(await service.admin_list(session, resource), request_id_from_request(request))
