"""Feedback ingestion, negative-feedback protection and member tuning.

Feedback is idempotent and typed. A skip starts a cooldown and never becomes a
hidden hard constraint; a block or report removes the candidate immediately and
is handed to the safety domain rather than used as preference-learning data.
Members can switch behavioural personalisation off, and reset it entirely.
"""

# ruff: noqa: E501
from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.privacy.crypto import encrypt_private
from vav.modules.recommendations import service
from vav.modules.recommendations.domain import (
    COOLDOWN_FEEDBACK_TYPES,
    FEEDBACK_REASON_CODES,
    MEMBER_FEEDBACK_TYPES,
    SAFETY_FEEDBACK_TYPES,
    RecommendationFeedbackType,
    canonical_pair,
)
from vav.modules.recommendations.features import FEATURES_BY_CODE

#: Weight nudge applied per repeated negative signal, bounded by the scorer.
TUNING_STEP = 0.1
MIN_ADJUSTMENT = 0.5
MAX_ADJUSTMENT = 1.5

#: Negative reasons that may inform a weight nudge, mapped to feature codes.
REASON_FEATURES: dict[str, tuple[str, ...]] = {
    "location_not_suitable": ("location_compatibility", "relocation_alignment"),
    "faith_expectations_differ": (
        "faith_status_alignment",
        "church_tradition_overlap",
        "marriage_faith_importance_alignment",
    ),
    "relationship_goals_differ": ("relationship_intent_alignment",),
    "family_and_children_expectations_differ": (
        "desire_children_alignment",
        "children_expectation_alignment",
    ),
    "lifestyle_not_suitable": (
        "daily_schedule_alignment",
        "smoking_alignment",
        "alcohol_alignment",
    ),
}


def feedback_idempotency_key(
    *,
    viewer_user_id: UUID,
    recommended_user_id: UUID,
    feedback_type: str,
    source_module: str,
    source_event_id: UUID | None,
) -> str:
    material = (
        f"{viewer_user_id}:{recommended_user_id}:{feedback_type}:{source_module}:{source_event_id or ''}"
    ).encode()
    return hashlib.sha256(material).hexdigest()[:64]


async def ingest(
    session: AsyncSession,
    *,
    viewer_user_id: UUID,
    recommended_user_id: UUID,
    feedback_type: str,
    recommendation_item_id: UUID | None = None,
    reason_code: str | None = None,
    reason_details: str | None = None,
    source_module: str = "recommendations",
    source_event_id: UUID | None = None,
    idempotency_key: str | None = None,
    from_member: bool = False,
) -> dict[str, Any]:
    """Record one feedback event and apply its protective consequences."""
    service.enabled()
    try:
        typed = RecommendationFeedbackType(feedback_type)
    except ValueError as error:
        raise VavError(
            "RECOMMENDATION_FEEDBACK_TYPE_INVALID",
            f"Unsupported feedback type {feedback_type}.",
            status_code=422,
        ) from error
    if from_member and typed.value not in MEMBER_FEEDBACK_TYPES:
        raise VavError(
            "RECOMMENDATION_FEEDBACK_NOT_MEMBER_OWNED",
            "Likes, skips and introductions are recorded by the interaction module.",
            status_code=409,
        )
    if reason_code is not None and reason_code not in FEEDBACK_REASON_CODES:
        raise VavError(
            "RECOMMENDATION_FEEDBACK_REASON_INVALID",
            "Unsupported feedback reason.",
            status_code=422,
        )
    if viewer_user_id == recommended_user_id:
        raise VavError(
            "RECOMMENDATION_FEEDBACK_SELF", "A member cannot rate themselves.", status_code=422
        )

    candidate_pair_id: UUID | None = None
    if recommendation_item_id is not None:
        row = (
            await session.execute(
                text(
                    "SELECT candidate_pair_id, recommended_user_id FROM recommendation_items "
                    "WHERE id=:id AND viewer_user_id=:viewer"
                ),
                {"id": recommendation_item_id, "viewer": viewer_user_id},
            )
        ).mappings()
        item = row.first()
        if item is None:
            raise VavError(
                "RECOMMENDATION_ITEM_NOT_FOUND", "Recommendation not found.", status_code=404
            )
        candidate_pair_id = item["candidate_pair_id"]

    key = idempotency_key or feedback_idempotency_key(
        viewer_user_id=viewer_user_id,
        recommended_user_id=recommended_user_id,
        feedback_type=typed.value,
        source_module=source_module,
        source_event_id=source_event_id or recommendation_item_id,
    )
    encrypted_details = encrypt_private(reason_details) if reason_details else None

    inserted = (
        await session.execute(
            text(
                "INSERT INTO recommendation_feedback_events "
                "(viewer_user_id,recommended_user_id,recommendation_item_id,candidate_pair_id,"
                "feedback_type,reason_code,reason_details_encrypted,source_module,source_event_id,"
                "idempotency_key) VALUES (:viewer,:recommended,:item,:pair,:type,:reason,:details,"
                ":module,:source_event,:key) "
                "ON CONFLICT (viewer_user_id,idempotency_key) DO NOTHING RETURNING *"
            ),
            {
                "viewer": viewer_user_id,
                "recommended": recommended_user_id,
                "item": recommendation_item_id,
                "pair": candidate_pair_id,
                "type": typed.value,
                "reason": reason_code,
                "details": encrypted_details,
                "module": source_module,
                "source_event": source_event_id,
                "key": key,
            },
        )
    ).mappings()
    created = inserted.first()
    if created is None:
        return {"recorded": False, "reason_code": "duplicate_event"}

    await _apply_consequences(
        session,
        viewer_user_id=viewer_user_id,
        recommended_user_id=recommended_user_id,
        feedback_type=typed.value,
        reason_code=reason_code,
        recommendation_item_id=recommendation_item_id,
    )
    await service.audit(
        session,
        "recommendation.feedback.received",
        "recommendation_feedback",
        created["id"],
        context={"feedback_type": typed.value, "has_reason": reason_code is not None},
    )
    return {"recorded": True, "feedback_id": created["id"], "feedback_type": typed.value}


async def _apply_consequences(
    session: AsyncSession,
    *,
    viewer_user_id: UUID,
    recommended_user_id: UUID,
    feedback_type: str,
    reason_code: str | None,
    recommendation_item_id: UUID | None,
) -> None:
    settings = get_settings()
    low, high = canonical_pair(viewer_user_id, recommended_user_id)

    if feedback_type in SAFETY_FEEDBACK_TYPES:
        await _add_exclusion(
            session,
            low=low,
            high=high,
            exclusion_type="safety_block",
            source_module="moderation",
            reason_code=feedback_type,
            expires_at=None,
        )
        await session.execute(
            text(
                "UPDATE recommendation_items SET status='invalidated', invalidated_at=now(), "
                "invalidation_reason=:reason WHERE ((viewer_user_id=:a AND recommended_user_id=:b) "
                "OR (viewer_user_id=:b AND recommended_user_id=:a)) AND status IN ('ready','exposed','viewed')"
            ),
            {"a": viewer_user_id, "b": recommended_user_id, "reason": feedback_type},
        )
        await session.execute(
            text(
                "UPDATE recommendation_candidate_pairs SET status='safety_blocked', invalidated_at=now(), "
                "invalidation_reason=:reason WHERE user_low_id=:low AND user_high_id=:high"
            ),
            {"low": low, "high": high, "reason": feedback_type},
        )
        await service.emit_event(
            session,
            "recommendation.safety.signal",
            recommended_user_id,
            {"feedback_type": feedback_type, "reported_by": str(viewer_user_id)},
        )
        return

    if feedback_type in COOLDOWN_FEEDBACK_TYPES:
        await _add_exclusion(
            session,
            low=low,
            high=high,
            exclusion_type="skip_cooldown",
            source_module="recommendations",
            reason_code=reason_code or feedback_type,
            expires_at=service.utcnow()
            + timedelta(days=settings.recommendation_skip_cooldown_days),
        )
        if recommendation_item_id is not None:
            await session.execute(
                text(
                    "UPDATE recommendation_items SET status='skipped' WHERE id=:id "
                    "AND status IN ('ready','exposed','viewed')"
                ),
                {"id": recommendation_item_id},
            )
        if reason_code:
            await _nudge_tuning(session, viewer_user_id, reason_code)
        return

    if feedback_type in {
        RecommendationFeedbackType.MUTUAL_MATCHED.value,
        RecommendationFeedbackType.RELATIONSHIP_STARTED.value,
        RecommendationFeedbackType.INTRODUCTION_ACCEPTED.value,
    }:
        await _add_exclusion(
            session,
            low=low,
            high=high,
            exclusion_type="active_relationship",
            source_module="matchmaking",
            reason_code=feedback_type,
            expires_at=None,
        )
        return

    if feedback_type == RecommendationFeedbackType.RELATIONSHIP_ENDED.value:
        await session.execute(
            text(
                "UPDATE recommendation_pair_exclusions SET released_at=now() "
                "WHERE user_low_id=:low AND user_high_id=:high AND exclusion_type='active_relationship' "
                "AND released_at IS NULL"
            ),
            {"low": low, "high": high},
        )


async def _add_exclusion(
    session: AsyncSession,
    *,
    low: UUID,
    high: UUID,
    exclusion_type: str,
    source_module: str,
    reason_code: str | None,
    expires_at: Any,
) -> None:
    await session.execute(
        text(
            "INSERT INTO recommendation_pair_exclusions "
            "(user_low_id,user_high_id,exclusion_type,source_module,reason_code,expires_at) "
            "VALUES (:low,:high,:type,:module,:reason,:expires) "
            "ON CONFLICT (user_low_id,user_high_id,exclusion_type) WHERE released_at IS NULL "
            "DO UPDATE SET expires_at=EXCLUDED.expires_at, reason_code=EXCLUDED.reason_code"
        ),
        {
            "low": low,
            "high": high,
            "type": exclusion_type,
            "module": source_module,
            "reason": reason_code,
            "expires": expires_at,
        },
    )


async def _nudge_tuning(session: AsyncSession, user_id: UUID, reason_code: str) -> None:
    """Adjust a member's own soft weights, transparently and reversibly.

    A nudge only changes the weight of already-approved features, is bounded by
    the scorer, and never creates a new hard constraint.
    """
    profile = await service.tuning_profile(session, user_id)
    if not profile["feedback_personalization_enabled"]:
        return
    features = REASON_FEATURES.get(reason_code)
    if not features:
        return
    adjustments = dict(profile["feature_weight_adjustments"])
    for feature_code in features:
        if feature_code not in FEATURES_BY_CODE:
            continue
        current = float(adjustments.get(feature_code, 1.0))
        adjustments[feature_code] = round(
            max(MIN_ADJUSTMENT, min(MAX_ADJUSTMENT, current + TUNING_STEP)), 3
        )
    await session.execute(
        text(
            "INSERT INTO recommendation_user_tuning_profiles "
            "(user_id,tuning_version,feature_weight_adjustments,exploration_level,"
            "feedback_personalization_enabled,derived_from_feedback_through,updated_at) "
            "VALUES (:user_id,1,CAST(:adjustments AS jsonb),:level,true,now(),now()) "
            "ON CONFLICT (user_id) DO UPDATE SET feature_weight_adjustments=EXCLUDED.feature_weight_adjustments, "
            "tuning_version=recommendation_user_tuning_profiles.tuning_version + 1, "
            "derived_from_feedback_through=now(), updated_at=now()"
        ),
        {
            "user_id": user_id,
            "adjustments": service.json_value(adjustments),
            "level": str(profile["exploration_level"]),
        },
    )
    await service.audit(
        session,
        "recommendation.user_tuning.updated",
        "user",
        user_id,
        context={"adjusted_features": sorted(features)},
    )


async def update_tuning(
    session: AsyncSession,
    user_id: UUID,
    *,
    feedback_personalization_enabled: bool | None = None,
    exploration_level: str | None = None,
) -> dict[str, Any]:
    current = await service.tuning_profile(session, user_id)
    enabled = (
        current["feedback_personalization_enabled"]
        if feedback_personalization_enabled is None
        else bool(feedback_personalization_enabled)
    )
    level = exploration_level or str(current["exploration_level"])
    if level not in {"conservative", "balanced", "adventurous"}:
        raise VavError(
            "RECOMMENDATION_EXPLORATION_LEVEL_INVALID",
            "Unsupported exploration level.",
            status_code=422,
        )
    adjustments = current["feature_weight_adjustments"] if enabled else {}
    await session.execute(
        text(
            "INSERT INTO recommendation_user_tuning_profiles "
            "(user_id,tuning_version,feature_weight_adjustments,exploration_level,"
            "feedback_personalization_enabled,updated_at) "
            "VALUES (:user_id,1,CAST(:adjustments AS jsonb),:level,:enabled,now()) "
            "ON CONFLICT (user_id) DO UPDATE SET feature_weight_adjustments=EXCLUDED.feature_weight_adjustments, "
            "exploration_level=EXCLUDED.exploration_level, "
            "feedback_personalization_enabled=EXCLUDED.feedback_personalization_enabled, "
            "tuning_version=recommendation_user_tuning_profiles.tuning_version + 1, updated_at=now()"
        ),
        {
            "user_id": user_id,
            "adjustments": service.json_value(adjustments),
            "level": level,
            "enabled": enabled,
        },
    )
    await service.audit(
        session,
        "recommendation.user_tuning.updated",
        "user",
        user_id,
        context={"feedback_personalization_enabled": enabled, "exploration_level": level},
    )
    return await service.tuning_profile(session, user_id)


async def reset_tuning(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Clear behaviour-derived adjustments; stated criteria are untouched."""
    await session.execute(
        text(
            "UPDATE recommendation_user_tuning_profiles SET feature_weight_adjustments='{}'::jsonb, "
            "derived_from_feedback_through=NULL, tuning_version=tuning_version + 1, updated_at=now() "
            "WHERE user_id=:user_id"
        ),
        {"user_id": user_id},
    )
    await service.audit(session, "recommendation.user_tuning.reset", "user", user_id)
    return await service.tuning_profile(session, user_id)


async def feedback_summary(session: AsyncSession) -> dict[str, Any]:
    """Aggregate feedback counters for the operations dashboard."""
    rows = (
        await session.execute(
            text(
                "SELECT feedback_type, count(*) AS total FROM recommendation_feedback_events "
                "GROUP BY feedback_type ORDER BY total DESC"
            )
        )
    ).mappings()
    counts = {str(row["feedback_type"]): int(row["total"]) for row in rows}
    total = sum(counts.values())
    negative = sum(
        counts.get(code, 0)
        for code in (
            RecommendationFeedbackType.REPORTED.value,
            RecommendationFeedbackType.BLOCKED.value,
            RecommendationFeedbackType.NOT_RELEVANT.value,
        )
    )
    return {
        "counts_by_type": counts,
        "total_events": total,
        "negative_events": negative,
        "report_events": counts.get(RecommendationFeedbackType.REPORTED.value, 0),
        "block_events": counts.get(RecommendationFeedbackType.BLOCKED.value, 0),
    }
