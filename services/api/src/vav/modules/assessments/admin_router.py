"""Administrative paid assessment API (B17).

Permission-gated server-side (AUTH-002). The licence-verification route is
separate from version authoring on purpose: whoever signs off that the platform
may sell a version is named in the audit trail as a distinct action.
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
from vav.modules.assessments import service
from vav.modules.assessments.schemas import (
    AdviceRequest,
    LicenseVerificationRequest,
    ProductRequest,
    RefundRequest,
    VersionQuestionRequest,
    VersionRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin")


# --- catalogue --------------------------------------------------------------


@router.post("/assessments/products")
async def create_product(
    payload: ProductRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("assessments.products.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_product(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.post("/assessments/products/{product_id}/activate")
async def activate_product(
    product_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("assessments.products.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.activate_product(session, product_id=product_id, actor_id=principal.user.id),
        request_id_from_request(request),
    )


@router.get("/assessments/catalogue")
async def catalogue(
    request: Request,
    include_unpublished: bool = Query(default=True),
    _principal: AuthenticatedPrincipal = Depends(require_permission("assessments.versions.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_catalogue(session, include_unpublished=include_unpublished)},
        request_id_from_request(request),
    )


# --- versions and licensing -------------------------------------------------


@router.post("/assessments/products/{product_id}/versions")
async def create_version(
    product_id: UUID,
    payload: VersionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("assessments.versions.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_version(
            session,
            product_id=product_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/assessments/versions/{version_id}/license-verification")
async def verify_license(
    version_id: UUID,
    payload: LicenseVerificationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("assessments.licenses.verify")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Record who verified the licence. Publication is impossible without this."""

    return success(
        await service.verify_license(
            session,
            version_id=version_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/assessments/versions/{version_id}/questions")
async def add_question(
    version_id: UUID,
    payload: VersionQuestionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("assessments.versions.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Administrator-supplied items only; no licensed instrument ships in code."""

    return success(
        await service.add_version_question(
            session,
            version_id=version_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/assessments/versions/{version_id}/publish")
async def publish_version(
    version_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("assessments.versions.publish")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.publish_version(session, version_id=version_id, actor_id=principal.user.id),
        request_id_from_request(request),
    )


@router.post("/assessments/versions/{version_id}/retire")
async def retire_version(
    version_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("assessments.versions.publish")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.retire_version(session, version_id=version_id, actor_id=principal.user.id),
        request_id_from_request(request),
    )


@router.get("/assessments/license-audit")
async def license_audit(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("assessments.licenses.verify")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.admin_license_audit(session)},
        request_id_from_request(request),
    )


# --- commerce ---------------------------------------------------------------


@router.get("/assessments/purchases")
async def purchases(
    request: Request,
    user_id: UUID | None = Query(default=None),
    _principal: AuthenticatedPrincipal = Depends(require_permission("assessments.purchases.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.admin_list_purchases(session, user_id=user_id)},
        request_id_from_request(request),
    )


@router.post("/assessments/purchases/{purchase_id}/refund")
async def refund(
    purchase_id: UUID,
    payload: RefundRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("assessments.refunds.process")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Administrative refund. ``admin_override`` is only honoured on this route."""

    return success(
        await service.refund_purchase(
            session,
            purchase_id=purchase_id,
            actor_id=principal.user.id,
            actor_kind="admin",
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.put("/assessments/attempts/{attempt_id}/advice")
async def attach_advice(
    attempt_id: UUID,
    payload: AdviceRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("assessments.advice.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.attach_advice(
            session,
            attempt_id=attempt_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )
