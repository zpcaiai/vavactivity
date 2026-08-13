"""Member-facing attendee-preview and follow API (ATT-001 / SOC-001).

The attendee preview returns the minimum-field projection only: no gender, no
age, no MBTI, no registration id, no payment state. A member who has not
explicitly consented never appears, and consent is re-read from the database on
every request rather than cached in a token.
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
from vav.modules.attendee_social.schemas import (
    FollowRequest,
    NotificationPreferenceRequest,
    PreviewConsentRequest,
    PreviewIntroRequest,
    WantToMeetRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user

router = APIRouter(prefix="/account")


# --- ATT-001 attendee preview -----------------------------------------------


@router.get("/activities/{activity_id}/attendee-preview")
async def attendee_preview(
    activity_id: UUID,
    request: Request,
    limit: int = Query(default=12, ge=1, le=50),
    exclude_absent: bool = Query(default=False),
    _principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_attendee_preview(
            session, activity_id=activity_id, limit=limit, exclude_absent=exclude_absent
        ),
        request_id_from_request(request),
    )


@router.get("/registrations/{registration_id}/preview-consent")
async def preview_consent(
    registration_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_my_consent(
            session, registration_id=registration_id, user_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.put("/registrations/{registration_id}/preview-consent")
async def set_preview_consent(
    registration_id: UUID,
    payload: PreviewConsentRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.set_preview_consent(
            session,
            registration_id=registration_id,
            user_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.put("/registrations/{registration_id}/preview-intro")
async def set_preview_intro(
    registration_id: UUID,
    payload: PreviewIntroRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.set_preview_intro(
            session,
            registration_id=registration_id,
            user_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


# --- SOC-001 follow graph ---------------------------------------------------


@router.post("/follows")
async def follow_member(
    payload: FollowRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.follow_member(
            session, follower_id=principal.user.id, followee_id=payload.user_id
        ),
        request_id_from_request(request),
    )


@router.delete("/follows/{user_id}")
async def unfollow_member(
    user_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.unfollow_member(session, follower_id=principal.user.id, followee_id=user_id),
        request_id_from_request(request),
    )


@router.get("/follows/following")
async def following(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_following(session, user_id=principal.user.id, limit=limit)},
        request_id_from_request(request),
    )


@router.get("/follows/followers")
async def followers(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_followers(session, user_id=principal.user.id, limit=limit)},
        request_id_from_request(request),
    )


@router.post("/want-to-meet")
async def want_to_meet(
    payload: WantToMeetRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Event-scoped intent. Distinct from a follow and from a like (SOC-001)."""

    return success(
        await service.record_want_to_meet(
            session, user_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/social/notification-preferences")
async def notification_preferences(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_notification_preferences(session, principal.user.id),
        request_id_from_request(request),
    )


@router.put("/social/notification-preferences")
async def set_notification_preferences(
    payload: NotificationPreferenceRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.set_notification_preferences(
            session, user_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )
