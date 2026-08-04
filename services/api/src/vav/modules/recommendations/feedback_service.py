"""Persisted feedback intake and member tuning controls."""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.identity import User
from vav.modules.privacy.crypto import encrypt_private
from vav.modules.recommendations import feedback as feedback_rules
from vav.modules.recommendations import service
from vav.modules.recommendations.domain import (
    SKIP_REASON_CODES,
    RecommendationFeedbackType,
)


async def record_feedback(
    session: AsyncSession,
    viewer: User,
    *,
    recommended_user_id: UUID,
    feedback_type: str,
    reason_code: str | None,
    reason_details: str | None,
    recommendation_item_id: UUID | None,
    idempotency_key: str,
    source_module: str = "recommendations",
    source_event_id: UUID | None = None,
) -> dict[str, Any]:
    """Record one feedback event and apply its bounded, reversible effect."""
    service.enabled()
    settings = get_settings()
    try:
        parsed = RecommendationFeedbackType(feedback_type)
    except ValueError as exc:
        raise VavError(
            "RECOMMENDATION_FEEDBACK_TYPE_INVALID", "Unknown feedback type.", status_code=422
        ) from exc
    if reason_code and reason_code not in SKIP_REASON_CODES:
        raise VavError(
            "RECOMMENDATION_FEEDBACK_REASON_INVALID",
            "This feedback reason is not recognised.",
            status_code=422,
        )
    if viewer.id == recommended_user_id:
        raise VavError("RECOMMENDATION_FEEDBACK_SELF", "You cannot rate yourself.", status_code=422)

    candidate_pair_id = None
    if recommendation_item_id is not None:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT viewer_user_id,recommended_user_id,candidate_pair_id FROM recommendation_items WHERE id=:id"
                    ),
                    {"id": recommendation_item_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None or row["viewer_user_id"] != viewer.id:
            raise VavError(
                "RECOMMENDATION_ITEM_NOT_FOUND", "Recommendation not found.", status_code=404
            )
        candidate_pair_id = row["candidate_pair_id"]

    inserted = await session.scalar(
        text(
            "INSERT INTO recommendation_feedback_events "
            "(viewer_user_id,recommended_user_id,recommendation_item_id,candidate_pair_id,feedback_type,"
            "reason_code,reason_details_encrypted,source_module,source_event_id,idempotency_key) "
            "VALUES (:viewer,:recommended,:item,:pair,:type,:reason,:details,:module,:source_event,:key) "
            "ON CONFLICT (viewer_user_id,idempotency_key) DO NOTHING RETURNING id"
        ),
        {
            "viewer": viewer.id,
            "recommended": recommended_user_id,
            "item": recommendation_item_id,
            "pair": candidate_pair_id,
            "type": parsed.value,
            "reason": reason_code,
            # Free-text stays encrypted and is never shown to the other member.
            "details": encrypt_private(reason_details) if reason_details else None,
            "module": source_module,
            "source_event": source_event_id,
            "key": idempotency_key[:128],
        },
    )
    if inserted is None:
        await session.commit()
        return {"recorded": False, "duplicate": True}

    effects = feedback_rules.effects_for(parsed.value)

    if effects.get("starts_cooldown"):
        until = feedback_rules.cooldown_until(
            parsed.value, cooldown_days=settings.recommendation_skip_cooldown_days
        )
        await session.execute(
            text(
                "INSERT INTO recommendation_skip_cooldowns (viewer_user_id,skipped_user_id,reason_code,cooldown_until) "
                "VALUES (:viewer,:skipped,:reason,:until) "
                "ON CONFLICT (viewer_user_id,skipped_user_id) DO UPDATE SET cooldown_until=EXCLUDED.cooldown_until,"
                "reason_code=EXCLUDED.reason_code"
            ),
            {
                "viewer": viewer.id,
                "skipped": recommended_user_id,
                "reason": reason_code,
                "until": until,
            },
        )

    if effects.get("removes_candidate"):
        await session.execute(
            text(
                "UPDATE recommendation_candidate_pairs SET status='invalidated',invalidated_at=now(),"
                "invalidation_reason=:reason WHERE ((user_low_id=:a AND user_high_id=:b) "
                "OR (user_low_id=:b AND user_high_id=:a)) AND invalidated_at IS NULL"
            ),
            {"a": viewer.id, "b": recommended_user_id, "reason": parsed.value},
        )
        await session.execute(
            text(
                "UPDATE recommendation_items SET status='invalidated',invalidation_reason=:reason "
                "WHERE ((viewer_user_id=:a AND recommended_user_id=:b) OR (viewer_user_id=:b AND recommended_user_id=:a)) "
                "AND status IN ('ready','exposed','viewed')"
            ),
            {"a": viewer.id, "b": recommended_user_id, "reason": parsed.value},
        )

    if effects.get("notifies_safety"):
        # Safety owns the case; recommendations only signal and step aside.
        await service.emit_event(
            session,
            "recommendation.feedback.received",
            viewer.id,
            {
                "feedback_type": parsed.value,
                "requires_safety_review": True,
                "recommended_user_id": str(recommended_user_id),
            },
        )

    tuning = await service.tuning_profile(session, viewer.id)
    if not feedback_rules.is_safety_feedback(parsed.value):
        adjustments = feedback_rules.apply_learning(
            dict(tuning["feature_weight_adjustments"]),
            feedback_type=parsed.value,
            reason_code=reason_code,
            personalization_enabled=bool(tuning["feedback_personalization_enabled"]),
        )
        if adjustments != tuning["feature_weight_adjustments"]:
            await session.execute(
                text(
                    "UPDATE recommendation_user_tuning_profiles SET feature_weight_adjustments=CAST(:adjustments AS jsonb),"
                    "tuning_version=tuning_version+1,derived_from_feedback_through=now(),updated_at=now() WHERE user_id=:id"
                ),
                {"id": viewer.id, "adjustments": service.json_value(adjustments)},
            )

    if recommendation_item_id is not None and parsed.value in {"liked", "skipped", "not_relevant"}:
        await session.execute(
            text(
                "UPDATE recommendation_items SET status=:status WHERE id=:id AND status IN ('ready','exposed','viewed')"
            ),
            {
                "id": recommendation_item_id,
                "status": "acted" if parsed.value == "liked" else "skipped",
            },
        )

    await service.audit(
        session,
        "recommendation.feedback.received",
        "recommendation_item",
        recommendation_item_id,
        actor_id=viewer.id,
        context={"feedback_type": parsed.value, "reason_code": reason_code},
    )
    await session.commit()
    return {
        "recorded": True,
        "duplicate": False,
        "feedback_type": parsed.value,
        "used_for_learning": bool(effects.get("learning"))
        and not feedback_rules.is_safety_feedback(parsed.value),
        "removed_from_candidates": bool(effects.get("removes_candidate")),
    }


async def update_tuning(
    session: AsyncSession,
    viewer: User,
    *,
    exploration_level: str | None,
    feedback_personalization_enabled: bool | None,
    daily_received_limit: int | None,
    allow_relaxed_recommendations: bool | None,
    recommendations_paused: bool | None,
) -> dict[str, Any]:
    """Apply the member's own recommendation settings."""
    service.enabled()
    settings = get_settings()
    await service.tuning_profile(session, viewer.id)
    if exploration_level is not None and exploration_level not in {"focused", "balanced", "open"}:
        raise VavError(
            "RECOMMENDATION_EXPLORATION_LEVEL_INVALID",
            "Unknown exploration level.",
            status_code=422,
        )
    if daily_received_limit is not None and not (
        1 <= daily_received_limit <= settings.recommendation_max_daily_received
    ):
        raise VavError(
            "RECOMMENDATION_DAILY_LIMIT_INVALID",
            f"The daily limit must be between 1 and {settings.recommendation_max_daily_received}.",
            status_code=422,
        )
    if allow_relaxed_recommendations and not settings.recommendation_allow_user_relaxation:
        raise VavError(
            "RECOMMENDATION_RELAXATION_DISABLED",
            "Relaxed recommendations are disabled on this platform.",
            status_code=409,
        )

    await session.execute(
        text(
            "UPDATE recommendation_user_tuning_profiles SET "
            "exploration_level=COALESCE(:exploration, exploration_level),"
            "feedback_personalization_enabled=COALESCE(:personalization, feedback_personalization_enabled),"
            "daily_received_limit=COALESCE(:daily_limit, daily_received_limit),"
            "allow_relaxed_recommendations=COALESCE(:relaxation, allow_relaxed_recommendations),"
            "recommendations_paused=COALESCE(:paused, recommendations_paused),"
            "tuning_version=tuning_version+1,updated_at=now() WHERE user_id=:id"
        ),
        {
            "id": viewer.id,
            "exploration": exploration_level,
            "personalization": feedback_personalization_enabled,
            "daily_limit": daily_received_limit,
            "relaxation": allow_relaxed_recommendations,
            "paused": recommendations_paused,
        },
    )
    if feedback_personalization_enabled is False:
        # Turning personalisation off must stop using behaviour immediately.
        await session.execute(
            text(
                "UPDATE recommendation_user_tuning_profiles SET feature_weight_adjustments='{}'::jsonb,"
                "derived_from_feedback_through=NULL WHERE user_id=:id"
            ),
            {"id": viewer.id},
        )
    if recommendations_paused:
        await service.invalidate_candidates_for(
            session, viewer.id, "recommendations_paused", commit=False
        )
    await service.sync_pool_entry(session, viewer.id)
    await service.audit(
        session,
        "recommendation.user_tuning.updated",
        "user",
        viewer.id,
        actor_id=viewer.id,
        context={
            "exploration_level": exploration_level,
            "personalization_enabled": feedback_personalization_enabled,
            "paused": recommendations_paused,
        },
    )
    await session.commit()
    return await service.tuning_profile(session, viewer.id)


async def reset_tuning(session: AsyncSession, viewer: User) -> dict[str, Any]:
    """Clear learned adjustments while keeping the member's stated criteria."""
    service.enabled()
    await service.tuning_profile(session, viewer.id)
    await session.execute(
        text(
            "UPDATE recommendation_user_tuning_profiles SET feature_weight_adjustments='{}'::jsonb,"
            "exploration_level='balanced',derived_from_feedback_through=NULL,"
            "tuning_version=tuning_version+1,updated_at=now() WHERE user_id=:id"
        ),
        {"id": viewer.id},
    )
    await service.audit(
        session,
        "recommendation.user_tuning.reset",
        "user",
        viewer.id,
        actor_id=viewer.id,
        context={"explicit_preferences_preserved": True},
    )
    await session.commit()
    return {
        "reset": True,
        "explicit_partner_preferences_preserved": True,
        "learning_stage": feedback_rules.learning_stage_summary(),
    }
