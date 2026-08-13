"""Transactional post-event closure service (B09 / B10 / B11).

Design notes:

* Every write that must be serial (`freeze`, `submit`, `publish`) takes a row
  lock first, so two devices submitting at the same time produce one outcome.
* Candidate snapshots are append-only: a correction supersedes a version, it
  never edits one. That is what makes the frozen list replayable.
* Free-text member input (open answers, letter bodies, pass-reason notes) is
  stored through :mod:`vav.modules.privacy.crypto` and never enters outbox
  payloads, history rows or logs.
* All business rules live in :mod:`vav.modules.post_event.domain` so they are
  testable without a database; this layer only loads state and persists it.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.post_event.domain import (
    AttendanceRecord,
    CandidateEligibility,
    ExclusionKind,
    LetterOutcome,
    LetterStatus,
    PostEventRuleError,
    QuestionSpec,
    QuestionType,
    SelectionPolicy,
    SnapshotStatus,
    SubmittedAnswer,
    VisibilityMode,
    build_candidate_decisions,
    compute_mutual_pairs,
    content_fingerprint,
    ensure_reviewer_is_not_author,
    ensure_selection_editable,
    ensure_survey_open,
    extract_template_variables,
    is_survey_task_eligible,
    is_visible_candidate,
    plan_reminders,
    reminder_dedupe_key,
    render_template,
    require_manual_exclusion_reason,
    validate_answers,
    validate_letter_transition,
    validate_selection,
    validate_snapshot_transition,
)
from vav.modules.privacy.crypto import decrypt_private, encrypt_private

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: PostEventRuleError, status_code: int = 422) -> VavError:
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


def candidate_freeze_enabled() -> None:
    if not get_settings().post_event_candidate_freeze_enabled:
        raise VavError(
            "CANDIDATE_FREEZE_DISABLED",
            "Post-event candidate freeze is not enabled.",
            status_code=503,
        )


def survey_enabled() -> None:
    if not get_settings().post_event_survey_enabled:
        raise VavError(
            "POST_EVENT_SURVEY_DISABLED", "Post-event surveys are not enabled.", status_code=503
        )


def result_letters_enabled() -> None:
    if not get_settings().result_letters_enabled:
        raise VavError(
            "RESULT_LETTERS_DISABLED", "Result letters are not enabled.", status_code=503
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
    activity_id: UUID,
    snapshot_id: UUID | None,
    actor_id: UUID | None,
    actor_kind: str,
    action: str,
    subject_user_id: UUID | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO activity_selection_audits "
            "(activity_id,snapshot_id,actor_id,actor_kind,action,subject_user_id,reason,metadata) "
            "VALUES (:activity_id,:snapshot_id,:actor_id,:actor_kind,:action,:subject_user_id,:reason,CAST(:metadata AS jsonb))"
        ),
        {
            "activity_id": str(activity_id),
            "snapshot_id": str(snapshot_id) if snapshot_id else None,
            "actor_id": str(actor_id) if actor_id else None,
            "actor_kind": actor_kind,
            "action": action,
            "subject_user_id": str(subject_user_id) if subject_user_id else None,
            "reason": reason,
            "metadata": _json(metadata or {}),
        },
    )


# ---------------------------------------------------------------------------
# B09 selection policy and pass reasons
# ---------------------------------------------------------------------------


async def _load_policy(session: AsyncSession, activity_id: UUID) -> SelectionPolicy:
    row = (
        (
            await session.execute(
                text(
                    "SELECT visibility_mode,max_selections,min_selections,edit_window_hours,"
                    "allow_edit_after_submit,custom_rule FROM activity_selection_policies "
                    "WHERE activity_id=:activity_id"
                ),
                {"activity_id": str(activity_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        # No configured policy means the documented safe default, not "no rule".
        return SelectionPolicy()
    custom_pairs = frozenset(
        (UUID(str(pair[0])), UUID(str(pair[1])))
        for pair in (row["custom_rule"] or {}).get("pairs", [])
    )
    return SelectionPolicy(
        mode=VisibilityMode(row["visibility_mode"]),
        max_selections=int(row["max_selections"]),
        min_selections=int(row["min_selections"]),
        edit_window_hours=int(row["edit_window_hours"]),
        allow_edit_after_submit=bool(row["allow_edit_after_submit"]),
        custom_pairs=custom_pairs,
    )


async def upsert_selection_policy(
    session: AsyncSession, *, activity_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    candidate_freeze_enabled()
    try:
        # Constructing the dataclass validates the combination before we store it.
        SelectionPolicy(
            mode=VisibilityMode(payload["visibility_mode"]),
            max_selections=int(payload["max_selections"]),
            min_selections=int(payload["min_selections"]),
            edit_window_hours=int(payload["edit_window_hours"]),
            allow_edit_after_submit=bool(payload["allow_edit_after_submit"]),
        )
    except PostEventRuleError as error:
        raise _fail(error) from error
    await session.execute(
        text(
            "INSERT INTO activity_selection_policies "
            "(activity_id,visibility_mode,max_selections,min_selections,edit_window_hours,allow_edit_after_submit,custom_rule,updated_by) "
            "VALUES (:activity_id,:mode,:max_selections,:min_selections,:edit_window_hours,:allow_edit,CAST(:custom_rule AS jsonb),:actor) "
            "ON CONFLICT (activity_id) DO UPDATE SET visibility_mode=EXCLUDED.visibility_mode,"
            "max_selections=EXCLUDED.max_selections,min_selections=EXCLUDED.min_selections,"
            "edit_window_hours=EXCLUDED.edit_window_hours,allow_edit_after_submit=EXCLUDED.allow_edit_after_submit,"
            "custom_rule=EXCLUDED.custom_rule,updated_by=EXCLUDED.updated_by,updated_at=now()"
        ),
        {
            "activity_id": str(activity_id),
            "mode": payload["visibility_mode"],
            "max_selections": payload["max_selections"],
            "min_selections": payload["min_selections"],
            "edit_window_hours": payload["edit_window_hours"],
            "allow_edit": payload["allow_edit_after_submit"],
            "custom_rule": _json(payload.get("custom_rule") or {}),
            "actor": str(actor_id),
        },
    )
    await _audit(
        session,
        activity_id=activity_id,
        snapshot_id=None,
        actor_id=actor_id,
        actor_kind="admin",
        action="selection_policy.updated",
        metadata={key: payload[key] for key in ("visibility_mode", "max_selections")},
    )
    await session.commit()
    return {"activity_id": str(activity_id), **payload}


async def _allowed_pass_reasons(session: AsyncSession, activity_id: UUID) -> dict[str, bool]:
    """Activity-scoped reasons win over global ones with the same code."""

    rows = (
        (
            await session.execute(
                text(
                    "SELECT reason_code,requires_note,activity_id FROM activity_pass_reason_options "
                    "WHERE is_active=true AND (activity_id=:activity_id OR activity_id IS NULL) "
                    "ORDER BY activity_id NULLS FIRST, sort_order, reason_code"
                ),
                {"activity_id": str(activity_id)},
            )
        )
        .mappings()
        .all()
    )
    return {row["reason_code"]: bool(row["requires_note"]) for row in rows}


async def list_pass_reasons(session: AsyncSession, activity_id: UUID) -> list[dict[str, Any]]:
    reasons = await _allowed_pass_reasons(session, activity_id)
    return [
        {"reason_code": code, "requires_note": requires_note}
        for code, requires_note in reasons.items()
    ]


async def upsert_pass_reason(
    session: AsyncSession, *, activity_id: UUID | None, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    conflict_target = (
        "(activity_id, reason_code) WHERE activity_id IS NOT NULL"
        if activity_id
        else "(reason_code) WHERE activity_id IS NULL"
    )
    await session.execute(
        text(
            "INSERT INTO activity_pass_reason_options "
            "(activity_id,reason_code,sort_order,requires_note,is_active,created_by) "
            "VALUES (:activity_id,:reason_code,:sort_order,:requires_note,:is_active,:actor) "
            f"ON CONFLICT {conflict_target} DO UPDATE SET sort_order=EXCLUDED.sort_order,"
            "requires_note=EXCLUDED.requires_note,is_active=EXCLUDED.is_active,updated_at=now()"
        ),
        {
            "activity_id": str(activity_id) if activity_id else None,
            "reason_code": payload["reason_code"],
            "sort_order": payload["sort_order"],
            "requires_note": payload["requires_note"],
            "is_active": payload["is_active"],
            "actor": str(actor_id),
        },
    )
    await session.commit()
    return {"activity_id": str(activity_id) if activity_id else None, **payload}


# ---------------------------------------------------------------------------
# B09 candidate freeze
# ---------------------------------------------------------------------------


async def _load_attendance(session: AsyncSession, activity_id: UUID) -> list[AttendanceRecord]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT r.user_id, r.id AS registration_id, r.status AS registration_status,"
                    " r.attendance_status,"
                    " COALESCE(p.display_name, 'member-' || left(r.user_id::text, 8)) AS display_name,"
                    " core.gender_code AS gender,"
                    " gm.group_id AS group_id,"
                    " (SELECT max(e.occurred_at) FROM activity_checkin_events e"
                    "    WHERE e.registration_id=r.id AND e.action='check_in') AS checked_in_at,"
                    " EXISTS (SELECT 1 FROM user_roles ur JOIN roles ro ON ro.id=ur.role_id"
                    "    WHERE ur.user_id=r.user_id AND ur.revoked_at IS NULL AND ro.is_system=true) AS is_staff"
                    " FROM activity_registrations r"
                    " LEFT JOIN activity_participant_profiles p"
                    "   ON p.registration_id=r.id"
                    " LEFT JOIN dating_profiles dp ON dp.user_id=r.user_id"
                    " LEFT JOIN dating_profile_core_details core ON core.dating_profile_id=dp.id"
                    " LEFT JOIN activity_group_members gm"
                    "   ON gm.registration_id=r.id AND gm.removed_at IS NULL"
                    " WHERE r.activity_id=:activity_id"
                ),
                {"activity_id": str(activity_id)},
            )
        )
        .mappings()
        .all()
    )
    return [
        AttendanceRecord(
            user_id=UUID(str(row["user_id"])),
            registration_id=UUID(str(row["registration_id"])),
            registration_status=row["registration_status"],
            attendance_status=row["attendance_status"],
            gender=row["gender"],
            checked_in_at=row["checked_in_at"],
            is_staff=bool(row["is_staff"]),
            display_name=row["display_name"],
            group_id=UUID(str(row["group_id"])) if row["group_id"] else None,
        )
        for row in rows
    ]


async def _restricted_pairs(session: AsyncSession, user_ids: list[UUID]) -> dict[UUID, set[UUID]]:
    if not user_ids:
        return {}
    rows = (
        (
            await session.execute(
                text(
                    "SELECT user_a_id,user_b_id FROM activity_interaction_restrictions "
                    "WHERE status='active' AND (user_a_id = ANY(CAST(:ids AS uuid[])) OR user_b_id = ANY(CAST(:ids AS uuid[])))"
                ),
                {"ids": [str(item) for item in user_ids]},
            )
        )
        .mappings()
        .all()
    )
    restricted: dict[UUID, set[UUID]] = {}
    for row in rows:
        first = UUID(str(row["user_a_id"]))
        second = UUID(str(row["user_b_id"]))
        restricted.setdefault(first, set()).add(second)
        restricted.setdefault(second, set()).add(first)
    return restricted


async def freeze_candidates(
    session: AsyncSession, *, activity_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Create and freeze a new candidate snapshot version.

    The activity row is locked for the duration so two administrators pressing
    "freeze" concurrently cannot create two version-1 snapshots.
    """

    candidate_freeze_enabled()
    await session.execute(
        text("SELECT id FROM activities WHERE id=:id FOR UPDATE"), {"id": str(activity_id)}
    )
    existing = (
        (
            await session.execute(
                text(
                    "SELECT id,snapshot_version,status FROM activity_candidate_snapshots "
                    "WHERE activity_id=:activity_id ORDER BY snapshot_version DESC LIMIT 1"
                ),
                {"activity_id": str(activity_id)},
            )
        )
        .mappings()
        .first()
    )
    if existing and existing["status"] == SnapshotStatus.FROZEN:
        if not payload.get("supersede_existing"):
            raise VavError(
                "SNAPSHOT_ALREADY_FROZEN",
                "A frozen candidate snapshot already exists. Pass supersede_existing to replace it.",
                status_code=409,
                details=[{"snapshot_id": str(existing["id"])}],
            )
        try:
            validate_snapshot_transition(existing["status"], SnapshotStatus.SUPERSEDED)
        except PostEventRuleError as error:
            raise _fail(error, status_code=409) from error

    cutoff_at = payload.get("cutoff_at") or _now()
    if cutoff_at.tzinfo is None:
        cutoff_at = cutoff_at.replace(tzinfo=UTC)
    next_version = int(existing["snapshot_version"]) + 1 if existing else 1

    records = await _load_attendance(session, activity_id)
    try:
        decisions = build_candidate_decisions(records, cutoff_at=cutoff_at)
    except PostEventRuleError as error:
        raise _fail(error) from error

    # Carry forward manual exclusions from the superseded version so a
    # correction never silently readmits someone an administrator removed.
    if existing:
        carried = (
            (
                await session.execute(
                    text(
                        "SELECT user_id,exclusion_reason,excluded_by FROM activity_candidate_entries "
                        "WHERE snapshot_id=:snapshot_id AND exclusion_kind='manual'"
                    ),
                    {"snapshot_id": str(existing["id"])},
                )
            )
            .mappings()
            .all()
        )
        carried_map = {UUID(str(row["user_id"])): row for row in carried}
        if carried_map:
            decisions = build_candidate_decisions(
                records,
                cutoff_at=cutoff_at,
                manual_exclusions={
                    user_id: row["exclusion_reason"] for user_id, row in carried_map.items()
                },
            )
    else:
        carried_map = {}

    restricted = await _restricted_pairs(session, [record.user_id for record in records])

    snapshot_id = UUID(
        str(
            await session.scalar(
                text(
                    "INSERT INTO activity_candidate_snapshots "
                    "(activity_id,snapshot_version,status,cutoff_at,frozen_at,frozen_by,considered_count,eligible_count,excluded_count,freeze_note) "
                    "VALUES (:activity_id,:version,'frozen',:cutoff_at,now(),:actor,:considered,:eligible,:excluded,:note) RETURNING id"
                ),
                {
                    "activity_id": str(activity_id),
                    "version": next_version,
                    "cutoff_at": cutoff_at,
                    "actor": str(actor_id),
                    "considered": len(decisions),
                    "eligible": sum(
                        1 for item in decisions if item.eligibility is CandidateEligibility.ELIGIBLE
                    ),
                    "excluded": sum(
                        1 for item in decisions if item.eligibility is CandidateEligibility.EXCLUDED
                    ),
                    "note": payload.get("freeze_note"),
                },
            )
        )
    )

    for decision in decisions:
        carried_row = carried_map.get(decision.user_id)
        await session.execute(
            text(
                "INSERT INTO activity_candidate_entries "
                "(snapshot_id,activity_id,user_id,registration_id,gender,group_id,display_name,"
                "eligibility,exclusion_kind,exclusion_reason,excluded_by,excluded_at,checked_in_at) "
                "VALUES (:snapshot_id,:activity_id,:user_id,:registration_id,:gender,:group_id,:display_name,"
                ":eligibility,:exclusion_kind,:exclusion_reason,:excluded_by,:excluded_at,:checked_in_at)"
            ),
            {
                "snapshot_id": str(snapshot_id),
                "activity_id": str(activity_id),
                "user_id": str(decision.user_id),
                "registration_id": str(decision.registration_id),
                "gender": decision.gender,
                "group_id": str(decision.group_id) if decision.group_id else None,
                "display_name": decision.display_name,
                "eligibility": decision.eligibility.value,
                "exclusion_kind": (
                    decision.exclusion_kind.value if decision.exclusion_kind else None
                ),
                "exclusion_reason": decision.exclusion_reason,
                "excluded_by": (
                    str(carried_row["excluded_by"])
                    if carried_row is not None
                    else (
                        str(actor_id) if decision.exclusion_kind is ExclusionKind.MANUAL else None
                    )
                ),
                "excluded_at": (
                    _now() if decision.exclusion_kind is ExclusionKind.MANUAL else None
                ),
                "checked_in_at": next(
                    (
                        record.checked_in_at
                        for record in records
                        if record.user_id == decision.user_id
                    ),
                    None,
                ),
            },
        )

    if existing:
        await session.execute(
            text(
                "UPDATE activity_candidate_snapshots SET status='superseded',superseded_at=now(),"
                "superseded_by_snapshot_id=:new_id,updated_at=now() WHERE id=:old_id"
            ),
            {"new_id": str(snapshot_id), "old_id": str(existing["id"])},
        )

    await _audit(
        session,
        activity_id=activity_id,
        snapshot_id=snapshot_id,
        actor_id=actor_id,
        actor_kind="admin",
        action="candidates.frozen",
        reason=payload.get("freeze_note"),
        metadata={
            "snapshot_version": next_version,
            "cutoff_at": cutoff_at.isoformat(),
            "considered": len(decisions),
            "superseded_snapshot_id": str(existing["id"]) if existing else None,
            "restricted_pairs": len(restricted),
        },
    )
    await _publish(
        session,
        "activity.candidates.frozen.v1",
        "activity_candidate_snapshot",
        snapshot_id,
        {
            "activity_id": str(activity_id),
            "snapshot_id": str(snapshot_id),
            "snapshot_version": next_version,
            "eligible_count": sum(
                1 for item in decisions if item.eligibility is CandidateEligibility.ELIGIBLE
            ),
        },
    )
    await session.commit()
    return await get_snapshot(session, snapshot_id)


async def get_snapshot(session: AsyncSession, snapshot_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,snapshot_version,status,cutoff_at,frozen_at,frozen_by,"
                    "considered_count,eligible_count,excluded_count,freeze_note,superseded_at,"
                    "superseded_by_snapshot_id FROM activity_candidate_snapshots WHERE id=:id"
                ),
                {"id": str(snapshot_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("SNAPSHOT_NOT_FOUND", "Candidate snapshot not found.", status_code=404)
    return {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}


async def _active_snapshot(session: AsyncSession, activity_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,snapshot_version,status,cutoff_at FROM activity_candidate_snapshots "
                    "WHERE activity_id=:activity_id AND status='frozen'"
                ),
                {"activity_id": str(activity_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "SNAPSHOT_NOT_FROZEN",
            "The candidate list for this activity has not been frozen yet.",
            status_code=409,
        )
    return dict(row)


async def list_snapshot_entries(
    session: AsyncSession, snapshot_id: UUID, *, include_excluded: bool = True
) -> list[dict[str, Any]]:
    clause = "" if include_excluded else " AND eligibility='eligible'"
    rows = (
        (
            await session.execute(
                text(
                    "SELECT user_id,registration_id,display_name,gender,group_id,eligibility,"
                    "exclusion_kind,exclusion_reason,excluded_by,excluded_at,checked_in_at "
                    "FROM activity_candidate_entries WHERE snapshot_id=:snapshot_id"
                    + clause
                    + " ORDER BY eligibility, display_name"
                ),
                {"snapshot_id": str(snapshot_id)},
            )
        )
        .mappings()
        .all()
    )
    return [
        {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
        for row in rows
    ]


async def exclude_candidate(
    session: AsyncSession, *, snapshot_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Administratively exclude one candidate from a frozen snapshot.

    Raw attendance data is untouched: only the snapshot entry flips, and the
    reason plus actor are stored on the row and in the audit trail.
    """

    candidate_freeze_enabled()
    snapshot = await get_snapshot(session, snapshot_id)
    if snapshot["status"] != SnapshotStatus.FROZEN:
        raise VavError(
            "SNAPSHOT_NOT_FROZEN", "Only a frozen snapshot can be adjusted.", status_code=409
        )
    try:
        reason = require_manual_exclusion_reason(payload.get("reason"))
    except PostEventRuleError as error:
        raise _fail(error) from error
    updated = await session.execute(
        text(
            "UPDATE activity_candidate_entries SET eligibility='excluded',exclusion_kind='manual',"
            "exclusion_reason=:reason,excluded_by=:actor,excluded_at=now() "
            "WHERE snapshot_id=:snapshot_id AND user_id=:user_id AND eligibility='eligible'"
        ),
        {
            "reason": reason,
            "actor": str(actor_id),
            "snapshot_id": str(snapshot_id),
            "user_id": str(payload["user_id"]),
        },
    )
    if int(getattr(updated, "rowcount", 0) or 0) == 0:
        raise VavError(
            "CANDIDATE_NOT_ELIGIBLE",
            "That member is not an eligible candidate in this snapshot.",
            status_code=409,
        )
    await _recount_snapshot(session, snapshot_id)
    # Any selection already pointing at the excluded member is withdrawn so a
    # frozen-but-excluded person cannot end up in a mutual pair.
    await session.execute(
        text(
            "DELETE FROM activity_selection_items WHERE chosen_user_id=:user_id AND submission_id IN "
            "(SELECT id FROM activity_selection_submissions WHERE snapshot_id=:snapshot_id)"
        ),
        {"user_id": str(payload["user_id"]), "snapshot_id": str(snapshot_id)},
    )
    await session.execute(
        text(
            "UPDATE activity_selection_submissions s SET selection_count="
            "(SELECT count(*) FROM activity_selection_items i WHERE i.submission_id=s.id),updated_at=now() "
            "WHERE s.snapshot_id=:snapshot_id"
        ),
        {"snapshot_id": str(snapshot_id)},
    )
    await _audit(
        session,
        activity_id=UUID(str(snapshot["activity_id"])),
        snapshot_id=snapshot_id,
        actor_id=actor_id,
        actor_kind="admin",
        action="candidate.excluded",
        subject_user_id=UUID(str(payload["user_id"])),
        reason=reason,
    )
    await session.commit()
    return {"snapshot_id": str(snapshot_id), "user_id": str(payload["user_id"]), "reason": reason}


async def restore_candidate(
    session: AsyncSession, *, snapshot_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Undo a manual exclusion. Only manual exclusions can be undone."""

    candidate_freeze_enabled()
    try:
        reason = require_manual_exclusion_reason(payload.get("reason"))
    except PostEventRuleError as error:
        raise _fail(error) from error
    snapshot = await get_snapshot(session, snapshot_id)
    updated = await session.execute(
        text(
            "UPDATE activity_candidate_entries SET eligibility='eligible',exclusion_kind=NULL,"
            "exclusion_reason=NULL,excluded_by=NULL,excluded_at=NULL "
            "WHERE snapshot_id=:snapshot_id AND user_id=:user_id AND exclusion_kind='manual'"
        ),
        {"snapshot_id": str(snapshot_id), "user_id": str(payload["user_id"])},
    )
    if int(getattr(updated, "rowcount", 0) or 0) == 0:
        raise VavError(
            "CANDIDATE_NOT_MANUALLY_EXCLUDED",
            "Only a manual exclusion can be restored; attendance-based exclusions are facts.",
            status_code=409,
        )
    await _recount_snapshot(session, snapshot_id)
    await _audit(
        session,
        activity_id=UUID(str(snapshot["activity_id"])),
        snapshot_id=snapshot_id,
        actor_id=actor_id,
        actor_kind="admin",
        action="candidate.restored",
        subject_user_id=UUID(str(payload["user_id"])),
        reason=reason,
    )
    await session.commit()
    return {"snapshot_id": str(snapshot_id), "user_id": str(payload["user_id"])}


async def _recount_snapshot(session: AsyncSession, snapshot_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE activity_candidate_snapshots SET "
            "eligible_count=(SELECT count(*) FROM activity_candidate_entries WHERE snapshot_id=:id AND eligibility='eligible'),"
            "excluded_count=(SELECT count(*) FROM activity_candidate_entries WHERE snapshot_id=:id AND eligibility='excluded'),"
            "updated_at=now() WHERE id=:id"
        ),
        {"id": str(snapshot_id)},
    )


# ---------------------------------------------------------------------------
# B09 member-facing candidate list and selection
# ---------------------------------------------------------------------------


async def _chooser_entry(session: AsyncSession, snapshot_id: UUID, user_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT user_id,gender,eligibility FROM activity_candidate_entries "
                    "WHERE snapshot_id=:snapshot_id AND user_id=:user_id"
                ),
                {"snapshot_id": str(snapshot_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["eligibility"] != CandidateEligibility.ELIGIBLE:
        # A no-show must not learn who attended, so this is 403 rather than 404.
        raise VavError(
            "SELECTION_NOT_ELIGIBLE",
            "You are not an eligible participant for this activity's mutual selection.",
            status_code=403,
        )
    return dict(row)


async def list_visible_candidates(
    session: AsyncSession, *, activity_id: UUID, user_id: UUID
) -> dict[str, Any]:
    candidate_freeze_enabled()
    snapshot = await _active_snapshot(session, activity_id)
    snapshot_id = UUID(str(snapshot["id"]))
    chooser = await _chooser_entry(session, snapshot_id, user_id)
    policy = await _load_policy(session, activity_id)
    restricted = (await _restricted_pairs(session, [user_id])).get(user_id, set())
    entries = await list_snapshot_entries(session, snapshot_id, include_excluded=False)
    visible = [
        {
            "user_id": entry["user_id"],
            "display_name": entry["display_name"],
            "group_id": entry["group_id"],
        }
        for entry in entries
        if is_visible_candidate(
            policy,
            chooser_id=user_id,
            chooser_gender=chooser["gender"],
            candidate_id=UUID(str(entry["user_id"])),
            candidate_gender=entry["gender"],
            restricted_with=restricted,
        )
    ]
    return {
        "snapshot_id": str(snapshot_id),
        "snapshot_version": snapshot["snapshot_version"],
        "max_selections": policy.max_selections,
        "min_selections": policy.min_selections,
        "edit_window_hours": policy.edit_window_hours,
        "pass_reasons": await list_pass_reasons(session, activity_id),
        "candidates": visible,
    }


async def submit_selection(
    session: AsyncSession, *, activity_id: UUID, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Create or replace a member's mutual-selection submission.

    Locks the submission row before validating so a double-tap cannot produce
    two rows or two versions.
    """

    candidate_freeze_enabled()
    snapshot = await _active_snapshot(session, activity_id)
    snapshot_id = UUID(str(snapshot["id"]))
    chooser = await _chooser_entry(session, snapshot_id, user_id)
    policy = await _load_policy(session, activity_id)

    existing = (
        (
            await session.execute(
                text(
                    "SELECT id,status,submitted_at,version FROM activity_selection_submissions "
                    "WHERE snapshot_id=:snapshot_id AND chooser_user_id=:user_id FOR UPDATE"
                ),
                {"snapshot_id": str(snapshot_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    now = _now()
    if existing and existing["status"] == "submitted":
        try:
            ensure_selection_editable(policy, submitted_at=existing["submitted_at"], now=now)
        except PostEventRuleError as error:
            raise _fail(error, status_code=409) from error

    restricted = (await _restricted_pairs(session, [user_id])).get(user_id, set())
    entries = await list_snapshot_entries(session, snapshot_id, include_excluded=False)
    visible_ids = [
        UUID(str(entry["user_id"]))
        for entry in entries
        if is_visible_candidate(
            policy,
            chooser_id=user_id,
            chooser_gender=chooser["gender"],
            candidate_id=UUID(str(entry["user_id"])),
            candidate_gender=entry["gender"],
            restricted_with=restricted,
        )
    ]
    reasons = await _allowed_pass_reasons(session, activity_id)
    reason_code = payload.get("no_selection_reason_code")
    is_submit = payload.get("status", "submitted") == "submitted"

    if is_submit:
        try:
            ordered = validate_selection(
                policy,
                chooser_id=user_id,
                selected_ids=list(payload.get("selected_user_ids") or []),
                visible_ids=visible_ids,
                no_selection_reason_code=reason_code,
                allowed_reason_codes=reasons.keys(),
                reason_note=payload.get("no_selection_reason_note"),
                reason_requires_note=reasons.get(reason_code or "", False),
            )
        except PostEventRuleError as error:
            raise _fail(error) from error
    else:
        # A draft is not yet a decision; only obviously impossible entries are
        # rejected so autosave never blocks the member mid-thought.
        ordered = [
            item for item in (payload.get("selected_user_ids") or []) if item in visible_ids
        ][: policy.max_selections]

    note = payload.get("no_selection_reason_note")
    encrypted_note = encrypt_private(note) if note else None
    editable_until = (
        now + timedelta(hours=policy.edit_window_hours)
        if is_submit and policy.allow_edit_after_submit
        else None
    )

    if existing:
        submission_id = UUID(str(existing["id"]))
        await session.execute(
            text(
                "UPDATE activity_selection_submissions SET status=:status,selection_count=:count,"
                "no_selection_reason_code=:reason_code,no_selection_reason_note=:note,"
                "submitted_at=CASE WHEN :is_submit THEN COALESCE(submitted_at, now()) ELSE submitted_at END,"
                "editable_until=:editable_until,version=version+1,updated_at=now() WHERE id=:id"
            ),
            {
                "status": "submitted" if is_submit else "draft",
                "count": len(ordered),
                "reason_code": reason_code if not ordered else None,
                "note": encrypted_note if not ordered else None,
                "is_submit": is_submit,
                "editable_until": editable_until,
                "id": str(submission_id),
            },
        )
        await session.execute(
            text("DELETE FROM activity_selection_items WHERE submission_id=:id"),
            {"id": str(submission_id)},
        )
    else:
        submission_id = UUID(
            str(
                await session.scalar(
                    text(
                        "INSERT INTO activity_selection_submissions "
                        "(snapshot_id,activity_id,chooser_user_id,status,selection_count,"
                        "no_selection_reason_code,no_selection_reason_note,submitted_at,editable_until) "
                        "VALUES (:snapshot_id,:activity_id,:user_id,:status,:count,:reason_code,:note,"
                        "CASE WHEN :is_submit THEN now() ELSE NULL END,:editable_until) RETURNING id"
                    ),
                    {
                        "snapshot_id": str(snapshot_id),
                        "activity_id": str(activity_id),
                        "user_id": str(user_id),
                        "status": "submitted" if is_submit else "draft",
                        "count": len(ordered),
                        "reason_code": reason_code if not ordered else None,
                        "note": encrypted_note if not ordered else None,
                        "is_submit": is_submit,
                        "editable_until": editable_until,
                    },
                )
            )
        )

    for rank, chosen_id in enumerate(ordered, start=1):
        await session.execute(
            text(
                "INSERT INTO activity_selection_items (submission_id,chosen_user_id,rank) "
                "VALUES (:submission_id,:chosen_user_id,:rank)"
            ),
            {
                "submission_id": str(submission_id),
                "chosen_user_id": str(chosen_id),
                "rank": rank,
            },
        )

    await _audit(
        session,
        activity_id=activity_id,
        snapshot_id=snapshot_id,
        actor_id=user_id,
        actor_kind="member",
        action="selection.submitted" if is_submit else "selection.saved",
        # The chosen identities are deliberately absent: the audit trail records
        # that a decision happened, not who was picked.
        metadata={"selection_count": len(ordered), "has_reason": bool(reason_code)},
    )
    if is_submit:
        await _publish(
            session,
            "activity.selection.submitted.v1",
            "activity_selection_submission",
            submission_id,
            {
                "activity_id": str(activity_id),
                "snapshot_id": str(snapshot_id),
                "submission_id": str(submission_id),
            },
        )
    await session.commit()
    return await get_my_selection(session, activity_id=activity_id, user_id=user_id)


async def get_my_selection(
    session: AsyncSession, *, activity_id: UUID, user_id: UUID
) -> dict[str, Any]:
    snapshot = await _active_snapshot(session, activity_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,status,selection_count,no_selection_reason_code,no_selection_reason_note,"
                    "submitted_at,editable_until,version FROM activity_selection_submissions "
                    "WHERE snapshot_id=:snapshot_id AND chooser_user_id=:user_id"
                ),
                {"snapshot_id": str(snapshot["id"]), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return {
            "snapshot_id": str(snapshot["id"]),
            "status": "not_started",
            "selected_user_ids": [],
        }
    items = (
        (
            await session.execute(
                text(
                    "SELECT chosen_user_id FROM activity_selection_items "
                    "WHERE submission_id=:id ORDER BY rank"
                ),
                {"id": str(row["id"])},
            )
        )
        .scalars()
        .all()
    )
    return {
        "snapshot_id": str(snapshot["id"]),
        "submission_id": str(row["id"]),
        "status": row["status"],
        "selection_count": row["selection_count"],
        "selected_user_ids": [str(item) for item in items],
        "no_selection_reason_code": row["no_selection_reason_code"],
        "no_selection_reason_note": (
            decrypt_private(row["no_selection_reason_note"])
            if row["no_selection_reason_note"]
            else None
        ),
        "submitted_at": row["submitted_at"],
        "editable_until": row["editable_until"],
        "version": row["version"],
    }


async def compute_matches(session: AsyncSession, snapshot_id: UUID) -> list[tuple[UUID, UUID]]:
    """Derive mutual pairs from submitted selections in the frozen snapshot."""

    rows = (
        (
            await session.execute(
                text(
                    "SELECT s.chooser_user_id, i.chosen_user_id FROM activity_selection_submissions s "
                    "JOIN activity_selection_items i ON i.submission_id=s.id "
                    "WHERE s.snapshot_id=:snapshot_id AND s.status='submitted'"
                ),
                {"snapshot_id": str(snapshot_id)},
            )
        )
        .mappings()
        .all()
    )
    submissions: dict[UUID, list[UUID]] = {}
    for row in rows:
        submissions.setdefault(UUID(str(row["chooser_user_id"])), []).append(
            UUID(str(row["chosen_user_id"]))
        )
    # Members who submitted "nobody" still count as having submitted, which
    # matters for the no-match letter outcome below.
    empty = (
        (
            await session.execute(
                text(
                    "SELECT chooser_user_id FROM activity_selection_submissions "
                    "WHERE snapshot_id=:snapshot_id AND status='submitted' AND selection_count=0"
                ),
                {"snapshot_id": str(snapshot_id)},
            )
        )
        .scalars()
        .all()
    )
    for user_id in empty:
        submissions.setdefault(UUID(str(user_id)), [])
    return compute_mutual_pairs(submissions)


# ---------------------------------------------------------------------------
# B10 survey definitions
# ---------------------------------------------------------------------------


def _question_spec(row: dict[str, Any]) -> QuestionSpec:
    """Rehydrate a frozen question row into its validated pure form."""

    config = row["config"] or {}
    return QuestionSpec(
        question_id=UUID(str(row["id"])),
        question_code=row["question_code"],
        question_type=QuestionType(row["question_type"]),
        is_required=bool(row["is_required"]),
        position=int(row["position"]),
        scale_min=int(config.get("scale_min", 1)),
        scale_max=int(config.get("scale_max", 5)),
        options=tuple(config.get("options", ())),
        max_length=int(config.get("max_length", 2000)),
        min_selections=int(config.get("min_selections", 1)),
        max_selections=int(config.get("max_selections", 1)),
        per_subject=bool(row["per_subject"]),
    )


async def create_survey_definition(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Create a draft survey version with its questions.

    Ships no production questionnaire content: the code creates the structure,
    an editor supplies the wording. That keeps DEC-003 honest.
    """

    survey_enabled()
    try:
        definition_id = UUID(
            str(
                await session.scalar(
                    text(
                        "INSERT INTO survey_definitions "
                        "(survey_code,semantic_version,scope,title,description,default_locale,status,created_by) "
                        "VALUES (:code,:version,:scope,:title,:description,:locale,'draft',:actor) RETURNING id"
                    ),
                    {
                        "code": payload["survey_code"],
                        "version": payload["semantic_version"],
                        "scope": payload["scope"],
                        "title": payload["title"],
                        "description": payload.get("description"),
                        "locale": payload["default_locale"],
                        "actor": str(actor_id),
                    },
                )
            )
        )
    except IntegrityError as error:
        await session.rollback()
        raise VavError(
            "SURVEY_VERSION_EXISTS",
            "That survey code and version already exist.",
            status_code=409,
        ) from error

    for question in payload["questions"]:
        question_id = UUID(
            str(
                await session.scalar(
                    text(
                        "INSERT INTO survey_questions "
                        "(definition_id,question_code,question_type,prompt,help_text,is_required,per_subject,position,config) "
                        "VALUES (:definition_id,:code,:type,:prompt,:help_text,:required,:per_subject,:position,CAST(:config AS jsonb)) RETURNING id"
                    ),
                    {
                        "definition_id": str(definition_id),
                        "code": question["question_code"],
                        "type": question["question_type"],
                        "prompt": question["prompt"],
                        "help_text": question.get("help_text"),
                        "required": question["is_required"],
                        "per_subject": question["per_subject"],
                        "position": question["position"],
                        "config": _json(question.get("config") or {}),
                    },
                )
            )
        )
        # Validate the stored shape immediately so a broken scale or an empty
        # option list is caught at authoring time rather than at member submit.
        try:
            _question_spec(
                {
                    "id": question_id,
                    "question_code": question["question_code"],
                    "question_type": question["question_type"],
                    "is_required": question["is_required"],
                    "per_subject": question["per_subject"],
                    "position": question["position"],
                    "config": question.get("config") or {},
                }
            )
        except PostEventRuleError as error:
            await session.rollback()
            raise _fail(error) from error

    await session.commit()
    return await get_survey_definition(session, definition_id)


async def get_survey_definition(session: AsyncSession, definition_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,survey_code,semantic_version,scope,title,description,default_locale,"
                    "status,published_at FROM survey_definitions WHERE id=:id"
                ),
                {"id": str(definition_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("SURVEY_NOT_FOUND", "Survey definition not found.", status_code=404)
    questions = (
        (
            await session.execute(
                text(
                    "SELECT id,question_code,question_type,prompt,help_text,is_required,per_subject,"
                    "position,config FROM survey_questions WHERE definition_id=:id ORDER BY position"
                ),
                {"id": str(definition_id)},
            )
        )
        .mappings()
        .all()
    )
    return {
        **{key: str(value) if isinstance(value, UUID) else value for key, value in row.items()},
        "questions": [
            {key: str(value) if isinstance(value, UUID) else value for key, value in item.items()}
            for item in questions
        ],
    }


async def publish_survey_definition(
    session: AsyncSession, *, definition_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    """Publish a draft. Published versions are frozen: edits require a new version."""

    survey_enabled()
    updated = await session.execute(
        text(
            "UPDATE survey_definitions SET status='published',published_at=now(),published_by=:actor,"
            "updated_at=now() WHERE id=:id AND status='draft'"
        ),
        {"id": str(definition_id), "actor": str(actor_id)},
    )
    if int(getattr(updated, "rowcount", 0) or 0) == 0:
        raise VavError(
            "SURVEY_NOT_DRAFT",
            "Only a draft survey version can be published.",
            status_code=409,
        )
    await session.commit()
    return await get_survey_definition(session, definition_id)


async def assign_survey(
    session: AsyncSession, *, activity_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Bind a published survey version to an activity and generate member tasks."""

    survey_enabled()
    definition = await get_survey_definition(session, UUID(str(payload["definition_id"])))
    if definition["status"] != "published":
        raise VavError(
            "SURVEY_NOT_PUBLISHED",
            "Only a published survey version can be assigned to an activity.",
            status_code=409,
        )
    deadline_at = payload["deadline_at"]
    if deadline_at.tzinfo is None:
        deadline_at = deadline_at.replace(tzinfo=UTC)
    opens_at = payload.get("opens_at")
    if opens_at is not None and opens_at.tzinfo is None:
        opens_at = opens_at.replace(tzinfo=UTC)

    snapshot_id = payload.get("snapshot_id")
    if snapshot_id is None:
        snapshot = (
            (
                await session.execute(
                    text(
                        "SELECT id FROM activity_candidate_snapshots "
                        "WHERE activity_id=:activity_id AND status='frozen'"
                    ),
                    {"activity_id": str(activity_id)},
                )
            )
            .mappings()
            .first()
        )
        snapshot_id = snapshot["id"] if snapshot else None

    assignment_id = UUID(
        str(
            await session.scalar(
                text(
                    "INSERT INTO activity_survey_assignments "
                    "(activity_id,definition_id,snapshot_id,status,opens_at,deadline_at,display_timezone,reminder_offsets_hours,created_by) "
                    "VALUES (:activity_id,:definition_id,:snapshot_id,'scheduled',:opens_at,:deadline_at,:tz,CAST(:offsets AS jsonb),:actor) "
                    "ON CONFLICT (activity_id, definition_id) DO UPDATE SET opens_at=EXCLUDED.opens_at,"
                    "deadline_at=EXCLUDED.deadline_at,display_timezone=EXCLUDED.display_timezone,"
                    "reminder_offsets_hours=EXCLUDED.reminder_offsets_hours,updated_at=now() RETURNING id"
                ),
                {
                    "activity_id": str(activity_id),
                    "definition_id": str(payload["definition_id"]),
                    "snapshot_id": str(snapshot_id) if snapshot_id else None,
                    "opens_at": opens_at,
                    "deadline_at": deadline_at,
                    "tz": payload["display_timezone"],
                    "offsets": _json(payload["reminder_offsets_hours"]),
                    "actor": str(actor_id),
                },
            )
        )
    )
    created = await generate_survey_tasks(session, assignment_id=assignment_id, commit=False)
    await session.commit()
    return {
        "assignment_id": str(assignment_id),
        "activity_id": str(activity_id),
        "definition_id": str(payload["definition_id"]),
        "snapshot_id": str(snapshot_id) if snapshot_id else None,
        "deadline_at": deadline_at,
        "tasks_created": created,
    }


async def generate_survey_tasks(
    session: AsyncSession, *, assignment_id: UUID, commit: bool = True
) -> int:
    """Create one task per eligible member. Idempotent: re-running adds nothing."""

    assignment = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,deadline_at FROM activity_survey_assignments WHERE id=:id"
                ),
                {"id": str(assignment_id)},
            )
        )
        .mappings()
        .first()
    )
    if assignment is None:
        raise VavError(
            "SURVEY_ASSIGNMENT_NOT_FOUND",
            "Survey assignment not found.",
            status_code=404,
        )
    records = await _load_attendance(session, UUID(str(assignment["activity_id"])))
    created = 0
    for record in records:
        if not is_survey_task_eligible(
            registration_status=record.registration_status,
            checked_in_at=record.checked_in_at,
            attendance_status=record.attendance_status,
            is_staff=record.is_staff,
        ):
            continue
        result = await session.execute(
            text(
                "INSERT INTO survey_tasks (assignment_id,activity_id,user_id,status,due_at) "
                "VALUES (:assignment_id,:activity_id,:user_id,'pending',:due_at) "
                "ON CONFLICT (assignment_id, user_id) DO NOTHING"
            ),
            {
                "assignment_id": str(assignment_id),
                "activity_id": str(assignment["activity_id"]),
                "user_id": str(record.user_id),
                "due_at": assignment["deadline_at"],
            },
        )
        created += int(getattr(result, "rowcount", 0) or 0) or 0
    if commit:
        await session.commit()
    return created


async def list_my_survey_tasks(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    survey_enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT t.id,t.assignment_id,t.activity_id,t.status,t.due_at,t.completed_at,"
                    "a.display_timezone,a.opens_at,d.title "
                    "FROM survey_tasks t "
                    "JOIN activity_survey_assignments a ON a.id=t.assignment_id "
                    "JOIN survey_definitions d ON d.id=a.definition_id "
                    "WHERE t.user_id=:user_id AND t.status <> 'waived' "
                    "ORDER BY t.status='completed', t.due_at"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .all()
    )
    return [
        {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
        for row in rows
    ]


async def get_survey_for_member(
    session: AsyncSession, *, assignment_id: UUID, user_id: UUID
) -> dict[str, Any]:
    survey_enabled()
    assignment = await _member_assignment(session, assignment_id, user_id)
    definition = await get_survey_definition(session, UUID(str(assignment["definition_id"])))
    subjects = await _survey_subjects(session, assignment, user_id)
    response = (
        (
            await session.execute(
                text(
                    "SELECT id,status,submitted_at,last_edited_at,edit_count FROM survey_responses "
                    "WHERE assignment_id=:assignment_id AND user_id=:user_id"
                ),
                {"assignment_id": str(assignment_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    answers: list[dict[str, Any]] = []
    if response is not None:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT q.question_code,a.rating_value,a.boolean_value,a.choice_values,"
                        "a.text_value_encrypted,a.subject_user_id FROM survey_answers a "
                        "JOIN survey_questions q ON q.id=a.question_id WHERE a.response_id=:id"
                    ),
                    {"id": str(response["id"])},
                )
            )
            .mappings()
            .all()
        )
        answers = [
            {
                "question_code": row["question_code"],
                "rating_value": row["rating_value"],
                "boolean_value": row["boolean_value"],
                "choice_values": row["choice_values"],
                "text_value": (
                    decrypt_private(row["text_value_encrypted"])
                    if row["text_value_encrypted"]
                    else None
                ),
                "subject_user_id": (
                    str(row["subject_user_id"]) if row["subject_user_id"] else None
                ),
            }
            for row in rows
        ]
    return {
        "assignment_id": str(assignment_id),
        "activity_id": str(assignment["activity_id"]),
        "definition": definition,
        "opens_at": assignment["opens_at"],
        "deadline_at": assignment["deadline_at"],
        "display_timezone": assignment["display_timezone"],
        "subjects": subjects,
        "response": (
            {
                "status": response["status"],
                "submitted_at": response["submitted_at"],
                "edit_count": response["edit_count"],
                "answers": answers,
            }
            if response is not None
            else None
        ),
    }


async def _member_assignment(
    session: AsyncSession, assignment_id: UUID, user_id: UUID
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT a.id,a.activity_id,a.definition_id,a.snapshot_id,a.opens_at,a.deadline_at,"
                    "a.display_timezone,t.id AS task_id,t.status AS task_status "
                    "FROM activity_survey_assignments a "
                    "JOIN survey_tasks t ON t.assignment_id=a.id AND t.user_id=:user_id "
                    "WHERE a.id=:assignment_id"
                ),
                {"assignment_id": str(assignment_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        # No task means this member was not eligible; do not disclose that the
        # survey exists at all.
        raise VavError("SURVEY_TASK_NOT_FOUND", "No survey task for this member.", status_code=404)
    return dict(row)


async def _survey_subjects(
    session: AsyncSession, assignment: dict[str, Any], user_id: UUID
) -> list[dict[str, Any]]:
    """The people this member may rate: the frozen visible candidate list."""

    if not assignment.get("snapshot_id"):
        return []
    activity_id = UUID(str(assignment["activity_id"]))
    snapshot_id = UUID(str(assignment["snapshot_id"]))
    policy = await _load_policy(session, activity_id)
    chooser = (
        (
            await session.execute(
                text(
                    "SELECT gender FROM activity_candidate_entries "
                    "WHERE snapshot_id=:snapshot_id AND user_id=:user_id"
                ),
                {"snapshot_id": str(snapshot_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if chooser is None:
        return []
    restricted = (await _restricted_pairs(session, [user_id])).get(user_id, set())
    entries = await list_snapshot_entries(session, snapshot_id, include_excluded=False)
    return [
        {"user_id": entry["user_id"], "display_name": entry["display_name"]}
        for entry in entries
        if is_visible_candidate(
            policy,
            chooser_id=user_id,
            chooser_gender=chooser["gender"],
            candidate_id=UUID(str(entry["user_id"])),
            candidate_gender=entry["gender"],
            restricted_with=restricted,
        )
    ]


async def save_survey_response(
    session: AsyncSession, *, assignment_id: UUID, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Autosave a draft or submit a survey response.

    Editing after submit is allowed until the deadline; after the deadline only
    an audited administrative reopen can change anything.
    """

    survey_enabled()
    assignment = await _member_assignment(session, assignment_id, user_id)
    now = _now()
    is_submit = payload.get("status", "submitted") == "submitted"
    try:
        ensure_survey_open(
            opens_at=assignment["opens_at"], deadline_at=assignment["deadline_at"], now=now
        )
    except PostEventRuleError as error:
        raise _fail(error, status_code=409) from error

    definition_id = UUID(str(assignment["definition_id"]))
    question_rows = (
        (
            await session.execute(
                text(
                    "SELECT id,question_code,question_type,is_required,per_subject,position,config "
                    "FROM survey_questions WHERE definition_id=:id ORDER BY position"
                ),
                {"id": str(definition_id)},
            )
        )
        .mappings()
        .all()
    )
    questions = [_question_spec(dict(row)) for row in question_rows]
    by_code = {question.question_code: question for question in questions}
    subjects = [
        UUID(str(item["user_id"])) for item in await _survey_subjects(session, assignment, user_id)
    ]

    submitted = [
        SubmittedAnswer(
            question_code=answer["question_code"],
            rating_value=answer.get("rating_value"),
            choice_values=tuple(answer.get("choice_values") or ()),
            text_value=answer.get("text_value"),
            boolean_value=answer.get("boolean_value"),
            subject_user_id=(
                UUID(str(answer["subject_user_id"])) if answer.get("subject_user_id") else None
            ),
        )
        for answer in payload["answers"]
    ]
    try:
        validate_answers(questions, submitted, subject_user_ids=subjects, partial=not is_submit)
    except PostEventRuleError as error:
        raise _fail(error) from error

    existing = (
        (
            await session.execute(
                text(
                    "SELECT id,status FROM survey_responses "
                    "WHERE assignment_id=:assignment_id AND user_id=:user_id FOR UPDATE"
                ),
                {"assignment_id": str(assignment_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if existing:
        response_id = UUID(str(existing["id"]))
        await session.execute(
            text(
                "UPDATE survey_responses SET status=:status,last_edited_at=now(),"
                "edit_count=edit_count+1,version=version+1,updated_at=now(),"
                "submitted_at=CASE WHEN :is_submit THEN COALESCE(submitted_at, now()) ELSE submitted_at END "
                "WHERE id=:id"
            ),
            {
                "status": "submitted" if is_submit else existing["status"],
                "is_submit": is_submit,
                "id": str(response_id),
            },
        )
        await session.execute(
            text("DELETE FROM survey_answers WHERE response_id=:id"), {"id": str(response_id)}
        )
    else:
        response_id = UUID(
            str(
                await session.scalar(
                    text(
                        "INSERT INTO survey_responses (assignment_id,definition_id,user_id,status,submitted_at) "
                        "VALUES (:assignment_id,:definition_id,:user_id,:status,"
                        "CASE WHEN :is_submit THEN now() ELSE NULL END) RETURNING id"
                    ),
                    {
                        "assignment_id": str(assignment_id),
                        "definition_id": str(definition_id),
                        "user_id": str(user_id),
                        "status": "submitted" if is_submit else "draft",
                        "is_submit": is_submit,
                    },
                )
            )
        )

    for answer in submitted:
        question = by_code[answer.question_code]
        await session.execute(
            text(
                "INSERT INTO survey_answers (response_id,question_id,subject_user_id,subject_key,"
                "rating_value,boolean_value,choice_values,text_value_encrypted) "
                "VALUES (:response_id,:question_id,:subject_user_id,:subject_key,:rating_value,"
                ":boolean_value,CAST(:choice_values AS jsonb),:text_value)"
            ),
            {
                "response_id": str(response_id),
                "question_id": str(question.question_id),
                "subject_user_id": (
                    str(answer.subject_user_id) if answer.subject_user_id else None
                ),
                "subject_key": str(answer.subject_user_id) if answer.subject_user_id else "-",
                "rating_value": answer.rating_value,
                "boolean_value": answer.boolean_value,
                "choice_values": _json(list(answer.choice_values)),
                "text_value": (encrypt_private(answer.text_value) if answer.text_value else None),
            },
        )

    if is_submit:
        await session.execute(
            text(
                "UPDATE survey_tasks SET status='completed',completed_at=now(),updated_at=now() "
                "WHERE id=:task_id"
            ),
            {"task_id": str(assignment["task_id"])},
        )
        # Suppress every reminder that has not gone out yet.
        await session.execute(
            text(
                "UPDATE survey_reminder_dispatches SET status='suppressed' "
                "WHERE task_id=:task_id AND status='scheduled'"
            ),
            {"task_id": str(assignment["task_id"])},
        )
        await _publish(
            session,
            "activity.survey.completed.v1",
            "survey_response",
            response_id,
            {
                "assignment_id": str(assignment_id),
                "activity_id": str(assignment["activity_id"]),
            },
        )
    else:
        await session.execute(
            text(
                "UPDATE survey_tasks SET status='in_progress',updated_at=now() "
                "WHERE id=:task_id AND status='pending'"
            ),
            {"task_id": str(assignment["task_id"])},
        )
    await session.commit()
    return await get_survey_for_member(session, assignment_id=assignment_id, user_id=user_id)


async def reopen_survey_response(
    session: AsyncSession,
    *,
    assignment_id: UUID,
    user_id: UUID,
    actor_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Audited administrative override of a passed deadline (SUR-001)."""

    survey_enabled()
    updated = await session.execute(
        text(
            "UPDATE survey_responses SET status='draft',override_by=:actor,override_reason=:reason,"
            "updated_at=now() WHERE assignment_id=:assignment_id AND user_id=:user_id"
        ),
        {
            "actor": str(actor_id),
            "reason": payload["reason"],
            "assignment_id": str(assignment_id),
            "user_id": str(user_id),
        },
    )
    if int(getattr(updated, "rowcount", 0) or 0) == 0:
        raise VavError("SURVEY_RESPONSE_NOT_FOUND", "No response to reopen.", status_code=404)
    if payload.get("new_deadline_at"):
        await session.execute(
            text(
                "UPDATE activity_survey_assignments SET deadline_at=:deadline,updated_at=now() WHERE id=:id"
            ),
            {"deadline": payload["new_deadline_at"], "id": str(assignment_id)},
        )
    await session.execute(
        text(
            "UPDATE survey_tasks SET status='pending',completed_at=NULL,updated_at=now() "
            "WHERE assignment_id=:assignment_id AND user_id=:user_id"
        ),
        {"assignment_id": str(assignment_id), "user_id": str(user_id)},
    )
    await session.commit()
    return {"assignment_id": str(assignment_id), "user_id": str(user_id), "status": "reopened"}


async def schedule_survey_reminders(session: AsyncSession, assignment_id: UUID) -> int:
    """Materialize reminder slots. Safe to re-run: the dedupe key is unique."""

    survey_enabled()
    assignment = (
        (
            await session.execute(
                text(
                    "SELECT id,deadline_at,reminder_offsets_hours FROM activity_survey_assignments WHERE id=:id"
                ),
                {"id": str(assignment_id)},
            )
        )
        .mappings()
        .first()
    )
    if assignment is None:
        raise VavError(
            "SURVEY_ASSIGNMENT_NOT_FOUND",
            "Survey assignment not found.",
            status_code=404,
        )
    tasks = (
        (
            await session.execute(
                text("SELECT id,status FROM survey_tasks WHERE assignment_id=:id"),
                {"id": str(assignment_id)},
            )
        )
        .mappings()
        .all()
    )
    now = _now()
    scheduled = 0
    for task in tasks:
        slots = plan_reminders(
            deadline_at=assignment["deadline_at"],
            offsets_hours=[int(item) for item in assignment["reminder_offsets_hours"]],
            now=now,
            task_status=task["status"],
        )
        for slot in slots:
            result = await session.execute(
                text(
                    "INSERT INTO survey_reminder_dispatches (task_id,reminder_code,dedupe_key,scheduled_for) "
                    "VALUES (:task_id,:code,:dedupe_key,:scheduled_for) ON CONFLICT (dedupe_key) DO NOTHING"
                ),
                {
                    "task_id": str(task["id"]),
                    "code": slot.reminder_code,
                    "dedupe_key": reminder_dedupe_key(UUID(str(task["id"])), slot.reminder_code),
                    "scheduled_for": slot.scheduled_for,
                },
            )
            scheduled += int(getattr(result, "rowcount", 0) or 0) or 0
    await session.commit()
    return scheduled


async def survey_aggregate(session: AsyncSession, assignment_id: UUID) -> dict[str, Any]:
    """Aggregated results only. Raw open text is never returned here."""

    survey_enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT q.question_code,q.question_type,count(a.id) AS answered,"
                    "avg(a.rating_value) AS average_rating,min(a.rating_value) AS min_rating,"
                    "max(a.rating_value) AS max_rating "
                    "FROM survey_questions q "
                    "JOIN survey_definitions d ON d.id=q.definition_id "
                    "JOIN activity_survey_assignments asg ON asg.definition_id=d.id AND asg.id=:assignment_id "
                    "LEFT JOIN survey_answers a ON a.question_id=q.id "
                    "  AND a.response_id IN (SELECT id FROM survey_responses WHERE assignment_id=:assignment_id AND status='submitted') "
                    "GROUP BY q.question_code,q.question_type,q.position ORDER BY q.position"
                ),
                {"assignment_id": str(assignment_id)},
            )
        )
        .mappings()
        .all()
    )
    totals = (
        (
            await session.execute(
                text(
                    "SELECT count(*) FILTER (WHERE status='completed') AS completed,count(*) AS total "
                    "FROM survey_tasks WHERE assignment_id=:id"
                ),
                {"id": str(assignment_id)},
            )
        )
        .mappings()
        .one()
    )
    return {
        "assignment_id": str(assignment_id),
        "completed": int(totals["completed"] or 0),
        "total": int(totals["total"] or 0),
        "questions": [
            {
                "question_code": row["question_code"],
                "question_type": row["question_type"],
                "answered": int(row["answered"] or 0),
                "average_rating": (
                    round(float(row["average_rating"]), 2) if row["average_rating"] else None
                ),
                "min_rating": row["min_rating"],
                "max_rating": row["max_rating"],
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# B11 result letters
# ---------------------------------------------------------------------------


async def upsert_letter_template(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    result_letters_enabled()
    try:
        declared = sorted(
            set(extract_template_variables(payload["subject_template"]))
            | set(extract_template_variables(payload["body_template"]))
        )
    except PostEventRuleError as error:
        raise _fail(error) from error
    template_id = UUID(
        str(
            await session.scalar(
                text(
                    "INSERT INTO result_letter_templates "
                    "(template_code,semantic_version,locale,outcome,subject_template,body_template,declared_variables,status,created_by) "
                    "VALUES (:code,:version,:locale,:outcome,:subject,:body,CAST(:vars AS jsonb),'draft',:actor) "
                    "ON CONFLICT (template_code, semantic_version, locale) DO UPDATE SET "
                    "outcome=EXCLUDED.outcome,subject_template=EXCLUDED.subject_template,"
                    "body_template=EXCLUDED.body_template,declared_variables=EXCLUDED.declared_variables,"
                    "updated_at=now() WHERE result_letter_templates.status='draft' RETURNING id"
                ),
                {
                    "code": payload["template_code"],
                    "version": payload["semantic_version"],
                    "locale": payload["locale"],
                    "outcome": payload["outcome"],
                    "subject": payload["subject_template"],
                    "body": payload["body_template"],
                    "vars": _json(declared),
                    "actor": str(actor_id),
                },
            )
        )
    )
    await session.commit()
    return {"template_id": str(template_id), "declared_variables": declared}


async def publish_letter_template(
    session: AsyncSession, *, template_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    result_letters_enabled()
    updated = await session.execute(
        text(
            "UPDATE result_letter_templates SET status='published',published_at=now(),"
            "published_by=:actor,updated_at=now() WHERE id=:id AND status='draft'"
        ),
        {"id": str(template_id), "actor": str(actor_id)},
    )
    if int(getattr(updated, "rowcount", 0) or 0) == 0:
        raise VavError(
            "TEMPLATE_NOT_DRAFT", "Only a draft template can be published.", status_code=409
        )
    await session.commit()
    return {"template_id": str(template_id), "status": "published"}


async def generate_letters(
    session: AsyncSession, *, activity_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Generate one draft letter per eligible candidate.

    Existing approved or published letters are never overwritten: a regenerate
    creates a new version, so the previously released text stays intact.
    """

    result_letters_enabled()
    snapshot_id = UUID(str(payload["snapshot_id"]))
    snapshot = await get_snapshot(session, snapshot_id)
    if snapshot["status"] != SnapshotStatus.FROZEN:
        raise VavError(
            "SNAPSHOT_NOT_FROZEN",
            "Letters can only be generated from a frozen snapshot.",
            status_code=409,
        )
    pairs = await compute_matches(session, snapshot_id)
    partners: dict[UUID, list[UUID]] = {}
    for first, second in pairs:
        partners.setdefault(first, []).append(second)
        partners.setdefault(second, []).append(first)

    eligible = await list_snapshot_entries(session, snapshot_id, include_excluded=False)
    names = {UUID(str(item["user_id"])): item["display_name"] for item in eligible}
    submitted = set(
        (
            await session.execute(
                text(
                    "SELECT chooser_user_id FROM activity_selection_submissions "
                    "WHERE snapshot_id=:id AND status='submitted'"
                ),
                {"id": str(snapshot_id)},
            )
        )
        .scalars()
        .all()
    )
    submitted_ids = {UUID(str(item)) for item in submitted}

    templates = await _templates_by_outcome(session, payload)
    generated = 0
    skipped = 0
    for entry in eligible:
        user_id = UUID(str(entry["user_id"]))
        if user_id not in submitted_ids:
            outcome = LetterOutcome.NOT_ELIGIBLE
        elif partners.get(user_id):
            outcome = LetterOutcome.MUTUAL_MATCH
        else:
            outcome = LetterOutcome.NO_MATCH
        template = templates.get(outcome)
        if template is None:
            skipped += 1
            continue
        matched = partners.get(user_id, [])
        variables = {
            "recipient_name": names.get(user_id, "member"),
            "match_count": len(matched),
            "match_names": "、".join(names.get(item, "member") for item in matched),
            "activity_id": str(activity_id),
        }
        try:
            subject = render_template(template["subject_template"], variables)
            body = render_template(template["body_template"], variables)
        except PostEventRuleError as error:
            raise _fail(error) from error
        digest = content_fingerprint(subject, body)

        current = (
            (
                await session.execute(
                    text(
                        "SELECT id,status,version,content_hash FROM result_letters "
                        "WHERE activity_id=:activity_id AND recipient_user_id=:user_id "
                        "ORDER BY version DESC LIMIT 1"
                    ),
                    {"activity_id": str(activity_id), "user_id": str(user_id)},
                )
            )
            .mappings()
            .first()
        )
        if current is not None:
            if current["status"] in (LetterStatus.DRAFT, LetterStatus.REJECTED):
                if not payload.get("regenerate") and current["content_hash"] == digest:
                    skipped += 1
                    continue
                await session.execute(
                    text(
                        "UPDATE result_letters SET outcome=:outcome,status='draft',template_id=:template_id,"
                        "subject_encrypted=:subject,body_encrypted=:body,content_hash=:hash,"
                        "matched_user_ids=CAST(:matched AS jsonb),authored_by=:actor,generated_at=now(),"
                        "updated_at=now() WHERE id=:id"
                    ),
                    {
                        "outcome": outcome.value,
                        "template_id": str(template["id"]),
                        "subject": encrypt_private(subject),
                        "body": encrypt_private(body),
                        "hash": digest,
                        "matched": _json([str(item) for item in matched]),
                        "actor": str(actor_id),
                        "id": str(current["id"]),
                    },
                )
                generated += 1
                continue
            if not payload.get("regenerate"):
                skipped += 1
                continue
            next_version = int(current["version"]) + 1
        else:
            next_version = 1

        await session.execute(
            text(
                "INSERT INTO result_letters (activity_id,snapshot_id,recipient_user_id,template_id,"
                "outcome,status,version,subject_encrypted,body_encrypted,content_hash,matched_user_ids,"
                "authored_by,generated_at) VALUES (:activity_id,:snapshot_id,:user_id,:template_id,"
                ":outcome,'draft',:version,:subject,:body,:hash,CAST(:matched AS jsonb),:actor,now())"
            ),
            {
                "activity_id": str(activity_id),
                "snapshot_id": str(snapshot_id),
                "user_id": str(user_id),
                "template_id": str(template["id"]),
                "outcome": outcome.value,
                "version": next_version,
                "subject": encrypt_private(subject),
                "body": encrypt_private(body),
                "hash": digest,
                "matched": _json([str(item) for item in matched]),
                "actor": str(actor_id),
            },
        )
        generated += 1

    await _audit(
        session,
        activity_id=activity_id,
        snapshot_id=snapshot_id,
        actor_id=actor_id,
        actor_kind="admin",
        action="letters.generated",
        metadata={"generated": generated, "skipped": skipped, "pairs": len(pairs)},
    )
    await session.commit()
    return {
        "activity_id": str(activity_id),
        "snapshot_id": str(snapshot_id),
        "generated": generated,
        "skipped": skipped,
        "mutual_pairs": len(pairs),
    }


async def _templates_by_outcome(
    session: AsyncSession, payload: dict[str, Any]
) -> dict[LetterOutcome, dict[str, Any]]:
    clause = " AND template_code=:code" if payload.get("template_code") else ""
    rows = (
        (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (outcome) id,outcome,subject_template,body_template "
                    "FROM result_letter_templates WHERE status='published' AND locale=:locale"
                    + clause
                    + " ORDER BY outcome, semantic_version DESC"
                ),
                (
                    {"locale": payload["locale"], "code": payload["template_code"]}
                    if payload.get("template_code")
                    else {"locale": payload["locale"]}
                ),
            )
        )
        .mappings()
        .all()
    )
    return {LetterOutcome(row["outcome"]): dict(row) for row in rows}


async def list_letters_for_review(
    session: AsyncSession, *, activity_id: UUID, status: str | None = None
) -> list[dict[str, Any]]:
    result_letters_enabled()
    clause = " AND status=:status" if status else ""
    params: dict[str, Any] = {"activity_id": str(activity_id)}
    if status:
        params["status"] = status
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,recipient_user_id,outcome,status,version,content_hash,generated_at,"
                    "authored_by,published_at FROM result_letters WHERE activity_id=:activity_id"
                    + clause
                    + " ORDER BY status, generated_at DESC"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    return [
        {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
        for row in rows
    ]


async def get_letter_for_review(session: AsyncSession, letter_id: UUID) -> dict[str, Any]:
    result_letters_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,recipient_user_id,outcome,status,version,subject_encrypted,"
                    "body_encrypted,content_hash,matched_user_ids,authored_by,generated_at "
                    "FROM result_letters WHERE id=:id"
                ),
                {"id": str(letter_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("LETTER_NOT_FOUND", "Result letter not found.", status_code=404)
    return {
        "id": str(row["id"]),
        "activity_id": str(row["activity_id"]),
        "recipient_user_id": str(row["recipient_user_id"]),
        "outcome": row["outcome"],
        "status": row["status"],
        "version": row["version"],
        "subject": decrypt_private(row["subject_encrypted"]),
        "body": decrypt_private(row["body_encrypted"]),
        "content_hash": row["content_hash"],
        "matched_user_ids": row["matched_user_ids"],
        "authored_by": str(row["authored_by"]) if row["authored_by"] else None,
        "generated_at": row["generated_at"],
    }


async def submit_letter_for_review(
    session: AsyncSession, *, letter_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    result_letters_enabled()
    letter = await get_letter_for_review(session, letter_id)
    try:
        validate_letter_transition(letter["status"], LetterStatus.PENDING_REVIEW)
    except PostEventRuleError as error:
        raise _fail(error, status_code=409) from error
    await session.execute(
        text("UPDATE result_letters SET status='pending_review',updated_at=now() WHERE id=:id"),
        {"id": str(letter_id)},
    )
    await _audit(
        session,
        activity_id=UUID(letter["activity_id"]),
        snapshot_id=None,
        actor_id=actor_id,
        actor_kind="admin",
        action="letter.submitted_for_review",
        metadata={"letter_id": str(letter_id)},
    )
    await session.commit()
    return {"letter_id": str(letter_id), "status": "pending_review"}


async def review_letter(
    session: AsyncSession, *, letter_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Record a reviewer decision.

    The reviewer submits the hash of the text they read. If the draft changed in
    the meantime the decision is refused, so an approval can never land on text
    nobody reviewed.
    """

    result_letters_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,status,content_hash,authored_by FROM result_letters "
                    "WHERE id=:id FOR UPDATE"
                ),
                {"id": str(letter_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("LETTER_NOT_FOUND", "Result letter not found.", status_code=404)
    decision = payload["decision"]
    target = (
        LetterStatus.APPROVED
        if decision == "approved"
        else (LetterStatus.REJECTED if decision == "rejected" else LetterStatus.PENDING_REVIEW)
    )
    try:
        ensure_reviewer_is_not_author(
            reviewer_id=actor_id,
            author_id=UUID(str(row["authored_by"])) if row["authored_by"] else None,
        )
        if decision != "changes_requested":
            validate_letter_transition(row["status"], target)
        elif row["status"] != LetterStatus.PENDING_REVIEW:
            raise PostEventRuleError(
                "LETTER_TRANSITION_INVALID",
                "Changes can only be requested on a letter awaiting review.",
            )
    except PostEventRuleError as error:
        raise _fail(error, status_code=409) from error
    if payload["reviewed_content_hash"] != row["content_hash"]:
        raise VavError(
            "LETTER_CONTENT_CHANGED",
            "The letter changed after it was opened for review. Reload and review again.",
            status_code=409,
        )

    await session.execute(
        text(
            "INSERT INTO result_letter_reviews (letter_id,reviewer_id,decision,comment,reviewed_content_hash,decided_at) "
            "VALUES (:letter_id,:reviewer,:decision,:comment,:hash,now())"
        ),
        {
            "letter_id": str(letter_id),
            "reviewer": str(actor_id),
            "decision": decision,
            "comment": payload.get("comment"),
            "hash": payload["reviewed_content_hash"],
        },
    )
    if decision in ("approved", "rejected"):
        await session.execute(
            text("UPDATE result_letters SET status=:status,updated_at=now() WHERE id=:id"),
            {"status": target.value, "id": str(letter_id)},
        )
    await _audit(
        session,
        activity_id=UUID(str(row["activity_id"])),
        snapshot_id=None,
        actor_id=actor_id,
        actor_kind="admin",
        action=f"letter.review.{decision}",
        metadata={"letter_id": str(letter_id)},
    )
    await session.commit()
    return {"letter_id": str(letter_id), "decision": decision, "status": target.value}


async def publish_letter(
    session: AsyncSession, *, letter_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Publish an approved letter and write its immutable release row."""

    result_letters_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,recipient_user_id,status,version,subject_encrypted,"
                    "body_encrypted,content_hash FROM result_letters WHERE id=:id FOR UPDATE"
                ),
                {"id": str(letter_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("LETTER_NOT_FOUND", "Result letter not found.", status_code=404)
    try:
        validate_letter_transition(row["status"], LetterStatus.PUBLISHED)
    except PostEventRuleError as error:
        raise _fail(error, status_code=409) from error
    approver = await session.scalar(
        text(
            "SELECT reviewer_id FROM result_letter_reviews WHERE letter_id=:id AND decision='approved' "
            "ORDER BY decided_at DESC LIMIT 1"
        ),
        {"id": str(letter_id)},
    )
    dedupe_key = f"result-letter:{letter_id}:{row['version']}"
    try:
        await session.execute(
            text(
                "INSERT INTO result_letter_releases (letter_id,version,subject_encrypted,body_encrypted,"
                "content_hash,approved_by,released_by,released_at,notification_dedupe_key) "
                "VALUES (:letter_id,:version,:subject,:body,:hash,:approved_by,:actor,now(),:dedupe_key)"
            ),
            {
                "letter_id": str(letter_id),
                "version": row["version"],
                "subject": row["subject_encrypted"],
                "body": row["body_encrypted"],
                "hash": row["content_hash"],
                "approved_by": str(approver) if approver else None,
                "actor": str(actor_id),
                "dedupe_key": dedupe_key,
            },
        )
    except IntegrityError as error:
        await session.rollback()
        raise VavError(
            "LETTER_ALREADY_RELEASED",
            "This letter version has already been released.",
            status_code=409,
        ) from error
    await session.execute(
        text(
            "UPDATE result_letters SET status='published',published_at=now(),published_by=:actor,"
            "updated_at=now() WHERE id=:id"
        ),
        {"actor": str(actor_id), "id": str(letter_id)},
    )
    if payload.get("notify", True):
        # The notification carries no letter content: only a pointer to the
        # member's authenticated private view.
        await _publish(
            session,
            "activity.result_letter.published.v1",
            "result_letter",
            letter_id,
            {
                "letter_id": str(letter_id),
                "recipient_user_id": str(row["recipient_user_id"]),
                "activity_id": str(row["activity_id"]),
                "dedupe_key": dedupe_key,
            },
        )
    await _audit(
        session,
        activity_id=UUID(str(row["activity_id"])),
        snapshot_id=None,
        actor_id=actor_id,
        actor_kind="admin",
        action="letter.published",
        metadata={"letter_id": str(letter_id), "version": row["version"]},
    )
    await session.commit()
    return {"letter_id": str(letter_id), "status": "published", "version": row["version"]}


async def revoke_letter(
    session: AsyncSession, *, letter_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    result_letters_enabled()
    row = (
        (
            await session.execute(
                text("SELECT id,activity_id,status FROM result_letters WHERE id=:id FOR UPDATE"),
                {"id": str(letter_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("LETTER_NOT_FOUND", "Result letter not found.", status_code=404)
    try:
        validate_letter_transition(row["status"], LetterStatus.REVOKED)
    except PostEventRuleError as error:
        raise _fail(error, status_code=409) from error
    await session.execute(
        text(
            "UPDATE result_letters SET status='revoked',revoked_at=now(),revoked_by=:actor,"
            "revoked_reason=:reason,updated_at=now() WHERE id=:id"
        ),
        {"actor": str(actor_id), "reason": payload["reason"], "id": str(letter_id)},
    )
    await _audit(
        session,
        activity_id=UUID(str(row["activity_id"])),
        snapshot_id=None,
        actor_id=actor_id,
        actor_kind="admin",
        action="letter.revoked",
        reason=payload["reason"],
        metadata={"letter_id": str(letter_id)},
    )
    await session.commit()
    return {"letter_id": str(letter_id), "status": "revoked"}


async def list_my_letters(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """Members only ever see published letters."""

    result_letters_enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,outcome,published_at,read_at FROM result_letters "
                    "WHERE recipient_user_id=:user_id AND status='published' "
                    "ORDER BY published_at DESC"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .all()
    )
    return [
        {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
        for row in rows
    ]


async def read_my_letter(
    session: AsyncSession, *, letter_id: UUID, user_id: UUID
) -> dict[str, Any]:
    """Return a published letter and mark it read.

    The status filter is part of the WHERE clause rather than a post-load check,
    so an unpublished letter is indistinguishable from a missing one.
    """

    result_letters_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT l.id,l.activity_id,l.outcome,l.version,l.published_at,"
                    "r.subject_encrypted,r.body_encrypted,r.content_hash "
                    "FROM result_letters l "
                    "JOIN result_letter_releases r ON r.letter_id=l.id AND r.version=l.version "
                    "WHERE l.id=:id AND l.recipient_user_id=:user_id AND l.status='published'"
                ),
                {"id": str(letter_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("LETTER_NOT_FOUND", "Result letter not found.", status_code=404)
    await session.execute(
        text("UPDATE result_letters SET read_at=COALESCE(read_at, now()) WHERE id=:id"),
        {"id": str(letter_id)},
    )
    await session.commit()
    return {
        "id": str(row["id"]),
        "activity_id": str(row["activity_id"]),
        "outcome": row["outcome"],
        "version": row["version"],
        "published_at": row["published_at"],
        "subject": decrypt_private(row["subject_encrypted"]),
        "body": decrypt_private(row["body_encrypted"]),
        "content_hash": row["content_hash"],
    }
