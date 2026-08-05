"""One place where external signals invalidate interactions.

Profile pause, account suspension, erasure, block, restriction and relationship
start all arrive here. Keeping the fan-in in one service is what stops the six
rules from drifting apart and leaving one path that forgets to revoke a grant.
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.modules.matchmaking_interactions import contact_exchange, service
from vav.modules.matchmaking_interactions.domain import (
    INVALIDATION_REASON_CODES,
    InvitationStatus,
    LikeStatus,
    MutualMatchStatus,
    PairStatus,
    canonical_pair,
)
from vav.modules.matchmaking_interactions.gateways import EventGateway, OutboxEvent


@dataclass(frozen=True)
class InvalidationSummary:
    likes: int = 0
    matches: int = 0
    invitations: int = 0
    contact_exchanges: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "likes": self.likes,
            "matches": self.matches,
            "invitations": self.invitations,
            "contact_exchanges": self.contact_exchanges,
        }


#: A block freezes rather than closes: an investigation needs the pair to stay
#: reconstructable, and closing would tell the blocked member something.
FREEZE_REASONS = frozenset({"block_created", "restriction_created", "high_risk_report"})


async def invalidate_pair(
    session: AsyncSession,
    *,
    user_a_id: UUID,
    user_b_id: UUID,
    reason_code: str,
    actor_user_id: UUID | None = None,
) -> InvalidationSummary:
    """Invalidate everything open between two members."""
    if reason_code not in INVALIDATION_REASON_CODES:
        reason_code = "admin_action"
    low, high = canonical_pair(user_a_id, user_b_id)
    rows = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_pairs WHERE user_low_id=:low AND user_high_id=:high "
                "FOR UPDATE"
            ),
            {"low": low, "high": high},
        )
    ).mappings()
    pair = rows.first()
    if pair is None:
        return InvalidationSummary()
    return await _invalidate(
        session, pair=dict(pair), reason_code=reason_code, actor_user_id=actor_user_id
    )


async def invalidate_for_user(
    session: AsyncSession, *, user_id: UUID, reason_code: str
) -> InvalidationSummary:
    """Invalidate every open interaction a member is part of."""
    if reason_code not in INVALIDATION_REASON_CODES:
        reason_code = "admin_action"
    rows = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_pairs WHERE user_low_id=:user OR user_high_id=:user "
                "FOR UPDATE"
            ),
            {"user": user_id},
        )
    ).mappings()
    totals = InvalidationSummary()
    for row in rows:
        summary = await _invalidate(session, pair=dict(row), reason_code=reason_code)
        totals = InvalidationSummary(
            likes=totals.likes + summary.likes,
            matches=totals.matches + summary.matches,
            invitations=totals.invitations + summary.invitations,
            contact_exchanges=totals.contact_exchanges + summary.contact_exchanges,
        )
    return totals


async def _invalidate(
    session: AsyncSession,
    *,
    pair: dict[str, Any],
    reason_code: str,
    actor_user_id: UUID | None = None,
) -> InvalidationSummary:
    pair_id = pair["id"]
    freeze = reason_code in FREEZE_REASONS

    likes = (
        await session.execute(
            text(
                "UPDATE matchmaking_likes SET status=:status, invalidated_at=now(), "
                "invalidation_reason_code=:reason WHERE pair_id=:pair AND status='active' "
                "RETURNING id"
            ),
            {"pair": pair_id, "status": LikeStatus.INVALIDATED.value, "reason": reason_code},
        )
    ).mappings()
    like_count = len(list(likes))

    invitations = (
        await session.execute(
            text(
                "UPDATE matchmaking_introduction_invitations SET status=:status, "
                "invalidated_at=now(), internal_invalidation_reason=:reason, "
                "invitation_version=invitation_version+1, updated_at=now() "
                "WHERE pair_id=:pair AND status='pending' RETURNING id"
            ),
            {
                "pair": pair_id,
                "status": InvitationStatus.INVALIDATED.value,
                "reason": reason_code,
            },
        )
    ).mappings()
    invitation_ids = [row["id"] for row in invitations]

    match_status = MutualMatchStatus.SAFETY_FROZEN if freeze else MutualMatchStatus.INVALIDATED
    matches = (
        await session.execute(
            text(
                "UPDATE matchmaking_mutual_matches SET status=:status, "
                "invalidated_at=CASE WHEN :freeze THEN invalidated_at ELSE now() END, "
                "closure_reason_code=:reason, match_version=match_version+1, updated_at=now() "
                "WHERE pair_id=:pair AND status NOT IN "
                "('closed','invalidated','safety_frozen') RETURNING id"
            ),
            {
                "pair": pair_id,
                "status": match_status.value,
                "reason": reason_code,
                "freeze": freeze,
            },
        )
    ).mappings()
    match_ids = [row["id"] for row in matches]

    exchange_count = 0
    if freeze or reason_code in {"erasure_started", "account_suspended", "contact_changed"}:
        counted = (
            await session.execute(
                text(
                    "SELECT count(*) FROM matchmaking_contact_exchange_requests "
                    "WHERE pair_id=:pair AND status<>'invalidated'"
                ),
                {"pair": pair_id},
            )
        ).scalar_one()
        exchange_count = int(counted or 0)
        await contact_exchange.revoke_for_pair(session, pair_id=pair_id, reason=reason_code)

    await service.touch_pair(
        session,
        pair_id,
        status=PairStatus.RESTRICTED if freeze else None,
        bump_restriction=True,
    )
    await service.append_history(
        session,
        pair_id=pair_id,
        entity_type="pair",
        entity_id=pair_id,
        action="invalidated",
        actor_user_id=actor_user_id,
        to_status=PairStatus.RESTRICTED.value if freeze else None,
        reason_code=reason_code,
        safe_metadata={
            "likes": like_count,
            "matches": len(match_ids),
            "invitations": len(invitation_ids),
            "contact_exchanges": exchange_count,
        },
    )
    await service.audit(
        session,
        event_type="matchmaking.match.safety_frozen" if freeze else "matchmaking.match.invalidated",
        subject_type="pair",
        subject_id=pair_id,
        actor_id=actor_user_id,
        reason=reason_code,
    )

    events = EventGateway(session)
    for match_id in match_ids:
        await events.publish(
            OutboxEvent(
                topic="matchmaking.mutual_match.invalidated",
                aggregate_type="matchmaking_mutual_match",
                aggregate_id=match_id,
                # Members are told the introduction ended. The internal cause
                # stays behind the sensitive-read permission.
                payload={"mutual_match_id": str(match_id), "disclosure": "generic_status_only"},
            )
        )
    for invitation_id in invitation_ids:
        await events.publish(
            OutboxEvent(
                topic="matchmaking.introduction.invalidated",
                aggregate_type="matchmaking_invitation",
                aggregate_id=invitation_id,
                payload={"invitation_id": str(invitation_id), "disclosure": "generic_status_only"},
            )
        )
    return InvalidationSummary(
        likes=like_count,
        matches=len(match_ids),
        invitations=len(invitation_ids),
        contact_exchanges=exchange_count,
    )


async def suspend_stale_contact_grants(session: AsyncSession, *, user_id: UUID) -> int:
    """Suspend grants whose consented values no longer match.

    Called when a member changes a verified contact point. The old consent is
    not widened to cover a new value; it is suspended until its owner confirms
    again.
    """
    rows = (
        await session.execute(
            text(
                "UPDATE matchmaking_contact_exchange_grants SET status='suspended', "
                "suspended_at=now() WHERE owner_user_id=:user AND status='active' RETURNING id"
            ),
            {"user": user_id},
        )
    ).mappings()
    grant_ids = [row["id"] for row in rows]
    if grant_ids:
        await session.execute(
            text(
                "UPDATE matchmaking_contact_reveal_tokens SET status='invalidated', "
                "invalidated_at=now() WHERE status='issued' AND grant_id = ANY(:ids)"
            ),
            {"ids": grant_ids},
        )
        await service.audit(
            session,
            event_type="matchmaking.contact_exchange.revoked",
            subject_type="contact_grant",
            subject_id=None,
            reason="contact_changed",
            safe_context={"suspended": len(grant_ids)},
        )
    return len(grant_ids)


#: Inbox routing for the events other modules publish.
INBOX_REASONS: dict[str, str] = {
    "dating_profile.paused": "profile_paused",
    "dating_profile.suspended": "profile_suspended",
    "dating_profile.archived": "profile_archived",
    "dating_profile.privacy_updated": "privacy_updated",
    "user.account.suspended": "account_suspended",
    "privacy.erasure.started": "erasure_started",
    "moderation.block.created": "block_created",
    "moderation.restriction.created": "restriction_created",
    "moderation.report.high_risk": "high_risk_report",
    "relationship.journey.started": "relationship_started",
}


async def handle_inbox_event(
    session: AsyncSession,
    *,
    source_module: str,
    source_event_id: UUID,
    event_type: str,
    user_id: UUID | None = None,
    other_user_id: UUID | None = None,
) -> InvalidationSummary | None:
    """Process one external event exactly once."""
    claimed = (
        await session.execute(
            text(
                "INSERT INTO matchmaking_interaction_inbox_events "
                "(source_module,source_event_id,event_type) VALUES (:module,:event,:type) "
                "ON CONFLICT (source_module,source_event_id) DO NOTHING RETURNING id"
            ),
            {"module": source_module, "event": source_event_id, "type": event_type},
        )
    ).mappings()
    if claimed.first() is None:
        return None

    reason = INBOX_REASONS.get(event_type)
    if reason is None or user_id is None:
        await session.execute(
            text(
                "UPDATE matchmaking_interaction_inbox_events SET status='failed', "
                "error_code='unsupported_event', processed_at=now() "
                "WHERE source_module=:module AND source_event_id=:event"
            ),
            {"module": source_module, "event": source_event_id},
        )
        return None

    if other_user_id is not None:
        summary = await invalidate_pair(
            session, user_a_id=user_id, user_b_id=other_user_id, reason_code=reason
        )
    else:
        summary = await invalidate_for_user(session, user_id=user_id, reason_code=reason)

    await session.execute(
        text(
            "UPDATE matchmaking_interaction_inbox_events SET status='processed', "
            "processed_at=now() WHERE source_module=:module AND source_event_id=:event"
        ),
        {"module": source_module, "event": source_event_id},
    )
    return summary
