# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.experience import service
from vav.modules.experience.schemas import (
    FeedbackCreate,
    HandoffCreate,
    JourneyStart,
    SupportRequestCreate,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user

public_router = APIRouter(prefix="/public/experience")
router = APIRouter(prefix="/experience")


def _ok(data: Any, request: Request) -> dict[str, Any]:
    return success(data, request_id_from_request(request))


@public_router.get("/navigation")
async def public_navigation(
    request: Request,
    locale: str = Query(default="zh-CN", pattern=r"^(zh-CN|zh-TW|en)$"),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.navigation(
            session,
            application_code="user-web",
            authenticated=False,
            permissions=set(),
            locale=locale,
        ),
        request,
    )


@public_router.get("/search")
async def public_search(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.search(session, query=q, user_id=None, permissions=set()), request)


@public_router.get("/help")
async def public_help(
    request: Request,
    route_code: str | None = Query(default=None, max_length=128),
    locale: str = Query(default="zh-CN", pattern=r"^(zh-CN|zh-TW|en)$"),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.help_articles(session, route_code=route_code, locale=locale), request)


@router.get("/navigation")
async def user_navigation(
    request: Request,
    locale: str = Query(default="zh-CN", pattern=r"^(zh-CN|zh-TW|en)$"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.navigation(
            session,
            application_code="user-web",
            authenticated=True,
            permissions=set(principal.permissions),
            locale=locale,
        ),
        request,
    )


@router.get("/routes/{route_code}/eligibility")
async def eligibility(
    route_code: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.route_eligibility(
            session, route_code, authenticated=True, permissions=set(principal.permissions)
        ),
        request,
    )


@router.get("/home")
async def home(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.user_home(session, principal.user.id), request)


@router.get("/tasks")
async def tasks(
    request: Request,
    include_history: bool = False,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_tasks(session, principal.user.id, include_history), request)


@router.get("/journeys")
async def journeys(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.list_journeys(session, principal.user.id), request)


@router.post("/journeys")
async def start_journey(
    payload: JourneyStart,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.start_journey(session, principal.user.id, payload), request)


@router.post("/handoffs")
async def create_handoff(
    payload: HandoffCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_handoff(session, principal.user.id, payload), request)


@router.post("/handoffs/{handoff_id}/accept")
async def accept_handoff(
    handoff_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.accept_handoff(
            session, principal.user.id, handoff_id, set(principal.permissions)
        ),
        request,
    )


@router.get("/search")
async def user_search(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.search(
            session, query=q, user_id=principal.user.id, permissions=set(principal.permissions)
        ),
        request,
    )


@router.get("/help")
async def user_help(
    request: Request,
    route_code: str | None = Query(default=None, max_length=128),
    locale: str = Query(default="zh-CN", pattern=r"^(zh-CN|zh-TW|en)$"),
    _principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.help_articles(session, route_code=route_code, locale=locale), request)


@router.post("/support")
async def support_request(
    payload: SupportRequestCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_support_request(session, principal.user.id, payload), request)


@router.post("/feedback")
async def feedback(
    payload: FeedbackCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(await service.create_feedback(session, principal.user.id, payload), request)


@router.post("/deep-links/{token}/resolve")
async def resolve_deep_link(
    token: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return _ok(
        await service.resolve_deep_link(
            session, principal.user.id, token, set(principal.permissions)
        ),
        request,
    )
