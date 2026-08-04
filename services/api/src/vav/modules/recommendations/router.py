"""Member-facing recommendation API."""

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
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.recommendations import coldstart, explanations, feedback_service, service
from vav.modules.recommendations.schemas import (
    BatchRequest,
    ExposureRequest,
    FeedbackRequest,
    TuningRequest,
)

router = APIRouter()


@router.get("/recommendations")
async def list_recommendations(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    return success(
        await service.current_batch(session, principal.user), request_id_from_request(request)
    )


@router.post("/recommendations/batches", status_code=201)
async def create_batch(
    payload: BatchRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Generate the next batch, bounded by today's receive budget."""
    service.enabled()
    await service.sync_pool_entry(session, principal.user.id)
    await session.commit()
    await service.generate_candidates(session, principal.user.id)
    return success(
        await service.generate_batch(
            session,
            principal.user.id,
            batch_type=payload.batch_type,
            requested_size=payload.requested_size,
        ),
        request_id_from_request(request),
    )


@router.get("/recommendations/{item_id}")
async def recommendation_detail(
    item_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """One recommendation, re-checked against the candidate's current state."""
    service.enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT i.*, d.status AS profile_status FROM recommendation_items i "
                    "JOIN dating_profiles d ON d.user_id=i.recommended_user_id WHERE i.id=:id"
                ),
                {"id": item_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["viewer_user_id"] != principal.user.id:
        raise VavError(
            "RECOMMENDATION_ITEM_NOT_FOUND", "Recommendation not found.", status_code=404
        )
    if row["status"] == "invalidated" or row["profile_status"] != "active":
        raise VavError(
            "RECOMMENDATION_NO_LONGER_AVAILABLE",
            "This recommendation is no longer available.",
            status_code=404,
        )
    safety = await service.evaluate_recommendation_pair_safety(
        session, principal.user.id, row["recommended_user_id"]
    )
    if not safety["allowed"]:
        raise VavError(
            "RECOMMENDATION_NO_LONGER_AVAILABLE",
            "This recommendation is no longer available.",
            status_code=404,
        )
    return success(
        {
            **service._item_dto(dict(row)),
            "dating_profile_endpoint": f"/api/v1/dating-profiles/{row['recommended_user_id']}",
            # Batch 15 owns like / skip / withdraw; only the contract exists here.
            "available_actions": ["record_feedback"],
            "actions_pending_batch_15": ["like", "skip", "withdraw", "introduction_request"],
        },
        request_id_from_request(request),
    )


@router.post("/recommendations/{item_id}/exposure")
async def record_exposure(
    item_id: UUID,
    payload: ExposureRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.record_exposure(
            session,
            principal.user,
            item_id,
            exposure_type=payload.exposure_type,
            duration_ms=payload.duration_ms,
            idempotency_key=payload.idempotency_key,
            source=payload.source,
        ),
        request_id_from_request(request),
    )


@router.post("/recommendations/feedback", status_code=201)
async def record_feedback(
    payload: FeedbackRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await feedback_service.record_feedback(
            session,
            principal.user,
            recommended_user_id=payload.recommended_user_id,
            feedback_type=payload.feedback_type,
            reason_code=payload.reason_code,
            reason_details=payload.reason_details,
            recommendation_item_id=payload.recommendation_item_id,
            idempotency_key=payload.idempotency_key,
        ),
        request_id_from_request(request),
    )


@router.get("/account/recommendation-preferences")
async def get_preferences(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    settings = get_settings()
    tuning = await service.tuning_profile(session, principal.user.id)
    await session.commit()
    return success(
        {
            "exploration_level": tuning["exploration_level"],
            "feedback_personalization_enabled": tuning["feedback_personalization_enabled"],
            "daily_received_limit": tuning["daily_received_limit"]
            or settings.recommendation_max_daily_received,
            "maximum_daily_received_limit": settings.recommendation_max_daily_received,
            "allow_relaxed_recommendations": tuning["allow_relaxed_recommendations"],
            "recommendations_paused": tuning["recommendations_paused"],
            "tuning_version": tuning["tuning_version"],
            "cannot_configure": [
                "绕过安全限制",
                "查看对方的隐藏偏好",
                "强制某个用户出现在推荐中",
                "突破对方的硬性条件",
            ],
        },
        request_id_from_request(request),
    )


@router.put("/account/recommendation-preferences")
async def update_preferences(
    payload: TuningRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await feedback_service.update_tuning(
        session,
        principal.user,
        exploration_level=payload.exploration_level,
        feedback_personalization_enabled=payload.feedback_personalization_enabled,
        daily_received_limit=payload.daily_received_limit,
        allow_relaxed_recommendations=payload.allow_relaxed_recommendations,
        recommendations_paused=payload.recommendations_paused,
    )
    return success(
        {
            "exploration_level": result["exploration_level"],
            "feedback_personalization_enabled": result["feedback_personalization_enabled"],
            "daily_received_limit": result["daily_received_limit"],
            "allow_relaxed_recommendations": result["allow_relaxed_recommendations"],
            "recommendations_paused": result["recommendations_paused"],
            "tuning_version": result["tuning_version"],
        },
        request_id_from_request(request),
    )


@router.post("/account/recommendation-preferences/reset")
async def reset_preferences(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await feedback_service.reset_tuning(session, principal.user),
        request_id_from_request(request),
    )


@router.get("/account/recommendation-history")
async def recommendation_history(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    service.enabled()
    total = await session.scalar(
        text("SELECT count(*) FROM recommendation_items WHERE viewer_user_id=:id"),
        {"id": principal.user.id},
    )
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,recommended_user_id,rank_position,status,is_exploration_slot,created_at "
                    "FROM recommendation_items WHERE viewer_user_id=:id ORDER BY created_at DESC "
                    "LIMIT :limit OFFSET :offset"
                ),
                {
                    "id": principal.user.id,
                    "limit": min(page_size, 100),
                    "offset": (page - 1) * page_size,
                },
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


@router.get("/account/recommendation-transparency")
async def transparency(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """What the member may learn about how their own recommendations are built."""
    service.enabled()
    criteria: list[dict[str, Any]] = []
    projection = (
        (
            await session.execute(
                text(
                    "SELECT indexed_preference_criteria FROM dating_profile_recommendation_projections WHERE user_id=:id"
                ),
                {"id": principal.user.id},
            )
        )
        .mappings()
        .first()
    )
    if projection:
        criteria = list(projection["indexed_preference_criteria"])
    tuning = await service.tuning_profile(session, principal.user.id)
    guidance = coldstart.preference_guidance(len(criteria))
    await session.commit()
    return success(
        {
            **explanations.transparency_summary(criteria),
            "feedback_personalization_enabled": tuning["feedback_personalization_enabled"],
            "preference_guidance": guidance,
        },
        request_id_from_request(request),
    )
