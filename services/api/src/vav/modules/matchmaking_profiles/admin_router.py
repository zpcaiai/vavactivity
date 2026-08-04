"""Admin dating-profile review center."""

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
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.matchmaking_profiles import review as review_service
from vav.modules.matchmaking_profiles import service
from vav.modules.matchmaking_profiles.domain import DatingProfileViewContext
from vav.modules.matchmaking_profiles.schemas import (
    RestoreRequest,
    ReviewApproveRequest,
    ReviewAssignRequest,
    ReviewChangesRequest,
    ReviewEscalateRequest,
    ReviewItemRequest,
    ReviewRejectRequest,
    ReviewStartRequest,
    SuspendRequest,
)

router = APIRouter(prefix="/admin")


@router.get("/dating-profiles")
async def list_profiles(
    request: Request,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.profiles.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    clause = "WHERE status=:status" if status else ""
    params: dict[str, Any] = {"status": status} if status else {}
    total = await session.scalar(text(f"SELECT count(*) FROM dating_profiles {clause}"), params)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,profile_number,status,review_status,completeness_basis_points,"
                    "current_version_number,approved_version_number,submitted_at,updated_at "
                    f"FROM dating_profiles {clause} ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
                ),
                params | {"limit": min(page_size, 100), "offset": (page - 1) * page_size},
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": int(total or 0),
        },
        request_id_from_request(request),
    )


@router.get("/dating-profiles/{profile_id}")
async def profile_detail(
    profile_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.profiles.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    projection = await service.viewer_projection(
        session,
        profile_id=profile_id,
        viewer=principal.user,
        context=DatingProfileViewContext.ADMIN_REVIEW,
    )
    await service.audit(
        session,
        "matchmaking.profile.sensitive_read",
        "dating_profile",
        profile_id,
        actor_id=principal.user.id,
        context={
            "sensitive_permission": "matchmaking.profiles.sensitive.read" in principal.permissions
        },
    )
    await session.commit()
    return success(
        {
            "projection": projection,
            # Reviewers never receive contact details, AI transcripts,
            # counseling records or payment data through this endpoint.
            "excluded_domains": [
                "contact_details",
                "ai_conversations",
                "counseling_records",
                "payment_details",
                "credentials",
            ],
        },
        request_id_from_request(request),
    )


@router.get("/dating-profile-reviews")
async def list_reviews(
    request: Request,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.reviews.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.list_cases(
            session, status=status, page=page, page_size=min(page_size, 100)
        ),
        request_id_from_request(request),
    )


@router.get("/dating-profile-reviews/{case_id}")
async def review_detail(
    case_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.reviews.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.case_detail(
            session,
            case_id,
            include_sensitive="matchmaking.profiles.sensitive.read" in principal.permissions,
        ),
        request_id_from_request(request),
    )


@router.post("/dating-profile-reviews/{case_id}/assign")
async def assign(
    case_id: UUID,
    payload: ReviewAssignRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.reviews.assign")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.assign_case(
            session, principal.user, case_id, payload.assignee_id, payload.expected_version
        ),
        request_id_from_request(request),
    )


@router.post("/dating-profile-reviews/{case_id}/start")
async def start(
    case_id: UUID,
    payload: ReviewStartRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.reviews.decide")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.start_case(session, principal.user, case_id, payload.expected_version),
        request_id_from_request(request),
    )


@router.post("/dating-profile-reviews/{case_id}/items", status_code=201)
async def add_item(
    case_id: UUID,
    payload: ReviewItemRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.reviews.decide")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    if payload.item_type == "photo" and "matchmaking.photos.review" not in principal.permissions:
        raise VavError(
            "PERMISSION_DENIED", "Photo review requires a separate permission.", status_code=403
        )
    return success(
        await review_service.record_item(
            session,
            principal.user,
            case_id,
            item_type=payload.item_type,
            field_code=payload.field_code,
            photo_id=payload.photo_id,
            decision=payload.decision,
            reason_code=payload.reason_code,
            user_message_safe=payload.user_message_safe,
            internal_note=payload.internal_note,
        ),
        request_id_from_request(request),
    )


@router.post("/dating-profile-reviews/{case_id}/approve")
async def approve(
    case_id: UUID,
    payload: ReviewApproveRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.reviews.decide")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.approve_case(
            session,
            principal.user,
            case_id,
            user_message=payload.user_message,
            internal_summary=payload.internal_summary,
            expected_version=payload.expected_version,
        ),
        request_id_from_request(request),
    )


@router.post("/dating-profile-reviews/{case_id}/request-changes")
async def request_changes(
    case_id: UUID,
    payload: ReviewChangesRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.reviews.decide")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.request_changes(
            session,
            principal.user,
            case_id,
            user_message=payload.user_message,
            internal_summary=payload.internal_summary,
            expected_version=payload.expected_version,
        ),
        request_id_from_request(request),
    )


@router.post("/dating-profile-reviews/{case_id}/reject")
async def reject(
    case_id: UUID,
    payload: ReviewRejectRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.reviews.decide")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.reject_case(
            session,
            principal.user,
            case_id,
            reason_code=payload.reason_code,
            user_message=payload.user_message,
            internal_summary=payload.internal_summary,
            expected_version=payload.expected_version,
        ),
        request_id_from_request(request),
    )


@router.post("/dating-profile-reviews/{case_id}/escalate")
async def escalate(
    case_id: UUID,
    payload: ReviewEscalateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.reviews.escalate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.escalate_case(
            session,
            principal.user,
            case_id,
            reason=payload.reason,
            expected_version=payload.expected_version,
        ),
        request_id_from_request(request),
    )


@router.get("/dating-profile-photo-reviews")
async def photo_review_queue(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.photos.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    total = await session.scalar(
        text(
            "SELECT count(*) FROM dating_profile_photos WHERE status='review_required' AND deleted_at IS NULL"
        )
    )
    rows = (
        (
            await session.execute(
                text(
                    "SELECT p.id,p.dating_profile_id,p.photo_role,p.status,p.processing_report,p.created_at,"
                    "d.profile_number FROM dating_profile_photos p JOIN dating_profiles d ON d.id=p.dating_profile_id "
                    "WHERE p.status='review_required' AND p.deleted_at IS NULL "
                    "ORDER BY p.created_at LIMIT :limit OFFSET :offset"
                ),
                {"limit": min(page_size, 100), "offset": (page - 1) * page_size},
            )
        )
        .mappings()
        .all()
    )
    can_view_original = "matchmaking.photos.original.read" in principal.permissions
    return success(
        {
            "items": [
                {
                    "photo_id": str(row["id"]),
                    "profile_number": row["profile_number"],
                    "photo_role": row["photo_role"],
                    "status": row["status"],
                    "quality_flags": (row["processing_report"] or {}).get("quality_flags", []),
                    "automated_findings_are_advisory": True,
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": int(total or 0),
            "original_access_granted": can_view_original,
        },
        request_id_from_request(request),
    )


@router.post("/dating-profiles/{profile_id}/suspend")
async def suspend(
    profile_id: UUID,
    payload: SuspendRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.profiles.suspend")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.suspend_profile(
            session, principal.user, profile_id, reason_code=payload.reason_code
        ),
        request_id_from_request(request),
    )


@router.post("/dating-profiles/{profile_id}/restore")
async def restore(
    profile_id: UUID,
    payload: RestoreRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.profiles.restore")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.restore_profile(
            session, principal.user, profile_id, reason=payload.reason
        ),
        request_id_from_request(request),
    )


@router.get("/dating-profile-versions/{left}/diff/{right}")
async def admin_diff(
    left: int,
    right: int,
    request: Request,
    profile_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.reviews.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await service.version_diff(session, profile_id, left, right),
        request_id_from_request(request),
    )


@router.get("/dating-schema-releases")
async def schema_releases(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.schemas.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,schema_code,semantic_version,status,valid_from,valid_until,created_at,approved_at "
                    "FROM dating_profile_schema_releases ORDER BY created_at DESC"
                )
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


@router.get("/dating-taxonomies")
async def taxonomies(
    request: Request,
    locale: str = "zh-CN",
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.taxonomies.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        {"taxonomies": await service.active_taxonomies(session, locale)},
        request_id_from_request(request),
    )


@router.get("/dating-projections")
async def projections(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.projections.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    total = await session.scalar(
        text("SELECT count(*) FROM dating_profile_recommendation_projections")
    )
    rows = (
        (
            await session.execute(
                text(
                    "SELECT dating_profile_id,approved_profile_version,preference_version,privacy_settings_version,"
                    "eligible,age_bucket,country_code,region_code,city_code,projection_checksum,projection_version,updated_at "
                    "FROM dating_profile_recommendation_projections ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
                ),
                {"limit": min(page_size, 100), "offset": (page - 1) * page_size},
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": int(total or 0),
        },
        request_id_from_request(request),
    )


@router.post("/dating-projections/{profile_id}/rebuild")
async def rebuild(
    profile_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.projections.rebuild")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await service.rebuild_projection(session, profile_id), request_id_from_request(request)
    )


@router.post("/dating-projections/process-jobs")
async def process_jobs(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.projections.rebuild")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(await service.process_projection_jobs(session), request_id_from_request(request))


@router.get("/dating-profile-audit")
async def audit_events(
    request: Request,
    subject_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await review_service.audit_trail(
            session, subject_id=subject_id, page=page, page_size=min(page_size, 200)
        ),
        request_id_from_request(request),
    )
