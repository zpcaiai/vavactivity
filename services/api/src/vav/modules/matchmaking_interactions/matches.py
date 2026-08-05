"""Mutual-match detection, closure and the activity bridge.

This is the only genuinely contended path in the batch. Two members can press
the same button in the same millisecond, and the result must be one match, one
notification, and two likes that both read ``matched``.
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
from vav.modules.matchmaking_interactions import service
from vav.modules.matchmaking_interactions.domain import (
    CooldownType,
    InteractionSource,
    InvitationStatus,
    LikeStatus,
    MutualMatchStatus,
    PairStatus,
    canonical_pair,
    match_number,
)
from vav.modules.matchmaking_interactions.gateways import (
    ActivityGateway,
    EventGateway,
    OutboxEvent,
    RecommendationGateway,
)


async def match_for_pair(session: AsyncSession, pair_id: UUID) -> dict[str, Any] | None:
    rows = (
        await session.execute(
            text("SELECT * FROM matchmaking_mutual_matches WHERE pair_id=:pair"),
            {"pair": pair_id},
        )
    ).mappings()
    found = rows.first()
    return dict(found) if found is not None else None


async def detect_mutual_match(
    session: AsyncSession,
    *,
    pair: dict[str, Any],
    actor_user_id: UUID,
    target_user_id: UUID,
    actor_like: dict[str, Any],
    source: InteractionSource,
    request_id: UUID | None = None,
) -> dict[str, Any] | None:
    """Create the match if the reverse like is already there.

    The caller holds the pair lock. That is what makes the read of the reverse
    like trustworthy: without it, both transactions would see "no reverse like"
    and neither would create the match, or both would try.
    """
    settings = get_settings()
    if not settings.matchmaking_mutual_match_enabled:
        return None

    existing = await match_for_pair(session, pair["id"])
    if existing is not None:
        return existing

    reverse = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_likes WHERE actor_user_id=:actor "
                "AND target_user_id=:target AND status='active'"
            ),
            {"actor": target_user_id, "target": actor_user_id},
        )
    ).mappings()
    reverse_like = reverse.first()
    if reverse_like is None:
        return None

    # Both sides said yes; re-verify both sides before binding them together.
    eligibility = await service.check_interaction_allowed(
        session, actor_user_id=actor_user_id, target_user_id=target_user_id
    )
    if not eligibility.allowed:
        await _invalidate_like(
            session,
            like_id=actor_like["id"],
            pair_id=pair["id"],
            reason_code=eligibility.reason_code,
        )
        # The other member is told nothing: their like stays active and they
        # never learn that a match was almost created.
        eligibility.raise_for_member()

    low, high = canonical_pair(actor_user_id, target_user_id)
    low_to_high = actor_like if actor_user_id == low else dict(reverse_like)
    high_to_low = dict(reverse_like) if actor_user_id == low else actor_like

    try:
        inserted = (
            await session.execute(
                text(
                    "INSERT INTO matchmaking_mutual_matches "
                    "(match_number,pair_id,user_low_id,user_high_id,source,"
                    "low_to_high_like_id,high_to_low_like_id,status) VALUES "
                    "(:number,:pair,:low,:high,:source,:low_like,:high_like,:status) "
                    "ON CONFLICT (pair_id) DO NOTHING RETURNING *"
                ),
                {
                    "number": match_number(),
                    "pair": pair["id"],
                    "low": low,
                    "high": high,
                    "source": source.value,
                    "low_like": low_to_high["id"],
                    "high_like": high_to_low["id"],
                    "status": MutualMatchStatus.ACTIVE.value,
                },
            )
        ).mappings()
    except IntegrityError as exc:  # pragma: no cover - guarded by the pair lock
        raise VavError(
            "MUTUAL_MATCH_CONFLICT", "This match already exists.", status_code=409
        ) from exc
    created = inserted.first()
    if created is None:
        # Another transaction won. Its match is the one that counts, and it
        # already emitted the single notification.
        return await match_for_pair(session, pair["id"])
    match = dict(created)

    await session.execute(
        text(
            "UPDATE matchmaking_likes SET status=:status, matched_at=now() "
            "WHERE id IN (:low_like,:high_like)"
        ),
        {
            "status": LikeStatus.MATCHED.value,
            "low_like": low_to_high["id"],
            "high_like": high_to_low["id"],
        },
    )
    await service.touch_pair(
        session,
        pair["id"],
        status=PairStatus.MUTUAL_MATCHED,
        active_mutual_match_id=match["id"],
    )
    await _record_source(
        session,
        mutual_match_id=match["id"],
        source_type=source.value,
        source_reference_id=actor_like["id"],
    )
    await service.append_history(
        session,
        pair_id=pair["id"],
        entity_type="mutual_match",
        entity_id=match["id"],
        action="created",
        actor_user_id=actor_user_id,
        to_status=MutualMatchStatus.ACTIVE.value,
        safe_metadata={"source": source.value},
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.match.created",
        subject_type="mutual_match",
        subject_id=match["id"],
        actor_id=actor_user_id,
    )
    if settings.matchmaking_mutual_match_notification_enabled:
        # Exactly one event. Both members are recipients of that one event,
        # which is what makes the notification exactly-once rather than twice.
        await EventGateway(session).publish(
            OutboxEvent(
                topic="matchmaking.mutual_match.created",
                aggregate_type="matchmaking_mutual_match",
                aggregate_id=match["id"],
                payload={
                    "mutual_match_id": str(match["id"]),
                    "pair_id": str(pair["id"]),
                    "recipient_user_ids": [str(low), str(high)],
                    "source": source.value,
                },
            )
        )
    return match


async def _record_source(
    session: AsyncSession,
    *,
    mutual_match_id: UUID,
    source_type: str,
    source_reference_id: UUID,
) -> None:
    await session.execute(
        text(
            "INSERT INTO matchmaking_match_sources "
            "(mutual_match_id,source_type,source_reference_id) VALUES (:match,:type,:ref) "
            "ON CONFLICT (source_type,source_reference_id) DO NOTHING"
        ),
        {"match": mutual_match_id, "type": source_type, "ref": source_reference_id},
    )


async def _invalidate_like(
    session: AsyncSession, *, like_id: UUID, pair_id: UUID, reason_code: str | None
) -> None:
    await session.execute(
        text(
            "UPDATE matchmaking_likes SET status=:status, invalidated_at=now(), "
            "invalidation_reason_code=:reason WHERE id=:id"
        ),
        {"id": like_id, "status": LikeStatus.INVALIDATED.value, "reason": reason_code},
    )
    await service.append_history(
        session,
        pair_id=pair_id,
        entity_type="like",
        entity_id=like_id,
        action="invalidated",
        to_status=LikeStatus.INVALIDATED.value,
        reason_code=reason_code,
    )


async def close_match(
    session: AsyncSession,
    *,
    user_id: UUID,
    match_id: UUID,
    reason_code: str | None = None,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Either member may close a match without the other's agreement."""
    service.enabled()
    match = await _member_match(session, user_id=user_id, match_id=match_id, lock=True)
    status = MutualMatchStatus(str(match["status"]))
    if status in {MutualMatchStatus.CLOSED, MutualMatchStatus.INVALIDATED}:
        return {"mutual_match_id": str(match_id), "status": match["status"]}
    if status is MutualMatchStatus.INTRODUCTION_ACCEPTED:
        raise VavError(
            "RELATIONSHIP_ALREADY_STARTED",
            "This introduction has already started; ending it is handled in the relationship.",
            status_code=409,
        )

    await session.execute(
        text(
            "UPDATE matchmaking_introduction_invitations SET status=:status, "
            "cancelled_at=now(), invitation_version=invitation_version+1, updated_at=now() "
            "WHERE mutual_match_id=:match AND status='pending'"
        ),
        {"match": match_id, "status": InvitationStatus.CANCELLED.value},
    )
    await session.execute(
        text(
            "UPDATE matchmaking_mutual_matches SET status=:status, closed_at=now(), "
            "closure_reason_code=:reason, closed_by_user_id=:actor, "
            "match_version=match_version+1, updated_at=now() WHERE id=:id"
        ),
        {
            "id": match_id,
            "status": MutualMatchStatus.CLOSED.value,
            "reason": reason_code,
            "actor": user_id,
        },
    )
    await service.clear_active_match(session, match["pair_id"])
    await service.touch_pair(session, match["pair_id"], status=PairStatus.CLOSED)
    low, high = canonical_pair(match["user_low_id"], match["user_high_id"])
    await RecommendationGateway(session).exclude_pair(
        user_low_id=low,
        user_high_id=high,
        exclusion_type=CooldownType.MATCH_CLOSED.value,
        reason_code="match_closed",
        expires_at=service.now()
        + timedelta(days=get_settings().matchmaking_declined_pair_cooldown_days),
    )
    await service.append_history(
        session,
        pair_id=match["pair_id"],
        entity_type="mutual_match",
        entity_id=match_id,
        action="closed",
        actor_user_id=user_id,
        from_status=status.value,
        to_status=MutualMatchStatus.CLOSED.value,
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.match.closed",
        subject_type="mutual_match",
        subject_id=match_id,
        actor_id=user_id,
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.mutual_match.closed",
            aggregate_type="matchmaking_mutual_match",
            aggregate_id=match_id,
            # The other member is told the introduction ended, never who ended
            # it or why.
            payload={
                "mutual_match_id": str(match_id),
                "recipient_user_ids": [str(low), str(high)],
            },
        )
    )
    return {"mutual_match_id": str(match_id), "status": MutualMatchStatus.CLOSED.value}


async def _member_match(
    session: AsyncSession, *, user_id: UUID, match_id: UUID, lock: bool = False
) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock else ""
    rows = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_mutual_matches WHERE id=:id "
                "AND (user_low_id=:user OR user_high_id=:user)" + suffix
            ),
            {"id": match_id, "user": user_id},
        )
    ).mappings()
    match = rows.first()
    if match is None:
        raise VavError("MUTUAL_MATCH_NOT_FOUND", "That match was not found.", status_code=404)
    return dict(match)


async def member_match(session: AsyncSession, *, user_id: UUID, match_id: UUID) -> dict[str, Any]:
    return await _member_match(session, user_id=user_id, match_id=match_id)


async def list_matches(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT m.*, "
                "(SELECT id FROM matchmaking_introduction_invitations i "
                "  WHERE i.mutual_match_id=m.id ORDER BY i.created_at DESC LIMIT 1) "
                "  AS invitation_id, "
                "(SELECT status FROM matchmaking_introduction_invitations i "
                "  WHERE i.mutual_match_id=m.id ORDER BY i.created_at DESC LIMIT 1) "
                "  AS invitation_status, "
                "(SELECT id FROM matchmaking_contact_exchange_requests c "
                "  WHERE c.mutual_match_id=m.id) AS contact_exchange_id, "
                "(SELECT status FROM matchmaking_contact_exchange_requests c "
                "  WHERE c.mutual_match_id=m.id) AS contact_exchange_status "
                "FROM matchmaking_mutual_matches m "
                "WHERE (m.user_low_id=:user OR m.user_high_id=:user) "
                "AND m.status NOT IN ('invalidated') "
                "ORDER BY m.matched_at DESC LIMIT 200"
            ),
            {"user": user_id},
        )
    ).mappings()
    return [dict(row) for row in rows]


def other_member(match: dict[str, Any], user_id: UUID) -> UUID:
    other: UUID = match["user_high_id"] if match["user_low_id"] == user_id else match["user_low_id"]
    return other


# --------------------------------------------------------------------------
# Activity bridge
# --------------------------------------------------------------------------


async def ingest_activity_mutual_choice(
    session: AsyncSession,
    *,
    source_event_id: UUID,
    activity_mutual_choice_id: UUID,
) -> dict[str, Any] | None:
    """Attach a post-event mutual choice to the unified interaction domain.

    A check-in is not a choice and a grouping is not a match: only a recorded
    mutual choice between two participants reaches here, and replaying the same
    event never produces a second match.
    """
    service.enabled()
    claimed = (
        await session.execute(
            text(
                "INSERT INTO matchmaking_interaction_inbox_events "
                "(source_module,source_event_id,event_type,payload) VALUES "
                "('activities',:event_id,'activity.mutual_choice.created',CAST(:payload AS jsonb)) "
                "ON CONFLICT (source_module,source_event_id) DO NOTHING RETURNING id"
            ),
            {
                "event_id": source_event_id,
                "payload": f'{{"activity_mutual_choice_id": "{activity_mutual_choice_id}"}}',
            },
        )
    ).mappings()
    if claimed.first() is None:
        # Already handled. Idempotent replay is a success, not an error.
        return None

    choice = await ActivityGateway(session).mutual_choice(activity_mutual_choice_id)
    if choice is None or str(choice["status"]) != "matched":
        await _fail_inbox(session, source_event_id, "activity_choice_not_matched")
        return None

    user_a, user_b = choice["user_a_id"], choice["user_b_id"]
    eligibility = await service.check_interaction_allowed(
        session, actor_user_id=user_a, target_user_id=user_b
    )
    if not eligibility.allowed:
        await _fail_inbox(session, source_event_id, eligibility.reason_code or "not_eligible")
        return None

    pair = await service.ensure_pair(session, user_a, user_b)
    existing = await match_for_pair(session, pair["id"])
    if existing is not None:
        # A recommendation match already exists: record the activity as an
        # additional source rather than creating a competing match.
        await _record_source(
            session,
            mutual_match_id=existing["id"],
            source_type=InteractionSource.ACTIVITY_POST_EVENT.value,
            source_reference_id=activity_mutual_choice_id,
        )
        await _complete_inbox(session, source_event_id)
        return existing

    low, high = canonical_pair(user_a, user_b)
    inserted = (
        await session.execute(
            text(
                "INSERT INTO matchmaking_mutual_matches "
                "(match_number,pair_id,user_low_id,user_high_id,source,"
                "activity_mutual_choice_id,status) VALUES "
                "(:number,:pair,:low,:high,:source,:choice,:status) "
                "ON CONFLICT (pair_id) DO NOTHING RETURNING *"
            ),
            {
                "number": match_number(),
                "pair": pair["id"],
                "low": low,
                "high": high,
                "source": InteractionSource.ACTIVITY_POST_EVENT.value,
                "choice": activity_mutual_choice_id,
                "status": MutualMatchStatus.ACTIVE.value,
            },
        )
    ).mappings()
    created = inserted.first()
    if created is None:
        await _complete_inbox(session, source_event_id)
        return await match_for_pair(session, pair["id"])
    match = dict(created)

    await service.touch_pair(
        session, pair["id"], status=PairStatus.MUTUAL_MATCHED, active_mutual_match_id=match["id"]
    )
    await _record_source(
        session,
        mutual_match_id=match["id"],
        source_type=InteractionSource.ACTIVITY_POST_EVENT.value,
        source_reference_id=activity_mutual_choice_id,
    )
    await service.append_history(
        session,
        pair_id=pair["id"],
        entity_type="mutual_match",
        entity_id=match["id"],
        action="created",
        to_status=MutualMatchStatus.ACTIVE.value,
        safe_metadata={"source": InteractionSource.ACTIVITY_POST_EVENT.value},
    )
    await service.audit(
        session,
        event_type="matchmaking.match.created",
        subject_type="mutual_match",
        subject_id=match["id"],
    )
    if get_settings().matchmaking_mutual_match_notification_enabled:
        await EventGateway(session).publish(
            OutboxEvent(
                topic="matchmaking.mutual_match.created",
                aggregate_type="matchmaking_mutual_match",
                aggregate_id=match["id"],
                payload={
                    "mutual_match_id": str(match["id"]),
                    "pair_id": str(pair["id"]),
                    "recipient_user_ids": [str(low), str(high)],
                    "source": InteractionSource.ACTIVITY_POST_EVENT.value,
                },
            )
        )
    await _complete_inbox(session, source_event_id)
    return match


async def _complete_inbox(session: AsyncSession, source_event_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE matchmaking_interaction_inbox_events SET status='processed', "
            "processed_at=now() WHERE source_module='activities' AND source_event_id=:id"
        ),
        {"id": source_event_id},
    )


async def _fail_inbox(session: AsyncSession, source_event_id: UUID, error_code: str) -> None:
    rows = (
        await session.execute(
            text(
                "UPDATE matchmaking_interaction_inbox_events SET status='failed', "
                "error_code=:code, attempts=attempts+1, processed_at=now() "
                "WHERE source_module='activities' AND source_event_id=:id RETURNING id, event_type"
            ),
            {"id": source_event_id, "code": error_code},
        )
    ).mappings()
    failed = rows.first()
    if failed is not None:
        await session.execute(
            text(
                "INSERT INTO matchmaking_interaction_dead_letters "
                "(inbox_event_id,event_type,error_code) VALUES (:inbox,:type,:code)"
            ),
            {"inbox": failed["id"], "type": failed["event_type"], "code": error_code},
        )
