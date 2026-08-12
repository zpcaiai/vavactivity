"""Member-facing post-event closure API.

Nothing here exposes another member's raw answers, another member's selections,
or an unpublished result letter. Eligibility is resolved from the frozen
snapshot on every call rather than trusted from the client.
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
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.post_event import service
from vav.modules.post_event.schemas import SelectionSubmitRequest, SurveyResponseRequest

router = APIRouter(prefix="/account")


# --- B09 mutual selection ---------------------------------------------------


@router.get("/activities/{activity_id}/candidates")
async def candidates(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_visible_candidates(
            session, activity_id=activity_id, user_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.get("/activities/{activity_id}/selection")
async def my_selection(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_my_selection(
            session, activity_id=activity_id, user_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.put("/activities/{activity_id}/selection")
async def submit_selection(
    activity_id: UUID,
    payload: SelectionSubmitRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.submit_selection(
            session,
            activity_id=activity_id,
            user_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


# --- B10 post-event survey --------------------------------------------------


@router.get("/survey-tasks")
async def survey_tasks(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_my_survey_tasks(session, principal.user.id)},
        request_id_from_request(request),
    )


@router.get("/surveys/{assignment_id}")
async def survey_detail(
    assignment_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_survey_for_member(
            session, assignment_id=assignment_id, user_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.put("/surveys/{assignment_id}/response")
async def save_survey_response(
    assignment_id: UUID,
    payload: SurveyResponseRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.save_survey_response(
            session,
            assignment_id=assignment_id,
            user_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


# --- B11 result letters -----------------------------------------------------


@router.get("/result-letters")
async def result_letters(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_my_letters(session, principal.user.id)},
        request_id_from_request(request),
    )


@router.get("/result-letters/{letter_id}")
async def result_letter(
    letter_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.read_my_letter(session, letter_id=letter_id, user_id=principal.user.id),
        request_id_from_request(request),
    )
