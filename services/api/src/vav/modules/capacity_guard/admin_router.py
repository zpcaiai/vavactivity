"""Administrative capacity and waitlist API (ACT-003).

Every route is permission-gated server-side. Hiding a control in the admin UI is
never the check (AUTH-002); the checks below are.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.capacity_guard import service
from vav.modules.capacity_guard.schemas import (
    CapacityAdjustRequest,
    OfferSweepRequest,
    PromotionRoundRequest,
    SalesStateRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin")


@router.get("/ticket-types/{ticket_type_id}/capacity")
async def read_capacity(
    ticket_type_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("activities.capacity.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_capacity(session, ticket_type_id), request_id_from_request(request)
    )


@router.put("/ticket-types/{ticket_type_id}/capacity")
async def adjust_capacity(
    ticket_type_id: UUID,
    payload: CapacityAdjustRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.capacity.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Change the cap. Refused if it would put the ticket type below what is sold."""

    return success(
        await service.adjust_capacity(
            session,
            ticket_type_id=ticket_type_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.put("/ticket-types/{ticket_type_id}/sales-state")
async def set_sales_state(
    ticket_type_id: UUID,
    payload: SalesStateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.capacity.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.set_sales_state(
            session,
            ticket_type_id=ticket_type_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/ticket-types/{ticket_type_id}/waitlist")
async def list_waitlist(
    ticket_type_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("activities.waitlist.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """The queue in promotion order, so "who is next" has one answer."""

    return success(
        {"items": await service.list_waitlist(session, ticket_type_id=ticket_type_id)},
        request_id_from_request(request),
    )


@router.post("/waitlist/promotion-rounds")
async def run_promotion_round(
    payload: PromotionRoundRequest,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("activities.waitlist.promote")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Run a promotion round by hand. ``dry_run`` shows the plan without writing."""

    return success(
        await service.run_promotion_round(session, payload=payload.model_dump()),
        request_id_from_request(request),
    )


@router.post("/waitlist/offer-sweeps")
async def sweep_offers(
    payload: OfferSweepRequest,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("activities.waitlist.promote")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Expire timed-out offers and release the seats they were holding."""

    return success(
        await service.sweep_expired_offers(session, payload=payload.model_dump()),
        request_id_from_request(request),
    )
