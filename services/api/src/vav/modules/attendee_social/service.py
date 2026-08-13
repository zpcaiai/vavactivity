"""Transactional attendee-preview and follow-graph service (B14).

Design notes:

* All business rules live in :mod:`vav.modules.attendee_social.domain` so they
  are testable without a database; this layer only loads state, calls domain and
  persists.
* Consent is opt-in. The preview query joins consent rows but the *decision* is
  always made by the domain, so a missing row and an explicit refusal behave
  identically (DEC-002).
* ``like``, ``follow`` and ``want_to_meet`` are three tables. Nothing in this
  module reads one and writes another.
* Free-text member input (a withdrawal note, an intro line) is stored through
  :mod:`vav.modules.privacy.crypto` and never enters outbox payloads or logs.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.attendee_social.domain import (
    FOLLOWED_USER_REGISTERED_PREFERENCE_KEY,
    FOLLOWED_USER_REGISTERED_TOPIC,
    AttendeeRecord,
    AttendeeSocialRuleError,
    FollowAction,
    FollowState,
    PreviewConsentState,
    RelationKind,
    apply_consent_decision,
    assert_minimum_projection,
    build_followed_user_registered_payload,
    build_preview,
    decide_followed_user_registered,
    plan_follow,
    plan_unfollow,
    relation_semantics,
)
from vav.modules.privacy.crypto import decrypt_private, encrypt_private

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: AttendeeSocialRuleError, status_code: int = 422) -> VavError:
    """Translate a pure-domain violation into the platform error envelope.

    ``VavError.details`` is a list in this codebase, so the rule's structured
    context is wrapped rather than passed through as a mapping.
    """

    return VavError(
        error.code,
        error.message,
        status_code=status_code,
        details=[error.details] if error.details else None,
    )


def preview_enabled() -> None:
    if not get_settings().attendee_preview_enabled:
        raise VavError(
            "ATTENDEE_PREVIEW_DISABLED", "The attendee preview is not enabled.", status_code=503
        )


def follow_graph_enabled() -> None:
    if not get_settings().social_follow_enabled:
        raise VavError(
            "SOCIAL_FOLLOW_DISABLED", "The follow graph is not enabled.", status_code=503
        )


async def _publish(
    session: AsyncSession,
    topic: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,:aggregate_type,:id,CAST(:payload AS jsonb))"
        ),
        {
            "topic": topic,
            "aggregate_type": aggregate_type,
            "id": str(aggregate_id),
            "payload": _json(payload),
        },
    )


async def _audit(
    session: AsyncSession,
    *,
    subject_user_id: UUID | None,
    activity_id: UUID | None,
    actor_id: UUID | None,
    actor_kind: str,
    action: str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO attendee_social_audits "
            "(subject_user_id,activity_id,actor_id,actor_kind,action,reason,metadata) "
            "VALUES (:subject_user_id,:activity_id,:actor_id,:actor_kind,:action,:reason,CAST(:metadata AS jsonb))"
        ),
        {
            "subject_user_id": str(subject_user_id) if subject_user_id else None,
            "activity_id": str(activity_id) if activity_id else None,
            "actor_id": str(actor_id) if actor_id else None,
            "actor_kind": actor_kind,
            "action": action,
            "reason": reason,
            "metadata": _json(metadata or {}),
        },
    )


# ---------------------------------------------------------------------------
# ATT-001 attendee preview
# ---------------------------------------------------------------------------


async def _load_attendee_records(
    session: AsyncSession, activity_id: UUID
) -> list[AttendeeRecord]:
    """Load every registration for an activity with its consent state.

    ``LEFT JOIN`` on the consent table is deliberate: a registration with no
    consent row must still appear here so the domain can classify it as
    ``not_asked`` and exclude it. Filtering it out in SQL would hide the count
    of people who were never asked.
    """

    rows = (
        (
            await session.execute(
                text(
                    "SELECT r.user_id, r.id AS registration_id, r.status AS registration_status,"
                    " r.attendance_status,"
                    " CASE WHEN r.status='confirmed' THEN 'paid' ELSE 'unpaid' END AS payment_state,"
                    " COALESCE(c.consent_state, 'not_asked') AS consent_state,"
                    " c.intro_line_encrypted,"
                    " COALESCE(p.display_name, 'member-' || left(r.user_id::text, 8)) AS display_name,"
                    " p.avatar_media_id::text AS avatar_url,"
                    " (u.status <> 'active' OR u.deleted_at IS NOT NULL) AS is_suspended,"
                    " EXISTS (SELECT 1 FROM user_roles ur JOIN roles ro ON ro.id=ur.role_id"
                    "    WHERE ur.user_id=r.user_id AND ur.revoked_at IS NULL AND ro.is_system=true) AS is_staff"
                    " FROM activity_registrations r"
                    " LEFT JOIN attendee_preview_consents c"
                    "   ON c.registration_id=r.id"
                    " LEFT JOIN activity_participant_profiles p"
                    "   ON p.registration_id=r.id"
                    " LEFT JOIN users u ON u.id=r.user_id"
                    " WHERE r.activity_id=:activity_id"
                ),
                {"activity_id": str(activity_id)},
            )
        )
        .mappings()
        .all()
    )
    return [
        AttendeeRecord(
            user_id=UUID(str(row["user_id"])),
            registration_id=UUID(str(row["registration_id"])),
            registration_status=row["registration_status"],
            payment_state=row["payment_state"],
            consent_state=row["consent_state"],
            attendance_status=row["attendance_status"],
            is_staff=bool(row["is_staff"]),
            is_suspended=bool(row["is_suspended"]),
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            intro_line=(
                decrypt_private(row["intro_line_encrypted"])
                if row["intro_line_encrypted"]
                else None
            ),
        )
        for row in rows
    ]


async def get_attendee_preview(
    session: AsyncSession,
    *,
    activity_id: UUID,
    limit: int = 12,
    exclude_absent: bool = False,
) -> dict[str, Any]:
    """Build the event-detail attendee preview.

    ``withheld_count`` is computed but never returned to members: publishing it
    would let anyone infer how many attendees declined, which for a small event
    is close to naming them.
    """

    preview_enabled()
    records = await _load_attendee_records(session, activity_id)
    try:
        summary = build_preview(records, limit=limit, exclude_absent=exclude_absent)
    except AttendeeSocialRuleError as error:
        raise _fail(error) from error
    for item in summary.items:
        # Belt and braces: the projection is built by explicit construction, and
        # checked again before it leaves the service.
        try:
            assert_minimum_projection(item)
        except AttendeeSocialRuleError as error:  # pragma: no cover - defensive
            raise _fail(error, status_code=500) from error
    return {
        "activity_id": str(activity_id),
        "items": list(summary.items),
        "additional_visible_count": summary.additional_visible_count,
    }


async def get_my_consent(
    session: AsyncSession, *, registration_id: UUID, user_id: UUID
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT c.consent_state,c.granted_at,c.withdrawn_at,c.intro_line_encrypted "
                    "FROM activity_registrations r "
                    "LEFT JOIN attendee_preview_consents c ON c.registration_id=r.id "
                    "WHERE r.id=:registration_id AND r.user_id=:user_id"
                ),
                {"registration_id": str(registration_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("REGISTRATION_NOT_FOUND", "Registration not found.", status_code=404)
    return {
        "registration_id": str(registration_id),
        # No row means "never asked", which is a refusal by default (DEC-002).
        "consent_state": row["consent_state"] or PreviewConsentState.NOT_ASKED.value,
        "granted_at": row["granted_at"],
        "withdrawn_at": row["withdrawn_at"],
        "intro_line": (
            decrypt_private(row["intro_line_encrypted"]) if row["intro_line_encrypted"] else None
        ),
    }


async def set_preview_consent(
    session: AsyncSession,
    *,
    registration_id: UUID,
    user_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Record a consent decision and audit it.

    The row is locked before the transition is validated so a double-tap cannot
    produce two audit entries for one decision.
    """

    preview_enabled()
    owned = await session.scalar(
        text(
            "SELECT activity_id FROM activity_registrations "
            "WHERE id=:registration_id AND user_id=:user_id FOR UPDATE"
        ),
        {"registration_id": str(registration_id), "user_id": str(user_id)},
    )
    if owned is None:
        raise VavError("REGISTRATION_NOT_FOUND", "Registration not found.", status_code=404)
    activity_id = UUID(str(owned))
    current = (
        await session.scalar(
            text(
                "SELECT consent_state FROM attendee_preview_consents "
                "WHERE registration_id=:registration_id FOR UPDATE"
            ),
            {"registration_id": str(registration_id)},
        )
        or PreviewConsentState.NOT_ASKED.value
    )
    try:
        change = apply_consent_decision(
            current_state=current, target_state=payload["decision"], now=_now()
        )
    except AttendeeSocialRuleError as error:
        raise _fail(error, status_code=409) from error

    note = payload.get("note")
    await session.execute(
        text(
            "INSERT INTO attendee_preview_consents "
            "(registration_id,activity_id,user_id,consent_state,granted_at,withdrawn_at) "
            "VALUES (:registration_id,:activity_id,:user_id,:state,:granted_at,:withdrawn_at) "
            "ON CONFLICT (registration_id) DO UPDATE SET consent_state=EXCLUDED.consent_state,"
            "granted_at=COALESCE(EXCLUDED.granted_at, attendee_preview_consents.granted_at),"
            "withdrawn_at=EXCLUDED.withdrawn_at,updated_at=now()"
        ),
        {
            "registration_id": str(registration_id),
            "activity_id": str(activity_id),
            "user_id": str(user_id),
            "state": change.state.value,
            "granted_at": change.granted_at,
            "withdrawn_at": change.withdrawn_at,
        },
    )
    await session.execute(
        text(
            "INSERT INTO attendee_preview_consent_history "
            "(registration_id,user_id,from_state,to_state,actor_id,actor_kind,note_encrypted) "
            "VALUES (:registration_id,:user_id,:from_state,:to_state,:actor,'member',:note)"
        ),
        {
            "registration_id": str(registration_id),
            "user_id": str(user_id),
            "from_state": current,
            "to_state": change.state.value,
            "actor": str(user_id),
            "note": encrypt_private(note) if note else None,
        },
    )
    await _audit(
        session,
        subject_user_id=user_id,
        activity_id=activity_id,
        actor_id=user_id,
        actor_kind="member",
        action=change.audit_action,
        metadata={
            "from_state": current,
            "to_state": change.state.value,
            "removes_future_display": change.removes_future_display,
        },
    )
    await session.commit()
    return await get_my_consent(session, registration_id=registration_id, user_id=user_id)


async def set_preview_intro(
    session: AsyncSession,
    *,
    registration_id: UUID,
    user_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Store the optional one-line intro, encrypted at rest."""

    preview_enabled()
    intro = (payload.get("intro_line") or "").strip() or None
    updated = cast(
        CursorResult[Any],
        await session.execute(
            text(
                "UPDATE attendee_preview_consents SET intro_line_encrypted=:intro,updated_at=now() "
                "WHERE registration_id=:registration_id AND user_id=:user_id"
            ),
            {
                "intro": encrypt_private(intro) if intro else None,
                "registration_id": str(registration_id),
                "user_id": str(user_id),
            },
        ),
    )
    if updated.rowcount == 0:
        raise VavError(
            "PREVIEW_CONSENT_NOT_FOUND",
            "Answer the attendee preview prompt before adding an intro.",
            status_code=409,
        )
    await session.commit()
    return await get_my_consent(session, registration_id=registration_id, user_id=user_id)


async def admin_withdraw_consent(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Operator-side withdrawal (moderation, support request, legal takedown).

    There is no admin *grant*: an operator can only ever reduce visibility.
    """

    preview_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT user_id,activity_id,consent_state FROM attendee_preview_consents "
                    "WHERE registration_id=:registration_id FOR UPDATE"
                ),
                {"registration_id": str(payload["registration_id"])},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("PREVIEW_CONSENT_NOT_FOUND", "No consent record.", status_code=404)
    try:
        change = apply_consent_decision(
            current_state=row["consent_state"],
            target_state=PreviewConsentState.WITHDRAWN.value,
            now=_now(),
            source="admin",
        )
    except AttendeeSocialRuleError as error:
        raise _fail(error, status_code=409) from error
    await session.execute(
        text(
            "UPDATE attendee_preview_consents SET consent_state=:state,withdrawn_at=:withdrawn_at,"
            "updated_at=now() WHERE registration_id=:registration_id"
        ),
        {
            "state": change.state.value,
            "withdrawn_at": change.withdrawn_at,
            "registration_id": str(payload["registration_id"]),
        },
    )
    await session.execute(
        text(
            "INSERT INTO attendee_preview_consent_history "
            "(registration_id,user_id,from_state,to_state,actor_id,actor_kind,reason) "
            "VALUES (:registration_id,:user_id,:from_state,:to_state,:actor,'admin',:reason)"
        ),
        {
            "registration_id": str(payload["registration_id"]),
            "user_id": str(row["user_id"]),
            "from_state": row["consent_state"],
            "to_state": change.state.value,
            "actor": str(actor_id),
            "reason": payload["reason"],
        },
    )
    await _audit(
        session,
        subject_user_id=UUID(str(row["user_id"])),
        activity_id=UUID(str(row["activity_id"])),
        actor_id=actor_id,
        actor_kind="admin",
        action=change.audit_action,
        reason=payload["reason"],
    )
    await session.commit()
    return {
        "registration_id": str(payload["registration_id"]),
        "consent_state": change.state.value,
    }


# ---------------------------------------------------------------------------
# SOC-001 follow graph
# ---------------------------------------------------------------------------


async def _blocked_either_way(session: AsyncSession, first: UUID, second: UUID) -> bool:
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM user_blocks WHERE status='active' AND "
                "((blocker_user_id=:first AND blocked_user_id=:second) OR (blocker_user_id=:second AND blocked_user_id=:first)))"
            ),
            {"first": str(first), "second": str(second)},
        )
    )


async def follow_member(
    session: AsyncSession, *, follower_id: UUID, followee_id: UUID
) -> dict[str, Any]:
    """Create a follow edge. Idempotent, block-aware and never a like."""

    follow_graph_enabled()
    current = await session.scalar(
        text(
            "SELECT state FROM social_follows WHERE follower_id=:follower AND followee_id=:followee FOR UPDATE"
        ),
        {"follower": str(follower_id), "followee": str(followee_id)},
    )
    following_count = int(
        await session.scalar(
            text("SELECT count(*) FROM social_follows WHERE follower_id=:follower AND state='active'"),
            {"follower": str(follower_id)},
        )
        or 0
    )
    blocked = await _blocked_either_way(session, follower_id, followee_id)
    try:
        plan = plan_follow(
            follower_id=follower_id,
            followee_id=followee_id,
            current_state=current,
            follower_blocks_followee=blocked,
            followee_blocks_follower=blocked,
            following_count=following_count,
            max_following=get_settings().social_max_following,
        )
    except AttendeeSocialRuleError as error:
        status = 403 if error.code == "FOLLOW_BLOCKED" else 422
        raise _fail(error, status_code=status) from error

    if plan.action is not FollowAction.UNCHANGED:
        await session.execute(
            text(
                "INSERT INTO social_follows (follower_id,followee_id,state,followed_at) "
                "VALUES (:follower,:followee,:state,now()) "
                "ON CONFLICT (follower_id, followee_id) DO UPDATE SET state=EXCLUDED.state,"
                "followed_at=now(),unfollowed_at=NULL,updated_at=now()"
            ),
            {
                "follower": str(follower_id),
                "followee": str(followee_id),
                "state": plan.state.value,
            },
        )
    if plan.should_notify_target:
        await _publish(
            session,
            "social.follow.created.v1",
            "social_follow",
            followee_id,
            {"follower_id": str(follower_id), "followee_id": str(followee_id)},
        )
    await session.commit()
    return {
        "follower_id": str(follower_id),
        "followee_id": str(followee_id),
        "state": plan.state.value,
        "action": plan.action.value,
        # Stated explicitly in the response so no client can mistake this for a
        # mutual-selection signal (SOC-001).
        "relation_kind": RelationKind.FOLLOW.value,
    }


async def unfollow_member(
    session: AsyncSession, *, follower_id: UUID, followee_id: UUID
) -> dict[str, Any]:
    follow_graph_enabled()
    current = await session.scalar(
        text(
            "SELECT state FROM social_follows WHERE follower_id=:follower AND followee_id=:followee FOR UPDATE"
        ),
        {"follower": str(follower_id), "followee": str(followee_id)},
    )
    plan = plan_unfollow(current_state=current)
    if plan.action is FollowAction.REMOVED:
        await session.execute(
            text(
                "UPDATE social_follows SET state='unfollowed',unfollowed_at=now(),updated_at=now() "
                "WHERE follower_id=:follower AND followee_id=:followee"
            ),
            {"follower": str(follower_id), "followee": str(followee_id)},
        )
    await session.commit()
    return {
        "follower_id": str(follower_id),
        "followee_id": str(followee_id),
        "state": plan.state.value,
        "action": plan.action.value,
        # Keep every follow-graph response self-describing.  A client must not
        # infer that an unfollow response belongs to the matchmaking/like graph.
        "relation_kind": RelationKind.FOLLOW.value,
    }


async def list_following(
    session: AsyncSession, *, user_id: UUID, limit: int = 50
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT f.followee_id AS user_id, f.followed_at, "
                    "EXISTS (SELECT 1 FROM social_follows reverse_edge "
                    "WHERE reverse_edge.follower_id=f.followee_id "
                    "AND reverse_edge.followee_id=f.follower_id "
                    "AND reverse_edge.state='active') AS is_mutual "
                    "FROM social_follows f WHERE f.follower_id=:user_id AND f.state='active' "
                    "ORDER BY f.followed_at DESC LIMIT :limit"
                ),
                {"user_id": str(user_id), "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "user_id": str(row["user_id"]),
            "followed_at": row["followed_at"],
            "is_mutual": bool(row["is_mutual"]),
            "relation_kind": RelationKind.FOLLOW.value,
        }
        for row in rows
    ]


async def list_followers(
    session: AsyncSession, *, user_id: UUID, limit: int = 50
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT f.follower_id AS user_id, f.followed_at, "
                    "EXISTS (SELECT 1 FROM social_follows reverse_edge "
                    "WHERE reverse_edge.follower_id=f.followee_id "
                    "AND reverse_edge.followee_id=f.follower_id "
                    "AND reverse_edge.state='active') AS is_mutual "
                    "FROM social_follows f WHERE f.followee_id=:user_id AND f.state='active' "
                    "ORDER BY f.followed_at DESC LIMIT :limit"
                ),
                {"user_id": str(user_id), "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "user_id": str(row["user_id"]),
            "followed_at": row["followed_at"],
            "is_mutual": bool(row["is_mutual"]),
            "relation_kind": RelationKind.FOLLOW.value,
        }
        for row in rows
    ]


async def record_want_to_meet(
    session: AsyncSession, *, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Record event-scoped want-to-meet intent.

    Written to its own table with its own semantics. It is not a follow (it is
    event-scoped) and not a like (it is not a mutual-selection input).
    """

    follow_graph_enabled()
    target_id = UUID(str(payload["user_id"]))
    if target_id == user_id:
        raise VavError(
            "WANT_TO_MEET_SELF_NOT_ALLOWED",
            "A member cannot record want-to-meet for themselves.",
            status_code=422,
        )
    if await _blocked_either_way(session, user_id, target_id):
        raise VavError("WANT_TO_MEET_BLOCKED", "This member cannot be selected.", status_code=403)
    await session.execute(
        text(
            "INSERT INTO social_want_to_meet (user_id,target_user_id,activity_id) "
            "VALUES (:user_id,:target_user_id,:activity_id) "
            "ON CONFLICT (user_id, target_user_id, activity_id) DO NOTHING"
        ),
        {
            "user_id": str(user_id),
            "target_user_id": str(target_id),
            "activity_id": str(payload["activity_id"]),
        },
    )
    await session.commit()
    return {
        "user_id": str(user_id),
        "target_user_id": str(target_id),
        "activity_id": str(payload["activity_id"]),
        "relation_kind": RelationKind.WANT_TO_MEET.value,
        "semantics": {
            "is_event_scoped": relation_semantics(RelationKind.WANT_TO_MEET).is_event_scoped,
            "visible_to_target": relation_semantics(
                RelationKind.WANT_TO_MEET
            ).visible_to_target,
        },
    }


# ---------------------------------------------------------------------------
# SOC-001 followed_user_registered notification
# ---------------------------------------------------------------------------


async def get_notification_preferences(
    session: AsyncSession, user_id: UUID
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT followed_user_registered FROM social_notification_preferences "
                    "WHERE user_id=:user_id"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    return {
        FOLLOWED_USER_REGISTERED_PREFERENCE_KEY: (
            bool(row["followed_user_registered"]) if row else True
        )
    }


async def set_notification_preferences(
    session: AsyncSession, *, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    await session.execute(
        text(
            "INSERT INTO social_notification_preferences (user_id,followed_user_registered) "
            "VALUES (:user_id,:enabled) "
            "ON CONFLICT (user_id) DO UPDATE SET followed_user_registered=EXCLUDED.followed_user_registered,"
            "updated_at=now()"
        ),
        {
            "user_id": str(user_id),
            "enabled": bool(payload[FOLLOWED_USER_REGISTERED_PREFERENCE_KEY]),
        },
    )
    await session.commit()
    return await get_notification_preferences(session, user_id)


async def fan_out_followed_user_registered(
    session: AsyncSession, *, actor_id: UUID, activity_id: UUID
) -> dict[str, Any]:
    """Notify the actor's followers that they registered for an activity.

    Every recipient is decided by the domain, which returns a suppression reason
    rather than raising, so one ineligible follower cannot abort the batch. The
    dedupe key is written with a unique constraint, so a retried run inserts
    nothing and sends nothing.
    """

    follow_graph_enabled()
    activity = (
        (
            await session.execute(
                text("SELECT status,visibility FROM activities WHERE id=:id"),
                {"id": str(activity_id)},
            )
        )
        .mappings()
        .first()
    )
    if activity is None:
        raise VavError("ACTIVITY_NOT_FOUND", "Activity not found.", status_code=404)
    event_is_public = (
        activity["status"] == "published" and activity["visibility"] == "public"
    )
    registration_is_public = bool(
        await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM activity_registrations r "
                "JOIN attendee_preview_consents c ON c.registration_id=r.id "
                "WHERE r.activity_id=:activity_id AND r.user_id=:user_id "
                "AND r.status='confirmed' AND c.consent_state='granted')"
            ),
            {"activity_id": str(activity_id), "user_id": str(actor_id)},
        )
    )
    rows = (
        (
            await session.execute(
                text(
                    "SELECT f.follower_id, f.state, "
                    " COALESCE(p.followed_user_registered, true) AS preference_enabled, "
                    " EXISTS (SELECT 1 FROM user_blocks b WHERE b.status='active' AND "
                    "   ((b.blocker_user_id=f.follower_id AND b.blocked_user_id=:actor_id) OR "
                    "    (b.blocker_user_id=:actor_id AND b.blocked_user_id=f.follower_id))) AS blocked, "
                    " EXISTS (SELECT 1 FROM social_notification_deliveries d "
                    "   WHERE d.dedupe_key = 'social.followed_user_registered:' || f.follower_id::text "
                    "     || ':' || :actor_id || ':' || :activity_id) AS already_delivered "
                    "FROM social_follows f "
                    "LEFT JOIN social_notification_preferences p ON p.user_id=f.follower_id "
                    "WHERE f.followee_id=:actor_id AND f.state='active'"
                ),
                {"actor_id": str(actor_id), "activity_id": str(activity_id)},
            )
        )
        .mappings()
        .all()
    )
    now = _now()
    sent = 0
    suppressed: dict[str, int] = {}
    for row in rows:
        recipient_id = UUID(str(row["follower_id"]))
        decision = decide_followed_user_registered(
            recipient_id=recipient_id,
            actor_id=actor_id,
            activity_id=activity_id,
            follow_state=row["state"],
            blocked_either_way=bool(row["blocked"]),
            preference_enabled=bool(row["preference_enabled"]),
            actor_registration_is_public=registration_is_public,
            event_is_public=event_is_public,
            already_delivered=bool(row["already_delivered"]),
        )
        if not decision.should_send:
            suppressed[decision.suppression.value] = (
                suppressed.get(decision.suppression.value, 0) + 1
            )
            continue
        inserted = cast(
            CursorResult[Any],
            await session.execute(
                text(
                    "INSERT INTO social_notification_deliveries "
                    "(dedupe_key,recipient_id,actor_id,activity_id,notification_code) "
                    "VALUES (:dedupe_key,:recipient,:actor,:activity_id,:code) "
                    "ON CONFLICT (dedupe_key) DO NOTHING"
                ),
                {
                    "dedupe_key": decision.dedupe_key,
                    "recipient": str(recipient_id),
                    "actor": str(actor_id),
                    "activity_id": str(activity_id),
                    "code": FOLLOWED_USER_REGISTERED_PREFERENCE_KEY,
                },
            ),
        )
        if not inserted.rowcount:
            # Another worker won the race; the constraint is the source of truth.
            suppressed["already_delivered"] = suppressed.get("already_delivered", 0) + 1
            continue
        await _publish(
            session,
            FOLLOWED_USER_REGISTERED_TOPIC,
            "social_notification",
            recipient_id,
            build_followed_user_registered_payload(
                recipient_id=recipient_id,
                actor_id=actor_id,
                activity_id=activity_id,
                occurred_at=now,
            ),
        )
        sent += 1
    await session.commit()
    return {"sent": sent, "considered": len(rows), "suppressed": suppressed}


async def apply_block(
    session: AsyncSession, *, blocker_user_id: UUID, blocked_user_id: UUID
) -> dict[str, Any]:
    """Sever follow edges in both directions when a block is created.

    Called by the moderation module after it writes the block row.
    """

    result = cast(
        CursorResult[Any],
        await session.execute(
            text(
                "UPDATE social_follows SET state='blocked',unfollowed_at=now(),updated_at=now() "
                "WHERE state='active' AND ((follower_id=:a AND followee_id=:b) OR (follower_id=:b AND followee_id=:a))"
            ),
            {"a": str(blocker_user_id), "b": str(blocked_user_id)},
        ),
    )
    await _audit(
        session,
        subject_user_id=blocked_user_id,
        activity_id=None,
        actor_id=blocker_user_id,
        actor_kind="member",
        action="social.follows.severed_by_block",
        metadata={"severed": result.rowcount or 0},
    )
    await session.commit()
    return {"severed": result.rowcount or 0, "state": FollowState.BLOCKED.value}
