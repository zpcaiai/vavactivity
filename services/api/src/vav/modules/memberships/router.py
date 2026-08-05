"""Public, member and authenticated internal membership APIs."""

# ruff: noqa: B008

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.memberships import projection, quota, service
from vav.modules.memberships.schemas import (
    AccessDecisionRequest,
    ChangeCreateRequest,
    ChangeDecisionRequest,
    ChangePreviewRequest,
    ProjectionEventRequest,
    QuotaMutationRequest,
    QuotaReserveRequest,
)

router = APIRouter()


def _require_same_user(principal: AuthenticatedPrincipal, user_id: UUID) -> None:
    if principal.user.id != user_id:
        raise VavError(
            "MEMBERSHIP_SUBJECT_MISMATCH",
            "A user can only act on their own membership.",
            status_code=403,
        )


@router.get("/public/membership-plans")
async def public_plans(
    request: Request,
    locale: str = Query(default="en", min_length=2, max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_public_plans(session, locale), request_id_from_request(request)
    )


@router.get("/public/membership-plans/{plan_code}")
async def public_plan(
    plan_code: str,
    request: Request,
    locale: str = Query(default="en", min_length=2, max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_public_plan(session, plan_code, locale),
        request_id_from_request(request),
    )


@router.get("/account/membership")
async def current_membership(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.membership_summary(session, principal.user.id),
        request_id_from_request(request),
    )


@router.get("/account/membership/benefits")
async def membership_benefits(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    summary = await service.membership_summary(session, principal.user.id)
    return success(summary["benefits"], request_id_from_request(request))


@router.get("/account/membership/usage")
async def membership_usage(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    summary = await service.membership_summary(session, principal.user.id)
    return success(summary["quotas"], request_id_from_request(request))


@router.get("/account/membership/history")
async def membership_history(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.membership_history(session, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/account/membership/change-preview")
async def change_preview(
    payload: ChangePreviewRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.change_preview(
            session, principal.user.id, payload.to_plan_code, payload.change_type
        ),
        request_id_from_request(request),
    )


@router.post("/account/membership/change-requests")
async def create_change_request(
    payload: ChangeCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_change_request(
            session,
            user_id=principal.user.id,
            to_plan_code=payload.to_plan_code,
            change_type=payload.change_type,
            idempotency_key=payload.idempotency_key,
        ),
        request_id_from_request(request),
    )


@router.get("/account/membership/change-requests/{change_id}")
async def get_change_request(
    change_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_change_request(session, principal.user.id, change_id),
        request_id_from_request(request),
    )


@router.post("/account/membership/change-requests/{change_id}/confirm")
async def confirm_change(
    change_id: UUID,
    payload: ChangeDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_change(
            session,
            user_id=principal.user.id,
            change_id=change_id,
            expected_version=payload.expected_version,
            confirm=True,
        ),
        request_id_from_request(request),
    )


@router.post("/account/membership/change-requests/{change_id}/cancel")
async def cancel_change(
    change_id: UUID,
    payload: ChangeDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_change(
            session,
            user_id=principal.user.id,
            change_id=change_id,
            expected_version=payload.expected_version,
            confirm=False,
        ),
        request_id_from_request(request),
    )


@router.post("/internal/membership/access-decisions")
async def access_decision(
    payload: AccessDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _require_same_user(principal, payload.user_id)
    return success(
        await service.decide_access(
            session,
            user_id=payload.user_id,
            capability_code=payload.capability_code,
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            requested_quantity=payload.requested_quantity,
        ),
        request_id_from_request(request),
    )


@router.post("/internal/membership/quota-reservations")
async def quota_reservation(
    payload: QuotaReserveRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _require_same_user(principal, payload.user_id)
    return success(
        await quota.reserve(session, **payload.model_dump()), request_id_from_request(request)
    )


@router.post("/internal/membership/quota-consumptions")
async def quota_consumption(
    payload: QuotaMutationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await quota.finalize_reservation(
            session,
            user_id=principal.user.id,
            reservation_id=payload.reservation_id,
            idempotency_key=payload.idempotency_key,
            consume=True,
        ),
        request_id_from_request(request),
    )


@router.post("/internal/membership/quota-releases")
async def quota_release(
    payload: QuotaMutationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await quota.finalize_reservation(
            session,
            user_id=principal.user.id,
            reservation_id=payload.reservation_id,
            idempotency_key=payload.idempotency_key,
            consume=False,
        ),
        request_id_from_request(request),
    )


@router.post("/internal/membership/events")
async def membership_event(
    payload: ProjectionEventRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    principal.require("memberships.accounts.rebuild")
    return success(
        await projection.project_event(session, **payload.model_dump()),
        request_id_from_request(request),
    )
