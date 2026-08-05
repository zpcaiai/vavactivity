"""Shared interaction primitives: pairs, locking, history, audit, eligibility.

Every two-person write in this module goes through the same pair lock, so the
concurrency rules are stated once instead of being re-derived — and getting
them wrong — in five different services.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.matchmaking_interactions.domain import (
    MEMBER_SAFE_UNAVAILABLE_STATE,
    InteractionSource,
    PairStatus,
    canonical_pair,
)
from vav.modules.matchmaking_interactions.gateways import (
    InteractionDecision,
    ModerationGateway,
    PrivacyGateway,
    ProfileGateway,
    RelationshipGateway,
)


def enabled() -> None:
    if not get_settings().matchmaking_interactions_enabled:
        raise VavError(
            "MATCHMAKING_INTERACTIONS_DISABLED",
            "Matchmaking interactions are not enabled.",
            status_code=503,
        )


def now() -> datetime:
    return datetime.now(UTC)


def jsonb(value: Any) -> Any:
    """Postgres jsonb comes back as a dict already; a string means raw text."""
    if isinstance(value, str):
        return json.loads(value)
    return value


# --------------------------------------------------------------------------
# Pairs
# --------------------------------------------------------------------------


async def ensure_pair(session: AsyncSession, user_a: UUID, user_b: UUID) -> dict[str, Any]:
    """Create the canonical pair if needed and lock it for this transaction.

    The insert is unconditional and conflict-tolerant so two simultaneous
    first-time likes cannot both decide the row is missing; the following
    ``FOR UPDATE`` is what serialises everything that comes after.
    """
    low, high = canonical_pair(user_a, user_b)
    await session.execute(
        text(
            "INSERT INTO matchmaking_pairs (user_low_id,user_high_id,status) "
            "VALUES (:low,:high,:status) ON CONFLICT (user_low_id,user_high_id) DO NOTHING"
        ),
        {"low": low, "high": high, "status": PairStatus.INTERACTING.value},
    )
    row = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_pairs WHERE user_low_id=:low AND user_high_id=:high "
                "FOR UPDATE"
            ),
            {"low": low, "high": high},
        )
    ).mappings()
    pair = row.first()
    if pair is None:  # pragma: no cover - the insert above guarantees a row
        raise VavError("PAIR_UNAVAILABLE", "The interaction pair is unavailable.", status_code=409)
    return dict(pair)


async def lock_pair(session: AsyncSession, pair_id: UUID) -> dict[str, Any]:
    row = (
        await session.execute(
            text("SELECT * FROM matchmaking_pairs WHERE id=:id FOR UPDATE"),
            {"id": pair_id},
        )
    ).mappings()
    pair = row.first()
    if pair is None:
        raise VavError("PAIR_NOT_FOUND", "The interaction pair was not found.", status_code=404)
    return dict(pair)


async def touch_pair(
    session: AsyncSession,
    pair_id: UUID,
    *,
    status: PairStatus | None = None,
    active_mutual_match_id: UUID | None = None,
    bump_restriction: bool = False,
) -> None:
    """Advance the pair and its versions.

    ``pair_version`` and ``restriction_version`` are part of every cache key,
    so bumping them here is what stops a stale cached view from outliving a
    block or a withdrawal.
    """
    await session.execute(
        text(
            "UPDATE matchmaking_pairs SET "
            "status=COALESCE(:status,status), "
            "active_mutual_match_id=COALESCE(:match_id,active_mutual_match_id), "
            "pair_version=pair_version+1, "
            "restriction_version=restriction_version+CASE WHEN :bump THEN 1 ELSE 0 END, "
            "updated_at=now() WHERE id=:id"
        ),
        {
            "id": pair_id,
            "status": status.value if status is not None else None,
            "match_id": active_mutual_match_id,
            "bump": bump_restriction,
        },
    )


async def clear_active_match(session: AsyncSession, pair_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE matchmaking_pairs SET active_mutual_match_id=NULL, pair_version=pair_version+1, "
            "updated_at=now() WHERE id=:id"
        ),
        {"id": pair_id},
    )


# --------------------------------------------------------------------------
# History and audit
# --------------------------------------------------------------------------


async def append_history(
    session: AsyncSession,
    *,
    pair_id: UUID,
    entity_type: str,
    entity_id: UUID | None,
    action: str,
    actor_user_id: UUID | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    reason_code: str | None = None,
    safe_metadata: dict[str, Any] | None = None,
    request_id: UUID | None = None,
) -> None:
    """Append one transition.

    ``safe_metadata`` is exactly that: status, counts and identifiers. A skip
    reason, an invitation body or a contact value never goes in here, because a
    timeline that leaks is worse than no timeline.
    """
    await session.execute(
        text(
            "INSERT INTO matchmaking_interaction_history "
            "(pair_id,actor_user_id,entity_type,entity_id,action,from_status,to_status,"
            "reason_code,safe_metadata,request_id) VALUES "
            "(:pair,:actor,:entity_type,:entity_id,:action,:from_status,:to_status,"
            ":reason,CAST(:metadata AS jsonb),:request_id)"
        ),
        {
            "pair": pair_id,
            "actor": actor_user_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "reason": reason_code,
            "metadata": json.dumps(safe_metadata or {}, default=str),
            "request_id": request_id,
        },
    )


async def audit(
    session: AsyncSession,
    *,
    event_type: str,
    subject_type: str,
    subject_id: UUID | None,
    actor_id: UUID | None = None,
    purpose: str | None = None,
    reason: str | None = None,
    safe_context: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO matchmaking_interaction_audit_events "
            "(event_type,actor_id,subject_type,subject_id,purpose,reason,safe_context) "
            "VALUES (:event_type,:actor,:subject_type,:subject_id,:purpose,:reason,"
            "CAST(:context AS jsonb))"
        ),
        {
            "event_type": event_type,
            "actor": actor_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "purpose": purpose,
            "reason": reason,
            "context": json.dumps(safe_context or {}, default=str),
        },
    )


async def sensitive_access(
    session: AsyncSession,
    *,
    actor_user_id: UUID,
    subject_user_id: UUID,
    asset_code: str,
    purpose: str,
    permission_code: str,
    result: str = "allowed",
    request_id: UUID | None = None,
) -> None:
    """Record a privileged read against the platform-wide sensitive log."""
    await session.execute(
        text(
            "INSERT INTO privacy_sensitive_access_events "
            "(actor_user_id,subject_user_id,module_code,asset_code,access_type,purpose,"
            "permission_code,request_id,result) VALUES "
            "(:actor,:subject,'matchmaking_interactions',:asset,'read',:purpose,:permission,"
            ":request_id,:result)"
        ),
        {
            "actor": actor_user_id,
            "subject": subject_user_id,
            "asset": asset_code,
            "purpose": purpose,
            "permission": permission_code,
            "request_id": request_id,
            "result": result,
        },
    )


# --------------------------------------------------------------------------
# Eligibility
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EligibilityResult:
    allowed: bool
    reason_code: str | None

    def raise_for_member(self) -> None:
        """Refuse without telling the member which rule fired.

        A precise reason here would leak the other member's profile state, a
        block, or an open report. One neutral code is the whole point.
        """
        if not self.allowed:
            raise VavError(
                "INTERACTION_NOT_AVAILABLE",
                "This introduction is no longer available.",
                status_code=409,
                details=[{"state": MEMBER_SAFE_UNAVAILABLE_STATE}],
            )


async def check_interaction_allowed(
    session: AsyncSession,
    *,
    actor_user_id: UUID,
    target_user_id: UUID,
    require_target_profile: bool = True,
    allow_active_relationship: bool = False,
) -> EligibilityResult:
    """The recheck every write and every display runs.

    A snapshot taken when a batch was generated is not evidence about now, so
    profile, privacy, safety and relationship state are re-read every time
    rather than trusted from the card the member is looking at.
    """
    if actor_user_id == target_user_id:
        return EligibilityResult(False, "self_interaction")

    profile_gateway = ProfileGateway(session)
    actor_profile = await profile_gateway.interaction_status(actor_user_id)
    if not actor_profile.allowed:
        return EligibilityResult(False, actor_profile.reason_code)
    if require_target_profile:
        target_profile = await profile_gateway.interaction_status(target_user_id)
        if not target_profile.allowed:
            return EligibilityResult(False, target_profile.reason_code)

    privacy = PrivacyGateway(session)
    if await privacy.erasure_in_progress(actor_user_id):
        return EligibilityResult(False, "erasure_started")
    if await privacy.erasure_in_progress(target_user_id):
        return EligibilityResult(False, "erasure_started")

    moderation = await ModerationGateway(session).evaluate_pair(
        actor_user_id=actor_user_id, target_user_id=target_user_id
    )
    if not moderation.allowed:
        return EligibilityResult(False, moderation.reason_code)

    if not allow_active_relationship and await RelationshipGateway(session).has_active_relationship(
        user_a_id=actor_user_id, user_b_id=target_user_id
    ):
        return EligibilityResult(False, "relationship_started")

    return EligibilityResult(True, None)


def decision_to_result(decision: InteractionDecision) -> EligibilityResult:
    return EligibilityResult(decision.allowed, decision.reason_code)


def source_enabled(source: InteractionSource) -> None:
    settings = get_settings()
    if (
        source is InteractionSource.PROFILE_DETAIL
        and not settings.matchmaking_allow_direct_profile_like
    ):
        raise VavError(
            "DIRECT_PROFILE_LIKE_DISABLED",
            "Liking a profile outside your recommendations is not available.",
            status_code=403,
        )
