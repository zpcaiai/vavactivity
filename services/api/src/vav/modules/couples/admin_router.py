"""Administrative couple binding and SCOPE API (B16).

Every route is permission-gated server-side (AUTH-002). Note what is *absent*:
there is no administrative route that reads a member's raw SCOPE answers, and
no route that creates a binding. An operator can end a binding and can inspect
deterministic scores, and that is the whole of their reach into a couple's data.
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
from vav.modules.couples import service
from vav.modules.couples.schemas import (
    AdminUnbindRequest,
    ScopeAdviceRequest,
    ScopeQuestionRequest,
    ScopeVersionRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin")


# --- COUPLE-001 relationships -----------------------------------------------


@router.get("/couple/relationships")
async def list_relationships(
    request: Request,
    state: str | None = Query(default=None),
    _principal: AuthenticatedPrincipal = Depends(require_permission("couples.relationships.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.admin_list_relationships(session, state=state)},
        request_id_from_request(request),
    )


@router.get("/couple/relationships/{relationship_id}/events")
async def relationship_events(
    relationship_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("couples.relationships.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_binding_events(session, relationship_id=relationship_id)},
        request_id_from_request(request),
    )


@router.post("/couple/relationships/{relationship_id}/unbind")
async def admin_unbind(
    relationship_id: UUID,
    payload: AdminUnbindRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("couples.relationships.unbind")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.admin_unbind_relationship(
            session,
            relationship_id=relationship_id,
            actor_id=principal.user.id,
            reason=payload.reason,
        ),
        request_id_from_request(request),
    )


@router.get("/couple/free-benefits/{pair_key}")
async def free_benefit(
    pair_key: str,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("couples.free_benefits.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Support answer to "why is their SCOPE not free?" — the pair already used it."""

    return success(
        await service.admin_free_benefit(session, key=pair_key),
        request_id_from_request(request),
    )


# --- SCOPE-001 question bank ------------------------------------------------


@router.post("/couple/scope/versions")
async def create_version(
    payload: ScopeVersionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("couples.scope.versions.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_scope_version(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/couple/scope/versions")
async def list_versions(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("couples.scope.versions.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_scope_versions(session)},
        request_id_from_request(request),
    )


@router.post("/couple/scope/versions/{version_id}/questions")
async def add_question(
    version_id: UUID,
    payload: ScopeQuestionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("couples.scope.versions.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """The question bank ships empty; administrators author it (DEC-001)."""

    return success(
        await service.add_scope_question(
            session,
            version_id=version_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/couple/scope/versions/{version_id}/publish")
async def publish_version(
    version_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("couples.scope.versions.publish")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.publish_scope_version(
            session, version_id=version_id, actor_id=principal.user.id
        ),
        request_id_from_request(request),
    )


@router.put("/couple/scope/assessments/{assessment_id}/advice")
async def attach_advice(
    assessment_id: UUID,
    payload: ScopeAdviceRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("couples.scope.advice.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Attach the AI narrative. Stored in its own columns, never in ``scores``."""

    return success(
        await service.attach_scope_advice(
            session,
            assessment_id=assessment_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )
