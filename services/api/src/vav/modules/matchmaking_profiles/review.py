"""Profile submission review workflow.

Reviewers judge what the member wrote; they never rewrite it. Every decision
separates the member-visible message from the internal note, and rejection or
suspension always requires a reason.
"""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.identity import User
from vav.modules.matchmaking_profiles.domain import (
    PHOTO_REJECTION_REASON_CODES,
    DatingProfileStatus,
    ProfileReviewDecision,
    ProfileReviewStatus,
    can_transition_review,
)
from vav.modules.matchmaking_profiles.service import (
    audit,
    emit_event,
    json_value,
    queue_projection_rebuild,
    require_profile,
    start_draft_revision,
)
from vav.modules.privacy.crypto import encrypt_private

_OPEN_STATUSES = (
    ProfileReviewStatus.PENDING.value,
    ProfileReviewStatus.ASSIGNED.value,
    ProfileReviewStatus.IN_REVIEW.value,
    ProfileReviewStatus.ESCALATED.value,
)


async def _case(session: AsyncSession, case_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM dating_profile_review_cases WHERE id=:id"), {"id": case_id}
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("DATING_REVIEW_CASE_NOT_FOUND", "Review case not found.", status_code=404)
    return dict(row)


async def _advance(
    session: AsyncSession,
    case: dict[str, Any],
    target: ProfileReviewStatus,
    *,
    expected_version: int | None,
    extra_sql: str = "",
    params: dict[str, Any] | None = None,
) -> None:
    if not can_transition_review(case["status"], target.value):
        raise VavError(
            "DATING_REVIEW_TRANSITION_INVALID",
            f"A review cannot move from {case['status']} to {target.value}.",
            status_code=409,
        )
    if expected_version is not None and expected_version != case["version"]:
        raise VavError(
            "DATING_REVIEW_VERSION_CONFLICT",
            "Another reviewer changed this case. Reload and try again.",
            status_code=409,
        )
    result = await session.execute(
        text(
            f"UPDATE dating_profile_review_cases SET status=:status,version=version+1,updated_at=now(){extra_sql} "
            "WHERE id=:id AND version=:version"
        ),
        {
            "status": target.value,
            "id": case["id"],
            "version": case["version"],
            **(params or {}),
        },
    )
    if int(getattr(result, "rowcount", 0) or 0) == 0:
        # Two reviewers decided at the same moment; neither may silently win.
        raise VavError(
            "DATING_REVIEW_VERSION_CONFLICT",
            "Another reviewer changed this case. Reload and try again.",
            status_code=409,
        )
    case["status"] = target.value
    case["version"] += 1


async def list_cases(
    session: AsyncSession, *, status: str | None, page: int, page_size: int
) -> dict[str, Any]:
    clause = "WHERE c.status = :status" if status else "WHERE c.status = ANY(:open_statuses)"
    params: dict[str, Any] = (
        {"status": status} if status else {"open_statuses": list(_OPEN_STATUSES)}
    )
    total = await session.scalar(
        text(f"SELECT count(*) FROM dating_profile_review_cases c {clause}"), params
    )
    rows = (
        (
            await session.execute(
                text(
                    "SELECT c.id,c.dating_profile_id,c.profile_version_id,c.review_type,c.status,c.priority,"
                    "c.assigned_to,c.submitted_at,c.started_at,c.completed_at,c.overall_decision,c.version,"
                    "d.profile_number,d.status AS profile_status,v.version_number "
                    "FROM dating_profile_review_cases c "
                    "JOIN dating_profiles d ON d.id=c.dating_profile_id "
                    "JOIN dating_profile_versions v ON v.id=c.profile_version_id "
                    f"{clause} ORDER BY c.priority DESC,c.submitted_at LIMIT :limit OFFSET :offset"
                ),
                params | {"limit": page_size, "offset": (page - 1) * page_size},
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [dict(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
    }


async def assign_case(
    session: AsyncSession,
    actor: User,
    case_id: UUID,
    assignee_id: UUID,
    expected_version: int | None,
) -> dict[str, Any]:
    case = await _case(session, case_id)
    await _advance(
        session,
        case,
        ProfileReviewStatus.ASSIGNED,
        expected_version=expected_version,
        extra_sql=",assigned_to=:assignee,assigned_at=now()",
        params={"assignee": assignee_id},
    )
    await audit(
        session,
        "matchmaking.review.assigned",
        "dating_profile_review_case",
        case_id,
        actor_id=actor.id,
        context={"assigned_to": str(assignee_id)},
    )
    await session.commit()
    return {"case_id": str(case_id), "status": case["status"], "version": case["version"]}


async def start_case(
    session: AsyncSession, actor: User, case_id: UUID, expected_version: int | None
) -> dict[str, Any]:
    case = await _case(session, case_id)
    await _advance(
        session,
        case,
        ProfileReviewStatus.IN_REVIEW,
        expected_version=expected_version,
        extra_sql=",started_at=COALESCE(started_at, now())",
    )
    await session.execute(
        text(
            "UPDATE dating_profiles SET status='in_review',review_status='in_review',updated_at=now() "
            "WHERE id=:id AND status='submitted'"
        ),
        {"id": case["dating_profile_id"]},
    )
    await audit(
        session,
        "matchmaking.review.started",
        "dating_profile_review_case",
        case_id,
        actor_id=actor.id,
    )
    await emit_event(
        session,
        "dating_profile.review_started",
        case["dating_profile_id"],
        {"case_id": str(case_id)},
    )
    await session.commit()
    return {"case_id": str(case_id), "status": case["status"], "version": case["version"]}


async def record_item(
    session: AsyncSession,
    actor: User,
    case_id: UUID,
    *,
    item_type: str,
    field_code: str | None,
    photo_id: UUID | None,
    decision: str,
    reason_code: str | None,
    user_message_safe: str | None,
    internal_note: str | None,
) -> dict[str, Any]:
    """Record one field-level or photo-level review outcome."""
    case = await _case(session, case_id)
    if case["status"] not in {
        ProfileReviewStatus.IN_REVIEW.value,
        ProfileReviewStatus.ESCALATED.value,
    }:
        raise VavError(
            "DATING_REVIEW_NOT_STARTED",
            "Start the review case before recording decisions.",
            status_code=409,
        )
    try:
        parsed = ProfileReviewDecision(decision)
    except ValueError as exc:
        raise VavError(
            "DATING_REVIEW_DECISION_INVALID", "Unknown decision.", status_code=422
        ) from exc
    if item_type not in {"field", "photo"}:
        raise VavError("DATING_REVIEW_ITEM_TYPE_INVALID", "Unknown item type.", status_code=422)
    if item_type == "field" and not field_code:
        raise VavError("DATING_REVIEW_FIELD_REQUIRED", "A field code is required.", status_code=422)
    if item_type == "photo" and photo_id is None:
        raise VavError("DATING_REVIEW_PHOTO_REQUIRED", "A photo id is required.", status_code=422)
    if (
        parsed in {ProfileReviewDecision.REJECT, ProfileReviewDecision.CHANGES_REQUIRED}
        and not reason_code
    ):
        raise VavError(
            "DATING_REVIEW_REASON_REQUIRED",
            "A reason code is required for rejection or change requests.",
            status_code=422,
        )
    if item_type == "photo" and reason_code and reason_code not in PHOTO_REJECTION_REASON_CODES:
        raise VavError(
            "DATING_REVIEW_REASON_INVALID",
            "This photo reason code is not recognised.",
            status_code=422,
        )

    item_id = await session.scalar(
        text(
            "INSERT INTO dating_profile_review_items "
            "(review_case_id,item_type,field_code,photo_id,decision,reason_code,user_message_safe,internal_note_encrypted,reviewed_by) "
            "VALUES (:case_id,:item_type,:field,:photo,:decision,:reason,:message,:note,:actor) RETURNING id"
        ),
        {
            "case_id": case_id,
            "item_type": item_type,
            "field": field_code,
            "photo": photo_id,
            "decision": parsed.value,
            "reason": reason_code,
            "message": user_message_safe,
            "note": encrypt_private(internal_note) if internal_note else None,
            "actor": actor.id,
        },
    )

    if item_type == "photo" and photo_id is not None:
        await _apply_photo_decision(
            session, actor, case, photo_id, parsed, reason_code, user_message_safe
        )

    await audit(
        session,
        "matchmaking.review.completed",
        "dating_profile_review_item",
        UUID(str(item_id)),
        actor_id=actor.id,
        context={
            "case_id": str(case_id),
            "item_type": item_type,
            "field_code": field_code,
            "decision": parsed.value,
            "reason_code": reason_code,
        },
    )
    await session.commit()
    return {"item_id": str(item_id), "decision": parsed.value}


async def _apply_photo_decision(
    session: AsyncSession,
    actor: User,
    case: dict[str, Any],
    photo_id: UUID,
    decision: ProfileReviewDecision,
    reason_code: str | None,
    user_message_safe: str | None,
) -> None:
    if decision is ProfileReviewDecision.APPROVE:
        await session.execute(
            text(
                "UPDATE dating_profile_photos SET status='approved',reviewed_by=:actor,reviewed_at=now(),"
                "rejection_reason_code=NULL,rejection_message_safe=NULL,updated_at=now() "
                "WHERE id=:id AND dating_profile_id=:profile_id AND status='review_required'"
            ),
            {"actor": actor.id, "id": photo_id, "profile_id": case["dating_profile_id"]},
        )
        await emit_event(
            session,
            "dating_profile.photo.approved",
            case["dating_profile_id"],
            {"photo_id": str(photo_id)},
        )
        await queue_projection_rebuild(
            session, case["dating_profile_id"], "dating_profile.photo_approved"
        )
    elif decision in {ProfileReviewDecision.REJECT, ProfileReviewDecision.CHANGES_REQUIRED}:
        await session.execute(
            text(
                "UPDATE dating_profile_photos SET status='rejected',reviewed_by=:actor,reviewed_at=now(),"
                "rejection_reason_code=:reason,rejection_message_safe=:message,updated_at=now() WHERE id=:id "
                "AND dating_profile_id=:profile_id"
            ),
            {
                "actor": actor.id,
                "id": photo_id,
                "profile_id": case["dating_profile_id"],
                "reason": reason_code,
                "message": user_message_safe,
            },
        )
        # A rejected photo must disappear from every viewer immediately.
        await session.execute(
            text(
                "UPDATE dating_profile_photo_view_tokens SET revoked_at=now() "
                "WHERE photo_id=:id AND revoked_at IS NULL"
            ),
            {"id": photo_id},
        )
        await emit_event(
            session,
            "dating_profile.photo.rejected",
            case["dating_profile_id"],
            {"photo_id": str(photo_id), "reason_code": reason_code},
        )
        await queue_projection_rebuild(
            session, case["dating_profile_id"], "dating_profile.photo_approved"
        )


async def approve_case(
    session: AsyncSession,
    actor: User,
    case_id: UUID,
    *,
    user_message: str | None,
    internal_summary: str | None,
    expected_version: int | None,
) -> dict[str, Any]:
    """Approve a version and atomically switch the displayed approved version."""
    case = await _case(session, case_id)
    blocking = await session.scalar(
        text(
            "SELECT count(*) FROM dating_profile_review_items WHERE review_case_id=:id "
            "AND decision IN ('reject','changes_required')"
        ),
        {"id": case_id},
    )
    if int(blocking or 0):
        raise VavError(
            "DATING_REVIEW_HAS_BLOCKING_ITEMS",
            "Resolve the rejected fields or photos before approving this profile.",
            status_code=409,
        )
    await _advance(
        session,
        case,
        ProfileReviewStatus.APPROVED,
        expected_version=expected_version,
        extra_sql=",completed_at=now(),overall_decision='approve',user_message_safe=:message,internal_summary_encrypted=:summary",
        params={
            "message": user_message,
            "summary": encrypt_private(internal_summary) if internal_summary else None,
        },
    )
    version_number = await session.scalar(
        text("SELECT version_number FROM dating_profile_versions WHERE id=:id"),
        {"id": case["profile_version_id"]},
    )
    await session.execute(
        text(
            "UPDATE dating_profile_versions SET review_status='approved',approved_at=now() WHERE id=:id"
        ),
        {"id": case["profile_version_id"]},
    )
    await session.execute(
        text(
            "UPDATE dating_profiles SET status='active',review_status='approved',"
            "approved_version_number=:version,approved_at=now(),activated_at=COALESCE(activated_at, now()),"
            "searchable=true,paused_at=NULL,version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"version": version_number, "id": case["dating_profile_id"]},
    )
    await audit(
        session,
        "matchmaking.profile.approved",
        "dating_profile",
        case["dating_profile_id"],
        actor_id=actor.id,
        context={"case_id": str(case_id), "version_number": version_number},
    )
    await emit_event(
        session,
        "dating_profile.approved",
        case["dating_profile_id"],
        {"version_number": version_number},
    )
    await emit_event(
        session,
        "dating_profile.activated",
        case["dating_profile_id"],
        {"version_number": version_number},
    )
    await queue_projection_rebuild(session, case["dating_profile_id"], "dating_profile.approved")
    await session.commit()
    return {
        "case_id": str(case_id),
        "status": ProfileReviewStatus.APPROVED.value,
        "approved_version_number": version_number,
    }


async def request_changes(
    session: AsyncSession,
    actor: User,
    case_id: UUID,
    *,
    user_message: str,
    internal_summary: str | None,
    expected_version: int | None,
) -> dict[str, Any]:
    case = await _case(session, case_id)
    if not user_message.strip():
        raise VavError(
            "DATING_REVIEW_MESSAGE_REQUIRED",
            "Explain to the member what needs to change.",
            status_code=422,
        )
    await _advance(
        session,
        case,
        ProfileReviewStatus.CHANGES_REQUESTED,
        expected_version=expected_version,
        extra_sql=",completed_at=now(),overall_decision='changes_required',user_message_safe=:message,internal_summary_encrypted=:summary",
        params={
            "message": user_message,
            "summary": encrypt_private(internal_summary) if internal_summary else None,
        },
    )
    await session.execute(
        text("UPDATE dating_profile_versions SET review_status='changes_requested' WHERE id=:id"),
        {"id": case["profile_version_id"]},
    )
    profile = (
        (
            await session.execute(
                text("SELECT * FROM dating_profiles WHERE id=:id"),
                {"id": case["dating_profile_id"]},
            )
        )
        .mappings()
        .first()
    )
    assert profile is not None
    await session.execute(
        text(
            "UPDATE dating_profiles SET status='changes_requested',review_status='changes_requested',"
            "version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"id": case["dating_profile_id"]},
    )
    # Editing after a change request always opens a new draft version so the
    # previously approved version keeps serving other members.
    await start_draft_revision(session, dict(profile))
    await audit(
        session,
        "matchmaking.profile.changes_requested",
        "dating_profile",
        case["dating_profile_id"],
        actor_id=actor.id,
        context={"case_id": str(case_id)},
    )
    await emit_event(
        session,
        "dating_profile.changes_requested",
        case["dating_profile_id"],
        {"case_id": str(case_id)},
    )
    await session.commit()
    return {"case_id": str(case_id), "status": ProfileReviewStatus.CHANGES_REQUESTED.value}


async def reject_case(
    session: AsyncSession,
    actor: User,
    case_id: UUID,
    *,
    reason_code: str,
    user_message: str,
    internal_summary: str | None,
    expected_version: int | None,
) -> dict[str, Any]:
    settings = get_settings()
    if settings.dating_review_require_reason_for_rejection and not reason_code.strip():
        raise VavError(
            "DATING_REVIEW_REASON_REQUIRED", "A rejection reason is required.", status_code=422
        )
    case = await _case(session, case_id)
    await _advance(
        session,
        case,
        ProfileReviewStatus.REJECTED,
        expected_version=expected_version,
        extra_sql=",completed_at=now(),overall_decision='reject',user_message_safe=:message,internal_summary_encrypted=:summary",
        params={
            "message": user_message,
            "summary": encrypt_private(internal_summary) if internal_summary else None,
        },
    )
    await session.execute(
        text("UPDATE dating_profile_versions SET review_status='rejected' WHERE id=:id"),
        {"id": case["profile_version_id"]},
    )
    await session.execute(
        text(
            "UPDATE dating_profiles SET status='rejected',review_status='rejected',searchable=false,"
            "version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"id": case["dating_profile_id"]},
    )
    await audit(
        session,
        "matchmaking.profile.rejected",
        "dating_profile",
        case["dating_profile_id"],
        actor_id=actor.id,
        reason=reason_code,
    )
    await queue_projection_rebuild(session, case["dating_profile_id"], "dating_profile.suspended")
    await session.commit()
    return {"case_id": str(case_id), "status": ProfileReviewStatus.REJECTED.value}


async def escalate_case(
    session: AsyncSession,
    actor: User,
    case_id: UUID,
    *,
    reason: str,
    expected_version: int | None,
) -> dict[str, Any]:
    case = await _case(session, case_id)
    await _advance(
        session,
        case,
        ProfileReviewStatus.ESCALATED,
        expected_version=expected_version,
        extra_sql=",priority='high'",
    )
    await audit(
        session,
        "matchmaking.review.escalated",
        "dating_profile_review_case",
        case_id,
        actor_id=actor.id,
        reason=reason,
    )
    await session.commit()
    return {"case_id": str(case_id), "status": ProfileReviewStatus.ESCALATED.value}


async def suspend_profile(
    session: AsyncSession, actor: User, profile_id: UUID, *, reason_code: str
) -> dict[str, Any]:
    settings = get_settings()
    if settings.dating_review_require_reason_for_suspension and not reason_code.strip():
        raise VavError(
            "DATING_REVIEW_REASON_REQUIRED", "A suspension reason is required.", status_code=422
        )
    result = await session.execute(
        text(
            "UPDATE dating_profiles SET status='suspended',searchable=false,suspended_at=now(),"
            "suspension_reason_code=:reason,version=version+1,updated_at=now() "
            "WHERE id=:id AND status IN ('active','paused_by_user','in_review','approved')"
        ),
        {"id": profile_id, "reason": reason_code},
    )
    if int(getattr(result, "rowcount", 0) or 0) == 0:
        raise VavError(
            "DATING_PROFILE_TRANSITION_INVALID",
            "This profile cannot be suspended in its current state.",
            status_code=409,
        )
    await audit(
        session,
        "matchmaking.profile.suspended",
        "dating_profile",
        profile_id,
        actor_id=actor.id,
        reason=reason_code,
    )
    await emit_event(session, "dating_profile.suspended", profile_id, {"reason_code": reason_code})
    await queue_projection_rebuild(session, profile_id, "dating_profile.suspended")
    await session.commit()
    return {"profile_id": str(profile_id), "status": DatingProfileStatus.SUSPENDED.value}


async def restore_profile(
    session: AsyncSession, actor: User, profile_id: UUID, *, reason: str | None
) -> dict[str, Any]:
    result = await session.execute(
        text(
            "UPDATE dating_profiles SET status='active',searchable=true,suspended_at=NULL,"
            "suspension_reason_code=NULL,version=version+1,updated_at=now() "
            "WHERE id=:id AND status='suspended' AND approved_version_number IS NOT NULL"
        ),
        {"id": profile_id},
    )
    if int(getattr(result, "rowcount", 0) or 0) == 0:
        raise VavError(
            "DATING_PROFILE_TRANSITION_INVALID",
            "Only a suspended profile with an approved version can be restored.",
            status_code=409,
        )
    await audit(
        session,
        "matchmaking.profile.restored",
        "dating_profile",
        profile_id,
        actor_id=actor.id,
        reason=reason,
    )
    await emit_event(session, "dating_profile.restored", profile_id, {})
    await queue_projection_rebuild(session, profile_id, "dating_profile.activated")
    await session.commit()
    return {"profile_id": str(profile_id), "status": DatingProfileStatus.ACTIVE.value}


async def pause_profile(session: AsyncSession, user: User) -> dict[str, Any]:
    profile = await require_profile(session, user.id)
    result = await session.execute(
        text(
            "UPDATE dating_profiles SET status='paused_by_user',searchable=false,paused_at=now(),"
            "version=version+1,updated_at=now() WHERE id=:id AND status='active'"
        ),
        {"id": profile["id"]},
    )
    if int(getattr(result, "rowcount", 0) or 0) == 0:
        raise VavError(
            "DATING_PROFILE_TRANSITION_INVALID",
            "Only an active profile can be paused.",
            status_code=409,
        )
    await audit(
        session, "matchmaking.profile.paused", "dating_profile", profile["id"], actor_id=user.id
    )
    await emit_event(session, "dating_profile.paused", profile["id"], {})
    await queue_projection_rebuild(session, profile["id"], "dating_profile.paused")
    await session.commit()
    return {"profile_id": str(profile["id"]), "status": DatingProfileStatus.PAUSED_BY_USER.value}


async def reactivate_profile(session: AsyncSession, user: User) -> dict[str, Any]:
    profile = await require_profile(session, user.id)
    result = await session.execute(
        text(
            "UPDATE dating_profiles SET status='active',searchable=true,paused_at=NULL,"
            "version=version+1,updated_at=now() WHERE id=:id AND status='paused_by_user' "
            "AND approved_version_number IS NOT NULL"
        ),
        {"id": profile["id"]},
    )
    if int(getattr(result, "rowcount", 0) or 0) == 0:
        raise VavError(
            "DATING_PROFILE_TRANSITION_INVALID",
            "Only a paused profile with an approved version can be reactivated.",
            status_code=409,
        )
    await audit(
        session,
        "matchmaking.profile.restored",
        "dating_profile",
        profile["id"],
        actor_id=user.id,
        context={"action": "reactivated"},
    )
    await emit_event(session, "dating_profile.reactivated", profile["id"], {})
    await queue_projection_rebuild(session, profile["id"], "dating_profile.activated")
    await session.commit()
    return {"profile_id": str(profile["id"]), "status": DatingProfileStatus.ACTIVE.value}


async def review_feedback(session: AsyncSession, user: User) -> dict[str, Any]:
    """Member-facing feedback: safe messages only, never internal notes."""
    profile = await require_profile(session, user.id)
    case = (
        (
            await session.execute(
                text(
                    "SELECT c.id,c.status,c.overall_decision,c.user_message_safe,c.completed_at,v.version_number "
                    "FROM dating_profile_review_cases c JOIN dating_profile_versions v ON v.id=c.profile_version_id "
                    "WHERE c.dating_profile_id=:id ORDER BY c.submitted_at DESC LIMIT 1"
                ),
                {"id": profile["id"]},
            )
        )
        .mappings()
        .first()
    )
    if case is None:
        return {"has_feedback": False, "items": []}
    items = (
        (
            await session.execute(
                text(
                    "SELECT item_type,field_code,photo_id,decision,reason_code,user_message_safe,reviewed_at "
                    "FROM dating_profile_review_items WHERE review_case_id=:id "
                    "AND decision IN ('changes_required','reject') ORDER BY reviewed_at"
                ),
                {"id": case["id"]},
            )
        )
        .mappings()
        .all()
    )
    return {
        "has_feedback": True,
        "review_status": case["status"],
        "overall_decision": case["overall_decision"],
        "message": case["user_message_safe"],
        "version_number": case["version_number"],
        "completed_at": case["completed_at"],
        "items": [dict(row) for row in items],
    }


async def case_detail(
    session: AsyncSession, case_id: UUID, *, include_sensitive: bool
) -> dict[str, Any]:
    case = await _case(session, case_id)
    items = (
        (
            await session.execute(
                text(
                    "SELECT id,item_type,field_code,photo_id,decision,reason_code,user_message_safe,reviewed_by,reviewed_at "
                    "FROM dating_profile_review_items WHERE review_case_id=:id ORDER BY reviewed_at"
                ),
                {"id": case_id},
            )
        )
        .mappings()
        .all()
    )
    detail = {
        key: value
        for key, value in case.items()
        # Internal summaries stay encrypted and are never returned by the API.
        if key != "internal_summary_encrypted"
    }
    detail["items"] = [dict(row) for row in items]
    detail["sensitive_access_granted"] = include_sensitive
    return detail


async def audit_trail(
    session: AsyncSession, *, subject_id: UUID | None, page: int, page_size: int
) -> dict[str, Any]:
    clause = "WHERE subject_id=:subject_id" if subject_id else ""
    params: dict[str, Any] = {"subject_id": subject_id} if subject_id else {}
    total = await session.scalar(
        text(f"SELECT count(*) FROM matchmaking_audit_events {clause}"), params
    )
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,event_type,actor_id,subject_type,subject_id,reason,safe_context,created_at "
                    f"FROM matchmaking_audit_events {clause} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                ),
                params | {"limit": page_size, "offset": (page - 1) * page_size},
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [dict(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
    }


def safe_context(payload: dict[str, Any]) -> str:
    return json_value(payload)
