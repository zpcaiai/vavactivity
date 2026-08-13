"""Member-facing capacity and waitlist API (ACT-003).

Nothing here exposes another member's place, another member's offer, or the
identity of anybody else in the queue. A member sees their own position and the
seats-remaining number the ticket type publishes.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.capacity_guard import service
from vav.modules.capacity_guard.schemas import (
    OfferResponseRequest,
    SeatReservationRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user

router = APIRouter(prefix="/account")


async def _own_registration(
    session: AsyncSession, *, registration_id: UUID, user_id: UUID
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,ticket_type_id,user_id,status FROM activity_registrations "
                    "WHERE id=:id AND user_id=:user_id"
                ),
                {"id": str(registration_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("CHECKIN_REGISTRATION_NOT_FOUND", "Registration not found.", status_code=404)
    return dict(row)


@router.post("/registrations/{registration_id}/seat")
async def reserve_seat(
    registration_id: UUID,
    payload: SeatReservationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Take a seat or a queue place for the caller's own registration."""

    await _own_registration(session, registration_id=registration_id, user_id=principal.user.id)
    return success(
        await service.reserve_seat(
            session,
            ticket_type_id=payload.ticket_type_id,
            registration_id=registration_id,
            user_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/ticket-types/{ticket_type_id}/capacity")
async def read_capacity(
    ticket_type_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_capacity(session, ticket_type_id), request_id_from_request(request)
    )


@router.get("/registrations/{registration_id}/waitlist-place")
async def my_waitlist_place(
    registration_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Own queue position only; the queue itself is never listed to members."""

    registration = await _own_registration(
        session, registration_id=registration_id, user_id=principal.user.id
    )
    return success(
        await service.my_waitlist_place(
            session,
            ticket_type_id=UUID(str(registration["ticket_type_id"])),
            registration_id=registration_id,
        ),
        request_id_from_request(request),
    )


@router.post("/waitlist-offers/{offer_id}/response")
async def respond_to_offer(
    offer_id: UUID,
    payload: OfferResponseRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Accept or decline a promotion offer.

    An offer past its deadline is refused here even if the sweeper has not run
    yet: expiry is decided from the clock, not from a job having caught up.
    """

    return success(
        await service.respond_to_offer(
            session,
            offer_id=offer_id,
            user_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )
