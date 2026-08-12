"""Member-facing couple binding and SCOPE API (B16).

Nothing here exposes a partner's raw SCOPE answers, an unfinished report, or
another member's invitation. Binding always requires two sides: the only route
that can produce an active relationship is the invitee's response to a pending
invitation.
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
from vav.modules.couples import service
from vav.modules.couples.schemas import (
    InvitationCreateRequest,
    InvitationRespondRequest,
    ScopeAnswersRequest,
    ScopeStartRequest,
    UnbindRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user

router = APIRouter(prefix="/account")


# --- COUPLE-001 invitations -------------------------------------------------


@router.post("/couple/invitations")
async def create_invitation(
    payload: InvitationCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_invitation(
            session, inviter_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/couple/invitations")
async def list_invitations(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_my_invitations(session, principal.user.id)},
        request_id_from_request(request),
    )


@router.post("/couple/invitations/{invitation_id}/response")
async def respond_to_invitation(
    invitation_id: UUID,
    payload: InvitationRespondRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.respond_to_invitation(
            session,
            invitation_id=invitation_id,
            user_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/couple/invitations/{invitation_id}/cancellation")
async def cancel_invitation(
    invitation_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.cancel_invitation(
            session, invitation_id=invitation_id, user_id=principal.user.id
        ),
        request_id_from_request(request),
    )


# --- COUPLE-001 relationship ------------------------------------------------


@router.get("/couple/relationship")
async def my_relationship(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_my_relationship(session, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/couple/relationship/unbind")
async def unbind(
    payload: UnbindRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.unbind_my_relationship(
            session, user_id=principal.user.id, reason=payload.reason
        ),
        request_id_from_request(request),
    )


# --- SCOPE-001 assessment ---------------------------------------------------


@router.get("/couple/scope/versions")
async def scope_versions(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.scope_enabled()
    versions = await service.list_scope_versions(session)
    return success(
        {"items": [item for item in versions if item["status"] == "published"]},
        request_id_from_request(request),
    )


@router.post("/couple/scope/assessments")
async def start_scope(
    payload: ScopeStartRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.start_scope_assessment(
            session, user_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/couple/scope/assessments/{assessment_id}")
async def scope_assessment(
    assessment_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_scope_assessment(
            session, assessment_id=assessment_id, user_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.get("/couple/scope/assessments/{assessment_id}/answers/{owner_id}")
async def scope_raw_answers(
    assessment_id: UUID,
    owner_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Raw answers, readable only by their author.

    ``owner_id`` is in the path on purpose: asking for a partner's answers is a
    request the server can refuse explicitly (403 ``SCOPE_ANSWERS_SEALED``)
    rather than a request that silently returns something else.
    """

    return success(
        await service.read_my_raw_answers(
            session,
            assessment_id=assessment_id,
            user_id=principal.user.id,
            owner_id=owner_id,
        ),
        request_id_from_request(request),
    )


@router.put("/couple/scope/assessments/{assessment_id}/answers")
async def save_scope_answers(
    assessment_id: UUID,
    payload: ScopeAnswersRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.save_scope_answers(
            session,
            assessment_id=assessment_id,
            user_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/couple/scope/assessments/{assessment_id}/report")
async def scope_report(
    assessment_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_scope_report(
            session, assessment_id=assessment_id, user_id=principal.user.id
        ),
        request_id_from_request(request),
    )
