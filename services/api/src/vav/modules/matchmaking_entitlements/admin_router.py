"""Administrative matchmaking entitlement controls (B12)."""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.matchmaking_entitlements import service
from vav.modules.matchmaking_entitlements.schemas import (
    AdminRelationshipStatusRequest,
    ArrivalJobRequest,
    DeliveryHistoryResetRequest,
    DisclaimerRequest,
    EntitlementAdjustRequest,
)

router = APIRouter(prefix="/admin/matchmaking")


@router.get("/members/{user_id}/relationship-status")
async def member_status(
    user_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.relationship_status.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_relationship_status(session, user_id),
        request_id_from_request(request),
    )


@router.put("/members/{user_id}/relationship-status")
async def set_member_status(
    user_id: UUID,
    payload: AdminRelationshipStatusRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.relationship_status.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.set_relationship_status(
            session,
            user_id=user_id,
            target=payload.status,
            source="admin",
            actor_id=principal.user.id,
            actor_kind="admin",
            reason=payload.reason,
        ),
        request_id_from_request(request),
    )


@router.post("/members/{user_id}/entitlement-adjustments")
async def adjust_entitlement(
    user_id: UUID,
    payload: EntitlementAdjustRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.entitlements.adjust")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.admin_adjust_entitlement(
            session, user_id=user_id, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.post("/members/{user_id}/delivery-history-resets")
async def reset_history(
    user_id: UUID,
    payload: DeliveryHistoryResetRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.entitlements.adjust")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.reset_delivery_history(
            session, user_id=user_id, actor_id=principal.user.id, reason=payload.reason
        ),
        request_id_from_request(request),
    )


@router.post("/wait-pool/notifications")
async def run_arrival_job(
    payload: ArrivalJobRequest,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.entitlements.adjust")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.notify_candidate_arrivals(session, opportunity_key=payload.opportunity_key),
        request_id_from_request(request),
    )


@router.put("/disclaimers")
async def upsert_disclaimer(
    payload: DisclaimerRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.disclaimers.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upsert_disclaimer(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.post("/disclaimers/{disclaimer_id}/publish")
async def publish_disclaimer(
    disclaimer_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.disclaimers.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.publish_disclaimer(
            session, disclaimer_id=disclaimer_id, actor_id=principal.user.id
        ),
        request_id_from_request(request),
    )
