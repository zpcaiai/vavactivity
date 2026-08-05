"""Likes, skips and withdrawal.

A like is a private, directional statement. Its target learns nothing — no
notification, no count, no API, no change in ordering — until and unless they
independently say the same thing back.
"""

# ruff: noqa: E501

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.matchmaking_interactions import matches as match_service
from vav.modules.matchmaking_interactions import service
from vav.modules.matchmaking_interactions.domain import (
    SKIP_REASON_CODES,
    CooldownType,
    InteractionSource,
    LikeStatus,
    SkipStatus,
    SkipType,
    canonical_pair,
    skip_cooldown_until,
)
from vav.modules.matchmaking_interactions.gateways import (
    EventGateway,
    OutboxEvent,
    RecommendationGateway,
)
from vav.modules.privacy.crypto import encrypt_private

#: Item states a member may still act on. Anything else means the card they
#: are looking at is stale.
ACTIONABLE_ITEM_STATUSES = frozenset({"ready", "exposed", "viewed"})


async def _item_for_action(session: AsyncSession, *, item_id: UUID, viewer_user_id: UUID) -> Any:
    context = await RecommendationGateway(session).item_context(
        item_id, viewer_user_id=viewer_user_id
    )
    if context is None:
        # Not found and not-yours are the same answer on purpose: probing item
        # identifiers must not reveal whether one exists for somebody else.
        raise VavError(
            "RECOMMENDATION_ITEM_NOT_FOUND",
            "That recommendation is not available.",
            status_code=404,
        )
    if context.status not in ACTIONABLE_ITEM_STATUSES:
        raise VavError(
            "RECOMMENDATION_ITEM_NOT_ACTIONABLE",
            "That recommendation can no longer be acted on.",
            status_code=409,
        )
    if context.expires_at is not None and context.expires_at <= service.now():
        raise VavError(
            "RECOMMENDATION_ITEM_EXPIRED",
            "That recommendation has expired.",
            status_code=409,
        )
    return context


async def create_like(
    session: AsyncSession,
    *,
    viewer_user_id: UUID,
    recommendation_item_id: UUID,
    idempotency_key: str,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Record interest and detect a mutual match in one locked transaction.

    The return value tells the member either ``one_sided`` or ``mutual_match``
    and nothing else — in particular never how long the other member has been
    waiting, or whether they had already liked first.
    """
    service.enabled()
    context = await _item_for_action(
        session, item_id=recommendation_item_id, viewer_user_id=viewer_user_id
    )
    target_user_id = context.recommended_user_id
    service.source_enabled(InteractionSource.RECOMMENDATION)

    eligibility = await service.check_interaction_allowed(
        session, actor_user_id=viewer_user_id, target_user_id=target_user_id
    )
    eligibility.raise_for_member()

    pair = await service.ensure_pair(session, viewer_user_id, target_user_id)
    settings = get_settings()
    expires_at = service.now() + timedelta(days=settings.matchmaking_like_ttl_days)

    existing = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_likes WHERE actor_user_id=:actor "
                "AND target_user_id=:target AND status IN ('active','matched')"
            ),
            {"actor": viewer_user_id, "target": target_user_id},
        )
    ).mappings()
    current = existing.first()
    if current is not None:
        # Already expressed. Report the current pair state rather than
        # creating a second row the unique index would refuse anyway.
        match_row = await match_service.match_for_pair(session, pair["id"])
        return _like_result(dict(current), match_row)

    try:
        inserted = (
            await session.execute(
                text(
                    "INSERT INTO matchmaking_likes "
                    "(pair_id,actor_user_id,target_user_id,source,recommendation_item_id,"
                    "status,idempotency_key,expires_at) VALUES "
                    "(:pair,:actor,:target,:source,:item,:status,:key,:expires) RETURNING *"
                ),
                {
                    "pair": pair["id"],
                    "actor": viewer_user_id,
                    "target": target_user_id,
                    "source": InteractionSource.RECOMMENDATION.value,
                    "item": recommendation_item_id,
                    "status": LikeStatus.ACTIVE.value,
                    "key": idempotency_key,
                    "expires": expires_at,
                },
            )
        ).mappings()
    except IntegrityError as exc:  # pragma: no cover - defended by the pair lock
        raise VavError(
            "LIKE_ALREADY_RECORDED",
            "Your choice was already recorded.",
            status_code=409,
        ) from exc
    like = dict(inserted.one())

    await RecommendationGateway(session).mark_item(recommendation_item_id, status="acted")
    await service.append_history(
        session,
        pair_id=pair["id"],
        entity_type="like",
        entity_id=like["id"],
        action="created",
        actor_user_id=viewer_user_id,
        to_status=LikeStatus.ACTIVE.value,
        safe_metadata={"source": InteractionSource.RECOMMENDATION.value},
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.like.created",
        subject_type="like",
        subject_id=like["id"],
        actor_id=viewer_user_id,
    )

    events = EventGateway(session)
    await events.publish(
        OutboxEvent(
            topic="matchmaking.like.created",
            aggregate_type="matchmaking_like",
            aggregate_id=like["id"],
            # The payload carries the pair, never a notification instruction:
            # a one-sided like has no recipient.
            payload={"pair_id": str(pair["id"]), "actor_user_id": str(viewer_user_id)},
        )
    )
    await _publish_recommendation_feedback(
        session,
        context=context,
        viewer_user_id=viewer_user_id,
        feedback_type="liked",
    )

    match_row = await match_service.detect_mutual_match(
        session,
        pair=pair,
        actor_user_id=viewer_user_id,
        target_user_id=target_user_id,
        actor_like=like,
        source=InteractionSource.RECOMMENDATION,
        request_id=request_id,
    )
    if match_row is not None:
        refreshed = (
            await session.execute(
                text("SELECT * FROM matchmaking_likes WHERE id=:id"), {"id": like["id"]}
            )
        ).mappings()
        like = dict(refreshed.one())
        await _publish_recommendation_feedback(
            session,
            context=context,
            viewer_user_id=viewer_user_id,
            feedback_type="mutual_matched",
        )
    return _like_result(like, match_row)


def _like_result(like: dict[str, Any], match_row: dict[str, Any] | None) -> dict[str, Any]:
    matched = match_row is not None and str(match_row["status"]) not in {
        "invalidated",
        "safety_frozen",
    }
    return {
        "like_id": str(like["id"]),
        "outcome": "mutual_match" if matched else "one_sided",
        "mutual_match_id": str(match_row["id"]) if matched and match_row else None,
        "recorded_at": like["created_at"],
    }


async def _publish_recommendation_feedback(
    session: AsyncSession,
    *,
    context: Any,
    viewer_user_id: UUID,
    feedback_type: str,
    reason_code: str | None = None,
) -> None:
    """Tell Batch 14 what happened, with the identifiers it needs to learn."""
    await EventGateway(session).publish(
        OutboxEvent(
            topic=f"recommendation.feedback.{feedback_type}",
            aggregate_type="recommendation_item",
            aggregate_id=context.item_id,
            payload={
                "recommendation_item_id": str(context.item_id),
                "candidate_pair_id": str(context.candidate_pair_id)
                if context.candidate_pair_id
                else None,
                "batch_id": str(context.batch_id) if context.batch_id else None,
                "strategy_version": context.strategy_version,
                "viewer_user_id": str(viewer_user_id),
                "feedback_type": feedback_type,
                "reason_code": reason_code,
                "source_module": "matchmaking_interactions",
            },
        )
    )


async def create_skip(
    session: AsyncSession,
    *,
    viewer_user_id: UUID,
    recommendation_item_id: UUID,
    skip_type: str,
    reason_code: str | None,
    reason_details: str | None,
    idempotency_key: str,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Record a skip and start a cooldown.

    A skip is a scheduling signal. It does not notify anyone, does not become a
    block, and does not turn into a hidden hard preference — the reason is
    encrypted and only the member and the recommendation engine ever see it.
    """
    service.enabled()
    try:
        typed = SkipType(skip_type)
    except ValueError as exc:
        raise VavError(
            "SKIP_TYPE_INVALID", "That skip type is not supported.", status_code=422
        ) from exc
    if reason_code is not None and reason_code not in SKIP_REASON_CODES:
        raise VavError("SKIP_REASON_INVALID", "That skip reason is not supported.", status_code=422)

    context = await _item_for_action(
        session, item_id=recommendation_item_id, viewer_user_id=viewer_user_id
    )
    target_user_id = context.recommended_user_id

    # A skip is allowed even when the other side has become ineligible: the
    # member is dismissing a card, and refusing that would be confusing.
    pair = await service.ensure_pair(session, viewer_user_id, target_user_id)
    settings = get_settings()
    moment = service.now()
    cooldown = skip_cooldown_until(
        typed,
        now=moment,
        not_now_days=settings.matchmaking_skip_not_now_cooldown_days,
        not_interested_days=settings.matchmaking_skip_not_interested_cooldown_days,
    )
    undo_until = (
        moment + timedelta(seconds=settings.matchmaking_skip_undo_window_seconds)
        if settings.matchmaking_allow_skip_undo
        else None
    )

    existing = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_skips WHERE actor_user_id=:actor "
                "AND target_user_id=:target AND status='active'"
            ),
            {"actor": viewer_user_id, "target": target_user_id},
        )
    ).mappings()
    current = existing.first()
    if current is not None:
        return _skip_result(dict(current))

    inserted = (
        await session.execute(
            text(
                "INSERT INTO matchmaking_skips "
                "(pair_id,actor_user_id,target_user_id,recommendation_item_id,skip_type,"
                "reason_code,reason_details_encrypted,status,cooldown_until,"
                "undo_available_until,idempotency_key) VALUES "
                "(:pair,:actor,:target,:item,:type,:reason,:details,:status,:cooldown,"
                ":undo,:key) RETURNING *"
            ),
            {
                "pair": pair["id"],
                "actor": viewer_user_id,
                "target": target_user_id,
                "item": recommendation_item_id,
                "type": typed.value,
                "reason": reason_code,
                "details": encrypt_private(reason_details) if reason_details else None,
                "status": SkipStatus.ACTIVE.value,
                "cooldown": cooldown,
                "undo": undo_until,
                "key": idempotency_key,
            },
        )
    ).mappings()
    skip = dict(inserted.one())

    await RecommendationGateway(session).mark_item(recommendation_item_id, status="skipped")
    low, high = canonical_pair(viewer_user_id, target_user_id)
    await RecommendationGateway(session).exclude_pair(
        user_low_id=low,
        user_high_id=high,
        exclusion_type=CooldownType.SKIP.value,
        reason_code=typed.value,
        expires_at=cooldown,
    )
    await service.append_history(
        session,
        pair_id=pair["id"],
        entity_type="skip",
        entity_id=skip["id"],
        action="created",
        actor_user_id=viewer_user_id,
        to_status=SkipStatus.ACTIVE.value,
        # The type is a scheduling input; the reason code and free text are not
        # recorded here.
        safe_metadata={"skip_type": typed.value},
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.skip.created",
        subject_type="skip",
        subject_id=skip["id"],
        actor_id=viewer_user_id,
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.skip.created",
            aggregate_type="matchmaking_skip",
            aggregate_id=skip["id"],
            payload={"pair_id": str(pair["id"]), "actor_user_id": str(viewer_user_id)},
        )
    )
    await _publish_recommendation_feedback(
        session,
        context=context,
        viewer_user_id=viewer_user_id,
        feedback_type="skipped",
        reason_code=reason_code,
    )
    return _skip_result(skip)


def _skip_result(skip: dict[str, Any]) -> dict[str, Any]:
    return {
        "skip_id": str(skip["id"]),
        "skip_type": skip["skip_type"],
        "cooldown_until": skip["cooldown_until"],
        "undo_available_until": skip["undo_available_until"],
    }


async def withdraw_like(
    session: AsyncSession,
    *,
    viewer_user_id: UUID,
    like_id: UUID,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Withdraw an unmatched like.

    Before a match this is silent, because the target never knew. After a
    match the like itself is not removed — the member is redirected to closing
    the match, which is the decision the other member actually shares.
    """
    service.enabled()
    row = (
        await session.execute(
            text("SELECT * FROM matchmaking_likes WHERE id=:id AND actor_user_id=:actor"),
            {"id": like_id, "actor": viewer_user_id},
        )
    ).mappings()
    found = row.first()
    if found is None:
        raise VavError("LIKE_NOT_FOUND", "That choice was not found.", status_code=404)
    like = dict(found)

    if str(like["status"]) == LikeStatus.MATCHED.value:
        raise VavError(
            "LIKE_ALREADY_MATCHED",
            "This choice is part of a mutual match; close the match instead.",
            status_code=409,
            details=[{"action": "close_mutual_match"}],
        )
    if str(like["status"]) != LikeStatus.ACTIVE.value:
        raise VavError(
            "LIKE_NOT_ACTIVE", "That choice can no longer be withdrawn.", status_code=409
        )

    await service.lock_pair(session, like["pair_id"])
    await session.execute(
        text(
            "UPDATE matchmaking_likes SET status=:status, withdrawn_at=now() "
            "WHERE id=:id AND status='active'"
        ),
        {"id": like_id, "status": LikeStatus.WITHDRAWN.value},
    )
    await service.append_history(
        session,
        pair_id=like["pair_id"],
        entity_type="like",
        entity_id=like_id,
        action="withdrawn",
        actor_user_id=viewer_user_id,
        from_status=LikeStatus.ACTIVE.value,
        to_status=LikeStatus.WITHDRAWN.value,
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.like.withdrawn",
        subject_type="like",
        subject_id=like_id,
        actor_id=viewer_user_id,
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.like.withdrawn",
            aggregate_type="matchmaking_like",
            aggregate_id=like_id,
            payload={"pair_id": str(like["pair_id"]), "actor_user_id": str(viewer_user_id)},
        )
    )
    if like["recommendation_item_id"] is not None:
        context = await RecommendationGateway(session).item_context(
            like["recommendation_item_id"], viewer_user_id=viewer_user_id
        )
        if context is not None:
            await _publish_recommendation_feedback(
                session,
                context=context,
                viewer_user_id=viewer_user_id,
                feedback_type="withdrawn",
            )
    return {"like_id": str(like_id), "status": LikeStatus.WITHDRAWN.value}


async def withdraw_skip(
    session: AsyncSession,
    *,
    viewer_user_id: UUID,
    skip_id: UUID,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Undo a skip and release its cooldown."""
    service.enabled()
    if not get_settings().matchmaking_allow_skip_undo:
        raise VavError("SKIP_UNDO_DISABLED", "Undoing a skip is not available.", status_code=403)
    row = (
        await session.execute(
            text("SELECT * FROM matchmaking_skips WHERE id=:id AND actor_user_id=:actor"),
            {"id": skip_id, "actor": viewer_user_id},
        )
    ).mappings()
    found = row.first()
    if found is None:
        raise VavError("SKIP_NOT_FOUND", "That skip was not found.", status_code=404)
    skip = dict(found)
    if str(skip["status"]) != SkipStatus.ACTIVE.value:
        raise VavError("SKIP_NOT_ACTIVE", "That skip can no longer be undone.", status_code=409)

    await session.execute(
        text(
            "UPDATE matchmaking_skips SET status=:status, withdrawn_at=now() "
            "WHERE id=:id AND status='active'"
        ),
        {"id": skip_id, "status": SkipStatus.WITHDRAWN.value},
    )
    low, high = canonical_pair(viewer_user_id, skip["target_user_id"])
    await RecommendationGateway(session).release_exclusion(
        user_low_id=low, user_high_id=high, exclusion_type=CooldownType.SKIP.value
    )
    await service.append_history(
        session,
        pair_id=skip["pair_id"],
        entity_type="skip",
        entity_id=skip_id,
        action="withdrawn",
        actor_user_id=viewer_user_id,
        from_status=SkipStatus.ACTIVE.value,
        to_status=SkipStatus.WITHDRAWN.value,
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.skip.withdrawn",
        subject_type="skip",
        subject_id=skip_id,
        actor_id=viewer_user_id,
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.skip.withdrawn",
            aggregate_type="matchmaking_skip",
            aggregate_id=skip_id,
            payload={"pair_id": str(skip["pair_id"]), "actor_user_id": str(viewer_user_id)},
        )
    )
    return {"skip_id": str(skip_id), "status": SkipStatus.WITHDRAWN.value}


async def outgoing_likes(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """A member's own outgoing choices.

    There is deliberately no incoming equivalent anywhere in this module.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, target_user_id, status, source, created_at, matched_at, withdrawn_at "
                "FROM matchmaking_likes WHERE actor_user_id=:user "
                "ORDER BY created_at DESC LIMIT 200"
            ),
            {"user": user_id},
        )
    ).mappings()
    return [
        {
            "like_id": str(row["id"]),
            "status": row["status"],
            "source": row["source"],
            "created_at": row["created_at"],
            "matched_at": row["matched_at"],
            "withdrawn_at": row["withdrawn_at"],
        }
        for row in rows
    ]


async def own_skips(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, skip_type, reason_code, status, cooldown_until, "
                "undo_available_until, created_at FROM matchmaking_skips "
                "WHERE actor_user_id=:user ORDER BY created_at DESC LIMIT 200"
            ),
            {"user": user_id},
        )
    ).mappings()
    return [
        {
            "skip_id": str(row["id"]),
            "skip_type": row["skip_type"],
            "reason_code": row["reason_code"],
            "status": row["status"],
            "cooldown_until": row["cooldown_until"],
            "undo_available_until": row["undo_available_until"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
