"""Administrative attendee-preview and follow-graph API (ATT-001 / SOC-001).

Every route is permission-gated server-side. Hiding a button in the admin UI is
never the control (AUTH-002); the checks below are.

New permission codes required by this module - add these to
``vav/modules/identity/permissions.py`` (they are deliberately NOT inserted by
the migration, because ``permissions`` has NOT NULL ``resource`` / ``action`` /
``risk_level`` columns that only the permission registry knows how to fill):

* ``attendee_preview.read``            - see the preview an operator would ship
* ``attendee_preview.consent.read``    - read consent state and its history
* ``attendee_preview.consent.withdraw``- administratively withdraw consent
* ``social.follows.read``              - inspect a member's follow graph
* ``social.notifications.dispatch``    - trigger the followed-user fan-out

There is deliberately **no** ``attendee_preview.consent.grant`` permission: an
operator must never be able to opt a member in (DEC-002).
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.attendee_social import service
from vav.modules.attendee_social.schemas import AdminConsentOverrideRequest
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin/attendee-social")


# --- ATT-001 preview and consent --------------------------------------------


@router.get("/activities/{activity_id}/preview")
async def attendee_preview(
    activity_id: UUID,
    request: Request,
    limit: int = Query(default=12, ge=1, le=50),
    exclude_absent: bool = Query(default=False),
    _principal: AuthenticatedPrincipal = Depends(require_permission("attendee_preview.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """The exact payload members receive - operators get no extra fields."""

    return success(
        await service.get_attendee_preview(
            session, activity_id=activity_id, limit=limit, exclude_absent=exclude_absent
        ),
        request_id_from_request(request),
    )


@router.post("/consents/withdraw")
async def withdraw_consent(
    payload: AdminConsentOverrideRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("attendee_preview.consent.withdraw")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.admin_withdraw_consent(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


# --- SOC-001 follow graph ---------------------------------------------------


@router.get("/members/{user_id}/follows")
async def member_follows(
    user_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    _principal: AuthenticatedPrincipal = Depends(require_permission("social.follows.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {
            "following": await service.list_following(session, user_id=user_id, limit=limit),
            "followers": await service.list_followers(session, user_id=user_id, limit=limit),
        },
        request_id_from_request(request),
    )


@router.post("/activities/{activity_id}/members/{user_id}/notify-followers")
async def notify_followers(
    activity_id: UUID,
    user_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("social.notifications.dispatch")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Re-run the followed-user fan-out. Safe to repeat: delivery is idempotent."""

    return success(
        await service.fan_out_followed_user_registered(
            session, actor_id=user_id, activity_id=activity_id
        ),
        request_id_from_request(request),
    )
