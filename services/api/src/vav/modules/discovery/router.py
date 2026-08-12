"""Member-facing discovery API (GEO-001 / MAP-001 / SHARE-001).

Nothing here returns a map API key, a raw IP, or an event that is not published
and public. The city used for a query is resolved server-side on every call
rather than trusted from the client.
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
from vav.modules.discovery import service
from vav.modules.discovery.schemas import CityPreferenceRequest
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user

router = APIRouter(prefix="/account")


def _ip_city_hint(request: Request) -> str | None:
    """Read the coarse city an upstream edge resolved from the request IP.

    The application never sees or stores the address itself: the edge (CDN or
    gateway) supplies a city header, and only that coarse value is used
    (GEO-001).
    """

    return request.headers.get("x-geo-city-code")


# --- GEO-001 city preference and feed ---------------------------------------


@router.get("/city-preference")
async def city_preference(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_city_preference(session, principal.user.id),
        request_id_from_request(request),
    )


@router.put("/city-preference")
async def set_city_preference(
    payload: CityPreferenceRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.set_city_preference(
            session, user_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/discovery/feed")
async def discovery_feed(
    request: Request,
    city_code: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10000),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.discovery_feed(
            session,
            user_id=principal.user.id,
            ip_city_code=_ip_city_hint(request),
            override_city_code=city_code,
            limit=limit,
            offset=offset,
        ),
        request_id_from_request(request),
    )


# --- MAP-001 venue location -------------------------------------------------


@router.get("/activities/{activity_id}/venue-location")
async def venue_location(
    activity_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_venue_location(session, activity_id),
        request_id_from_request(request),
    )


# --- SHARE-001 share card, short link, QR -----------------------------------


@router.get("/activities/{activity_id}/share-card")
async def share_card(
    activity_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_share_card(session, activity_id=activity_id),
        request_id_from_request(request),
    )


@router.get("/share-links/{short_code}")
async def resolve_share_link(
    short_code: str,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.resolve_short_link(session, short_code=short_code),
        request_id_from_request(request),
    )
