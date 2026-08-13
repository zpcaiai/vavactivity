"""Transactional onsite check-in operations service (B08 / CHK-002).

Design notes:

* Every write that must be serial (confirm, undo, revoke) takes a row lock on
  the registration first, so two operators tapping at the same moment produce
  one outcome and one event row.
* A last-four lookup is a *narrowing* query. The searchable
  ``user_contact_points.last_four_hmac`` column added by migration
  ``20260812_0105`` is only ever used to shrink a candidate set; nothing in this
  file turns a fragment into an identity. The lookup row stores the candidate
  registration ids server-side, and clients address them through opaque HMAC
  choice tokens.
* No response, audit row, outbox payload or log line built here contains a
  phone number, a whole registration number or an unmasked display name. The
  masking is enforced by :func:`~vav.modules.checkin_operations.domain.ensure_choice_payload_safe`
  rather than trusted to review.
* All business rules live in :mod:`vav.modules.checkin_operations.domain` so
  they are testable without a database; this layer only loads state, holds
  locks and persists decisions.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.checkin_operations.domain import (
    AttendanceStatus,
    CheckinRuleError,
    LookupCandidate,
    LookupOutcome,
    ScanOutcome,
    WindowPolicy,
    build_audit_metadata,
    build_lookup_response,
    classify_checkin_window,
    confirmation_token,
    decide_lookup_outcome,
    decide_scan,
    ensure_checkin_window,
    ensure_last_four,
    ensure_undo_allowed,
    evaluate_rate_limit,
    last_four_hmac,
    mask_phone_fragment,
    match_choice_token,
    require_reason,
    scan_dedupe_key,
    verify_confirmation_token,
)
from vav.modules.privacy.crypto import searchable_hmac

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: CheckinRuleError, status_code: int = 422) -> VavError:
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


def checkin_operations_enabled() -> None:
    if not get_settings().checkin_operations_enabled:
        raise VavError(
            "CHECKIN_OPERATIONS_DISABLED",
            "Onsite check-in operations are not enabled.",
            status_code=503,
        )


def last_four_lookup_enabled() -> None:
    checkin_operations_enabled()
    if not get_settings().checkin_last_four_lookup_enabled:
        raise VavError(
            "CHECKIN_LAST_FOUR_LOOKUP_DISABLED",
            "Phone last-four lookup is not enabled.",
            status_code=503,
        )


def _lookup_key() -> bytes:
    """Deployment salt for the last-four column.

    Refuses to run rather than falling back to an empty key: an unsalted
    four-digit HMAC is a rainbow table, and silently degrading to one would be
    the worst possible failure mode for this particular column.
    """

    # Configured as a SecretStr; unwrap here and nowhere else.
    secret = get_settings().checkin_last_four_hmac_key
    key = (secret.get_secret_value() if secret else "").strip()
    if not key:
        raise VavError(
            "CHECKIN_LAST_FOUR_KEY_MISSING",
            "CHECKIN_LAST_FOUR_HMAC_KEY is not configured; last-four lookup is unavailable.",
            status_code=503,
        )
    return key.encode("utf-8")


def _token_key() -> bytes:
    secret = get_settings().checkin_token_signing_key
    key = (secret.get_secret_value() if secret else "").strip()
    if not key:
        raise VavError(
            "CHECKIN_TOKEN_KEY_MISSING",
            "CHECKIN_TOKEN_SIGNING_KEY is not configured; check-in confirmation is unavailable.",
            status_code=503,
        )
    return key.encode("utf-8")


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


async def _record_operation(
    session: AsyncSession,
    *,
    activity_id: UUID,
    session_id: UUID | None,
    registration_id: UUID | None,
    lookup_id: UUID | None,
    operator_id: UUID,
    operation: str,
    outcome: str,
    method: str,
    device_reference: str,
    request_id: str | None,
    dedupe_key: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> UUID:
    """Append one row to the module's own operation log.

    Why a separate table rather than only ``activity_checkin_events``: that
    table's ``action`` column is a constrained vocabulary shared with the rest
    of the platform, and the operational states this module needs
    (``duplicate_scan``, ``rate_limited``, ``lookup``) are not attendance
    actions. Canonical attendance transitions are still written to
    ``activity_checkin_events``; this log is the operator-behaviour trail.
    """

    operation_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO checkin_operation_events "
            "(id,activity_id,session_id,registration_id,lookup_id,operator_id,operation,outcome,"
            "method,device_reference,request_id,dedupe_key,reason,metadata) "
            "VALUES (:id,:activity_id,:session_id,:registration_id,:lookup_id,:operator_id,:operation,:outcome,"
            ":method,:device_reference,:request_id,:dedupe_key,:reason,CAST(:metadata AS jsonb))"
        ),
        {
            "id": str(operation_id),
            "activity_id": str(activity_id),
            "session_id": str(session_id) if session_id else None,
            "registration_id": str(registration_id) if registration_id else None,
            "lookup_id": str(lookup_id) if lookup_id else None,
            "operator_id": str(operator_id),
            "operation": operation,
            "outcome": outcome,
            "method": method,
            "device_reference": (device_reference or "unknown-device")[:128],
            "request_id": request_id,
            "dedupe_key": dedupe_key,
            "reason": reason,
            "metadata": _json(metadata or {}),
        },
    )
    return operation_id


async def _enforce_rate_limit(
    session: AsyncSession, *, operator_id: UUID, activity_id: UUID, now: datetime
) -> None:
    """Per-operator sliding window over recorded actions.

    Counted from the operation log rather than from an in-process counter so
    the limit survives a restart and applies across every API replica the
    scanner might reach.
    """

    settings = get_settings()
    window_seconds = int(settings.checkin_operator_rate_window_seconds)
    max_events = int(settings.checkin_operator_rate_max_events)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT occurred_at FROM checkin_operation_events "
                    "WHERE operator_id=:operator_id AND activity_id=:activity_id "
                    "AND occurred_at > :since ORDER BY occurred_at DESC LIMIT 500"
                ),
                {
                    "operator_id": str(operator_id),
                    "activity_id": str(activity_id),
                    "since": now - timedelta(seconds=window_seconds),
                },
            )
        )
        .scalars()
        .all()
    )
    try:
        decision = evaluate_rate_limit(
            rows, now=now, window_seconds=window_seconds, max_events=max_events
        )
    except CheckinRuleError as error:
        raise _fail(error, status_code=500) from error
    if not decision.allowed:
        raise VavError(
            "CHECKIN_OPERATOR_RATE_LIMITED",
            "Too many check-in actions from this operator; wait a moment and scan again.",
            status_code=429,
            details=[
                {
                    "retry_after_seconds": decision.retry_after_seconds,
                    "observed": decision.observed,
                    "window_seconds": window_seconds,
                }
            ],
        )


# ---------------------------------------------------------------------------
# Window policy
# ---------------------------------------------------------------------------


async def _load_window_policy(session: AsyncSession, activity_id: UUID) -> WindowPolicy:
    row = (
        (
            await session.execute(
                text(
                    "SELECT early_minutes,late_minutes FROM checkin_window_policies "
                    "WHERE activity_id=:activity_id"
                ),
                {"activity_id": str(activity_id)},
            )
        )
        .mappings()
        .first()
    )
    settings = get_settings()
    if row is None:
        # No per-activity policy means the deployment default, not "no policy".
        return WindowPolicy(
            early_minutes=int(settings.checkin_window_early_minutes),
            late_minutes=int(settings.checkin_window_late_minutes),
        )
    return WindowPolicy(
        early_minutes=int(row["early_minutes"]), late_minutes=int(row["late_minutes"])
    )


async def upsert_window_policy(
    session: AsyncSession, *, activity_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    checkin_operations_enabled()
    try:
        policy = WindowPolicy(
            early_minutes=int(payload["early_minutes"]),
            late_minutes=int(payload["late_minutes"]),
        )
    except CheckinRuleError as error:
        raise _fail(error) from error
    await session.execute(
        text(
            "INSERT INTO checkin_window_policies (activity_id,early_minutes,late_minutes,updated_by) "
            "VALUES (:activity_id,:early,:late,:actor) "
            "ON CONFLICT (activity_id) DO UPDATE SET early_minutes=EXCLUDED.early_minutes,"
            "late_minutes=EXCLUDED.late_minutes,updated_by=EXCLUDED.updated_by,updated_at=now()"
        ),
        {
            "activity_id": str(activity_id),
            "early": policy.early_minutes,
            "late": policy.late_minutes,
            "actor": str(actor_id),
        },
    )
    return {
        "activity_id": str(activity_id),
        "early_minutes": policy.early_minutes,
        "late_minutes": policy.late_minutes,
    }


async def get_window_policy(session: AsyncSession, activity_id: UUID) -> dict[str, Any]:
    policy = await _load_window_policy(session, activity_id)
    return {
        "activity_id": str(activity_id),
        "early_minutes": policy.early_minutes,
        "late_minutes": policy.late_minutes,
    }


# ---------------------------------------------------------------------------
# CHK-002 last-four lookup
# ---------------------------------------------------------------------------


async def _load_candidates(
    session: AsyncSession, *, activity_id: UUID, fragment_hmac: str
) -> list[LookupCandidate]:
    """Narrow the guest list by the salted last-four HMAC.

    The join is on ``user_contact_points`` rather than on any denormalized copy
    so a member who changed their number is found by their *current* one, and
    the ``contact_type='phone'`` and ``status='verified'`` predicates keep an
    unverified number from resolving anybody.
    """

    rows = (
        (
            await session.execute(
                text(
                    "SELECT DISTINCT r.id AS registration_id, r.user_id, r.registration_number,"
                    " r.status AS registration_status, r.attendance_status,"
                    " COALESCE(p.display_name, 'member-' || left(r.user_id::text, 8)) AS display_name,"
                    " COALESCE(t.name, '') AS ticket_label"
                    " FROM activity_registrations r"
                    " JOIN user_contact_points cp ON cp.user_id=r.user_id"
                    " LEFT JOIN activity_participant_profiles p ON p.registration_id=r.id"
                    " LEFT JOIN activity_ticket_types t ON t.id=r.ticket_type_id"
                    " WHERE r.activity_id=:activity_id"
                    " AND cp.contact_type='phone' AND cp.status='verified'"
                    " AND cp.last_four_hmac=:fragment"
                    " AND r.status='confirmed'"
                    " ORDER BY r.registration_number"
                    " LIMIT 50"
                ),
                {"activity_id": str(activity_id), "fragment": fragment_hmac},
            )
        )
        .mappings()
        .all()
    )
    return [
        LookupCandidate(
            registration_id=UUID(str(row["registration_id"])),
            user_id=UUID(str(row["user_id"])),
            registration_number=str(row["registration_number"]),
            display_name=str(row["display_name"]),
            registration_status=str(row["registration_status"]),
            attendance_status=str(row["attendance_status"]),
            ticket_label=str(row["ticket_label"]),
        )
        for row in rows
    ]


async def lookup_by_last_four(
    session: AsyncSession,
    *,
    activity_id: UUID,
    operator_id: UUID,
    payload: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    """Search the guest list by a four-digit fragment.

    Returns opaque choice tokens, never people. Two or more matches are
    reported as ambiguous and *cannot* be acted on without a discriminator the
    operator reads off the member or their ticket; see
    :func:`~vav.modules.checkin_operations.domain.decide_lookup_outcome`.
    """

    last_four_lookup_enabled()
    now = _now()
    await _enforce_rate_limit(session, operator_id=operator_id, activity_id=activity_id, now=now)
    try:
        fragment = ensure_last_four(payload["last_four"])
        fragment_hmac = last_four_hmac(
            fragment,
            key=_lookup_key(),
            salt_version=get_settings().checkin_last_four_salt_version,
        )
    except CheckinRuleError as error:
        raise _fail(error, status_code=400) from error

    candidates = await _load_candidates(
        session, activity_id=activity_id, fragment_hmac=fragment_hmac
    )
    decision = decide_lookup_outcome(candidates)

    lookup_id = uuid4()
    ttl_seconds = int(get_settings().checkin_lookup_ttl_seconds)
    await session.execute(
        text(
            "INSERT INTO checkin_lookup_sessions "
            "(id,activity_id,session_id,operator_id,fragment_hmac,outcome,candidate_count,issued_at,expires_at,device_reference,request_id) "
            "VALUES (:id,:activity_id,:session_id,:operator_id,:fragment,:outcome,:count,:issued_at,:expires_at,:device,:request_id)"
        ),
        {
            "id": str(lookup_id),
            "activity_id": str(activity_id),
            "session_id": str(payload["session_id"]) if payload.get("session_id") else None,
            "operator_id": str(operator_id),
            "fragment": fragment_hmac,
            "outcome": decision.outcome.value,
            "count": len(decision.candidates),
            "issued_at": now,
            "expires_at": now + timedelta(seconds=ttl_seconds),
            "device": (payload.get("device_reference") or "unknown-device")[:128],
            "request_id": request_id,
        },
    )
    for position, candidate in enumerate(decision.candidates, start=1):
        await session.execute(
            text(
                "INSERT INTO checkin_lookup_candidates (id,lookup_id,registration_id,position) "
                "VALUES (:id,:lookup_id,:registration_id,:position)"
            ),
            {
                "id": str(uuid4()),
                "lookup_id": str(lookup_id),
                "registration_id": str(candidate.registration_id),
                "position": position,
            },
        )

    await _record_operation(
        session,
        activity_id=activity_id,
        session_id=UUID(str(payload["session_id"])) if payload.get("session_id") else None,
        registration_id=None,
        lookup_id=lookup_id,
        operator_id=operator_id,
        operation="lookup",
        outcome=decision.outcome.value,
        method="phone_last_four",
        device_reference=payload.get("device_reference") or "unknown-device",
        request_id=request_id,
        # Only the masked form. The fragment HMAC lives in the lookup row where
        # it is needed for replay; the audit trail does not need it.
        metadata={"searched_fragment": mask_phone_fragment(fragment)},
    )

    response = build_lookup_response(decision, lookup_id=lookup_id, issued_at=now, key=_token_key())
    response["expires_in_seconds"] = ttl_seconds
    if decision.outcome is LookupOutcome.TOO_MANY:
        response["hint_code"] = "CHECKIN_LOOKUP_TOO_MANY"
    return response


async def _load_lookup(
    session: AsyncSession, *, lookup_id: UUID, operator_id: UUID
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,session_id,operator_id,issued_at,expires_at,outcome "
                    "FROM checkin_lookup_sessions WHERE id=:id"
                ),
                {"id": str(lookup_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("CHECKIN_LOOKUP_NOT_FOUND", "That lookup has expired.", status_code=404)
    if UUID(str(row["operator_id"])) != operator_id:
        # Not 403: telling one operator that another operator's lookup exists
        # is itself a small leak about who is working the door.
        raise VavError("CHECKIN_LOOKUP_NOT_FOUND", "That lookup has expired.", status_code=404)
    if row["expires_at"] <= _now():
        raise VavError(
            "CHECKIN_LOOKUP_EXPIRED", "That lookup has expired; search again.", status_code=409
        )
    return dict(row)


async def select_candidate(
    session: AsyncSession, *, operator_id: UUID, payload: dict[str, Any], request_id: str
) -> dict[str, Any]:
    """Turn an opaque choice token into a pending, confirmable check-in.

    This is the disambiguation step. Nothing here writes attendance: it mints a
    short-lived confirmation token so the operator's next tap is an explicit,
    deliberate second action rather than a continuation of the search.
    """

    last_four_lookup_enabled()
    lookup_id = UUID(str(payload["lookup_id"]))
    lookup = await _load_lookup(session, lookup_id=lookup_id, operator_id=operator_id)
    activity_id = UUID(str(lookup["activity_id"]))
    now = _now()
    await _enforce_rate_limit(session, operator_id=operator_id, activity_id=activity_id, now=now)

    candidate_ids = (
        (
            await session.execute(
                text(
                    "SELECT registration_id FROM checkin_lookup_candidates "
                    "WHERE lookup_id=:lookup_id ORDER BY position"
                ),
                {"lookup_id": str(lookup_id)},
            )
        )
        .scalars()
        .all()
    )
    candidates = [
        LookupCandidate(
            registration_id=UUID(str(value)),
            user_id=UUID(int=0),
            registration_number="",
            display_name="",
            registration_status="confirmed",
            attendance_status=AttendanceStatus.NOT_CHECKED_IN,
        )
        for value in candidate_ids
    ]
    try:
        matched = match_choice_token(
            payload["choice_token"],
            candidates,
            lookup_id=lookup_id,
            issued_at=lookup["issued_at"],
            key=_token_key(),
        )
    except CheckinRuleError as error:
        raise _fail(error, status_code=409) from error

    token = confirmation_token(
        lookup_id=lookup_id,
        registration_id=matched.registration_id,
        operator_id=operator_id,
        issued_at=lookup["issued_at"],
        key=_token_key(),
    )
    await session.execute(
        text(
            "UPDATE checkin_lookup_sessions SET resolved_registration_id=:registration_id,"
            "resolved_at=:now,discriminator_kind=:kind WHERE id=:id"
        ),
        {
            "registration_id": str(matched.registration_id),
            "now": now,
            "kind": payload.get("discriminator_kind") or "both",
            "id": str(lookup_id),
        },
    )
    await _record_operation(
        session,
        activity_id=activity_id,
        session_id=UUID(str(lookup["session_id"])) if lookup["session_id"] else None,
        registration_id=matched.registration_id,
        lookup_id=lookup_id,
        operator_id=operator_id,
        operation="select_candidate",
        outcome="pending_confirmation",
        method="phone_last_four",
        device_reference="unknown-device",
        request_id=request_id,
        metadata={"discriminator_kind": payload.get("discriminator_kind") or "both"},
    )
    return {
        "lookup_id": str(lookup_id),
        "confirmation_token": token,
        "expires_at": lookup["expires_at"].isoformat(),
        "requires_confirmation": True,
    }


# ---------------------------------------------------------------------------
# CHK-002 confirm / scan
# ---------------------------------------------------------------------------


async def _lock_registration(session: AsyncSession, registration_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,user_id,status,attendance_status,version "
                    "FROM activity_registrations WHERE id=:id FOR UPDATE"
                ),
                {"id": str(registration_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("CHECKIN_REGISTRATION_NOT_FOUND", "Registration not found.", status_code=404)
    return dict(row)


async def _last_checkin_at(session: AsyncSession, registration_id: UUID) -> datetime | None:
    return (
        await session.execute(
            text(
                "SELECT max(occurred_at) FROM activity_checkin_events "
                "WHERE registration_id=:id AND action='check_in'"
            ),
            {"id": str(registration_id)},
        )
    ).scalar_one_or_none()


async def _session_window(
    session: AsyncSession, session_id: UUID | None
) -> tuple[datetime, datetime] | None:
    if session_id is None:
        return None
    row = (
        (
            await session.execute(
                text("SELECT starts_at,ends_at FROM activity_sessions WHERE id=:id"),
                {"id": str(session_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["starts_at"] is None or row["ends_at"] is None:
        return None
    return row["starts_at"], row["ends_at"]


async def confirm_checkin(
    session: AsyncSession,
    *,
    operator_id: UUID,
    payload: dict[str, Any],
    request_id: str,
    has_window_override: bool = False,
) -> dict[str, Any]:
    """The second, explicit tap that writes attendance.

    The registration row is locked for the duration, so two operators
    confirming the same person at the same moment serialize into one write and
    one ``activity_checkin_events`` row; the loser sees the idempotent
    duplicate response rather than an error.
    """

    checkin_operations_enabled()
    lookup_id = UUID(str(payload["lookup_id"]))
    lookup = await _load_lookup(session, lookup_id=lookup_id, operator_id=operator_id)
    if lookup.get("resolved_registration_id") is None:
        raise VavError(
            "CHECKIN_LOOKUP_UNRESOLVED",
            "Choose a candidate before confirming.",
            status_code=409,
        )
    registration_id = UUID(str(lookup["resolved_registration_id"]))
    activity_id = UUID(str(lookup["activity_id"]))
    now = _now()
    await _enforce_rate_limit(session, operator_id=operator_id, activity_id=activity_id, now=now)

    try:
        verify_confirmation_token(
            payload["confirmation_token"],
            lookup_id=lookup_id,
            registration_id=registration_id,
            operator_id=operator_id,
            issued_at=lookup["issued_at"],
            now=now,
            ttl_seconds=int(get_settings().checkin_confirmation_ttl_seconds),
            key=_token_key(),
        )
    except CheckinRuleError as error:
        raise _fail(error, status_code=409) from error

    registration = await _lock_registration(session, registration_id)
    session_id = (
        UUID(str(payload["session_id"]))
        if payload.get("session_id")
        else (UUID(str(lookup["session_id"])) if lookup["session_id"] else None)
    )

    window = await _session_window(session, session_id)
    policy = await _load_window_policy(session, activity_id)
    try:
        if window is None:
            # No session timing configured: there is no window to be outside
            # of, so the check-in is in-window by definition rather than
            # blocked on data the organizer never entered.
            window_decision = ensure_checkin_window(
                classify_checkin_window(
                    now=now,
                    session_start_at=now - timedelta(minutes=1),
                    session_end_at=now + timedelta(minutes=1),
                    policy=policy,
                ),
                has_override_permission=has_window_override,
            )
        else:
            state = classify_checkin_window(
                now=now, session_start_at=window[0], session_end_at=window[1], policy=policy
            )
            window_decision = ensure_checkin_window(
                state,
                has_override_permission=has_window_override,
                override_reason=payload.get("override_reason"),
            )
    except CheckinRuleError as error:
        await _record_operation(
            session,
            activity_id=activity_id,
            session_id=session_id,
            registration_id=registration_id,
            lookup_id=lookup_id,
            operator_id=operator_id,
            operation="confirm",
            outcome="refused_out_of_window",
            method=payload.get("method") or "manual",
            device_reference=payload.get("device_reference") or "unknown-device",
            request_id=request_id,
            metadata={"code": error.code, **error.details},
        )
        raise _fail(error, status_code=409) from error

    try:
        decision = decide_scan(
            registration_status=str(registration["status"]),
            attendance_status=str(registration["attendance_status"]),
            checked_in_at=await _last_checkin_at(session, registration_id),
            now=now,
        )
    except CheckinRuleError as error:
        await _record_operation(
            session,
            activity_id=activity_id,
            session_id=session_id,
            registration_id=registration_id,
            lookup_id=lookup_id,
            operator_id=operator_id,
            operation="confirm",
            outcome="refused",
            method=payload.get("method") or "manual",
            device_reference=payload.get("device_reference") or "unknown-device",
            request_id=request_id,
            metadata={"code": error.code, **error.details},
        )
        raise _fail(error, status_code=409) from error

    metadata = build_audit_metadata(
        outcome=decision.outcome,
        window=window_decision,
        method=payload.get("method") or "manual",
        device_reference=payload.get("device_reference") or "unknown-device",
    )

    if decision.writes_attendance:
        await session.execute(
            text(
                "UPDATE activity_registrations SET attendance_status='checked_in',"
                "version=version+1,updated_at=now() WHERE id=:id"
            ),
            {"id": str(registration_id)},
        )
        await session.execute(
            text(
                "INSERT INTO activity_checkin_events "
                "(activity_id,session_id,registration_id,action,method,performed_by,reason,device_reference,request_id,occurred_at) "
                "VALUES (:activity_id,:session_id,:registration_id,'check_in',:method,:operator,:reason,:device,:request_id,:occurred_at)"
            ),
            {
                "activity_id": str(activity_id),
                "session_id": str(session_id) if session_id else None,
                "registration_id": str(registration_id),
                "method": payload.get("method") or "manual",
                "operator": str(operator_id),
                "reason": window_decision.override_reason,
                "device": (payload.get("device_reference") or "unknown-device")[:128],
                "request_id": request_id,
                "occurred_at": decision.effective_checked_in_at,
            },
        )
        await _publish(
            session,
            "activity.checkin.recorded.v1",
            "activity_registration",
            registration_id,
            {
                "activity_id": str(activity_id),
                "registration_id": str(registration_id),
                "occurred_at": decision.effective_checked_in_at.isoformat(),
                "outcome": decision.outcome.value,
                "override_used": window_decision.override_used,
            },
        )
    if window_decision.override_used:
        await session.execute(
            text(
                "INSERT INTO checkin_window_overrides "
                "(id,activity_id,session_id,registration_id,operator_id,window_state,reason,occurred_at) "
                "VALUES (:id,:activity_id,:session_id,:registration_id,:operator_id,:state,:reason,:occurred_at)"
            ),
            {
                "id": str(uuid4()),
                "activity_id": str(activity_id),
                "session_id": str(session_id) if session_id else None,
                "registration_id": str(registration_id),
                "operator_id": str(operator_id),
                "state": window_decision.state.value,
                "reason": window_decision.override_reason,
                "occurred_at": now,
            },
        )

    try:
        dedupe = scan_dedupe_key(
            registration_id=registration_id,
            device_reference=payload.get("device_reference") or "unknown-device",
            request_id=request_id,
        )
    except CheckinRuleError as error:
        raise _fail(error, status_code=400) from error
    # The same request id may already have landed. That is a retry, and a retry
    # of a check-in is a success: the member is checked in either way.
    with suppress(IntegrityError):
        await _record_operation(
            session,
            activity_id=activity_id,
            session_id=session_id,
            registration_id=registration_id,
            lookup_id=lookup_id,
            operator_id=operator_id,
            operation="confirm",
            outcome=decision.outcome.value,
            method=payload.get("method") or "manual",
            device_reference=payload.get("device_reference") or "unknown-device",
            request_id=request_id,
            dedupe_key=dedupe,
            reason=window_decision.override_reason,
            metadata=metadata,
        )

    return {
        "registration_id": str(registration_id),
        "outcome": decision.outcome.value,
        "message_code": decision.message_code,
        "checked_in_at": decision.effective_checked_in_at.isoformat(),
        "attendance_status": AttendanceStatus.CHECKED_IN.value,
        "window_state": window_decision.state.value,
        "override_used": window_decision.override_used,
        "undo_window_minutes": int(get_settings().checkin_undo_window_minutes),
        "duplicate": decision.outcome is ScanOutcome.DUPLICATE_NOOP,
    }


# ---------------------------------------------------------------------------
# CHK-002 undo and revoke
# ---------------------------------------------------------------------------


async def undo_checkin(
    session: AsyncSession,
    *,
    registration_id: UUID,
    operator_id: UUID,
    payload: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    """Operator self-service correction of a mis-tap, inside a short window.

    Deliberately not the same route as the administrative revoke: an undo is
    "that was the wrong person, I tapped too fast", is limited to minutes, and
    still demands a written reason so the correction is not invisible.
    """

    checkin_operations_enabled()
    now = _now()
    registration = await _lock_registration(session, registration_id)
    activity_id = UUID(str(registration["activity_id"]))
    await _enforce_rate_limit(session, operator_id=operator_id, activity_id=activity_id, now=now)
    try:
        reason = ensure_undo_allowed(
            attendance_status=str(registration["attendance_status"]),
            checked_in_at=await _last_checkin_at(session, registration_id),
            now=now,
            undo_window_minutes=int(get_settings().checkin_undo_window_minutes),
            reason=payload.get("reason"),
        )
    except CheckinRuleError as error:
        raise _fail(error, status_code=409) from error

    await session.execute(
        text(
            "UPDATE activity_registrations SET attendance_status='checkin_revoked',"
            "version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"id": str(registration_id)},
    )
    await session.execute(
        text(
            "INSERT INTO activity_checkin_events "
            "(activity_id,session_id,registration_id,action,method,performed_by,reason,device_reference,request_id,occurred_at) "
            "VALUES (:activity_id,NULL,:registration_id,'revoke','manual',:operator,:reason,:device,:request_id,:occurred_at)"
        ),
        {
            "activity_id": str(activity_id),
            "registration_id": str(registration_id),
            "operator": str(operator_id),
            "reason": reason,
            "device": (payload.get("device_reference") or "unknown-device")[:128],
            "request_id": request_id,
            "occurred_at": now,
        },
    )
    await _record_operation(
        session,
        activity_id=activity_id,
        session_id=None,
        registration_id=registration_id,
        lookup_id=None,
        operator_id=operator_id,
        operation="undo",
        outcome="undone",
        method="manual",
        device_reference=payload.get("device_reference") or "unknown-device",
        request_id=request_id,
        reason=reason,
    )
    await _publish(
        session,
        "activity.checkin.undone.v1",
        "activity_registration",
        registration_id,
        {"activity_id": str(activity_id), "registration_id": str(registration_id)},
    )
    return {
        "registration_id": str(registration_id),
        "attendance_status": AttendanceStatus.CHECKIN_REVOKED.value,
        "undone_at": now.isoformat(),
    }


async def revoke_checkin(
    session: AsyncSession,
    *,
    registration_id: UUID,
    actor_id: UUID,
    payload: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    """Administrative revocation after the undo window has closed.

    Separated from undo because the consequences differ: this record feeds the
    post-event candidate freeze, so changing it hours later is a decision about
    who counts as having attended, not a typo correction.
    """

    checkin_operations_enabled()
    now = _now()
    registration = await _lock_registration(session, registration_id)
    try:
        reason = require_reason(payload.get("reason"), code="CHECKIN_REVOKE_REASON_REQUIRED")
    except CheckinRuleError as error:
        raise _fail(error, status_code=400) from error
    if registration["attendance_status"] not in (
        AttendanceStatus.CHECKED_IN,
        AttendanceStatus.CHECKIN_REVOKED,
    ):
        raise VavError(
            "CHECKIN_NOTHING_TO_REVOKE",
            "This registration has no check-in to revoke.",
            status_code=409,
            details=[{"attendance_status": str(registration["attendance_status"])}],
        )
    target = "no_show" if payload.get("mark_no_show") else "checkin_revoked"
    activity_id = UUID(str(registration["activity_id"]))
    await session.execute(
        text(
            "UPDATE activity_registrations SET attendance_status=:target,"
            "version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"target": target, "id": str(registration_id)},
    )
    await session.execute(
        text(
            "INSERT INTO activity_checkin_events "
            "(activity_id,session_id,registration_id,action,method,performed_by,reason,device_reference,request_id,occurred_at) "
            "VALUES (:activity_id,NULL,:registration_id,'revoke','manual',:actor,:reason,'admin-console',:request_id,:occurred_at)"
        ),
        {
            "activity_id": str(activity_id),
            "registration_id": str(registration_id),
            "actor": str(actor_id),
            "reason": reason,
            "request_id": request_id,
            "occurred_at": now,
        },
    )
    await _record_operation(
        session,
        activity_id=activity_id,
        session_id=None,
        registration_id=registration_id,
        lookup_id=None,
        operator_id=actor_id,
        operation="revoke",
        outcome=target,
        method="manual",
        device_reference="admin-console",
        request_id=request_id,
        reason=reason,
    )
    return {"registration_id": str(registration_id), "attendance_status": target}


# ---------------------------------------------------------------------------
# Administration and support views
# ---------------------------------------------------------------------------


async def list_operation_events(
    session: AsyncSession, *, activity_id: UUID, limit: int = 100
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,registration_id,operator_id,operation,outcome,method,"
                    "device_reference,reason,metadata,occurred_at FROM checkin_operation_events "
                    "WHERE activity_id=:activity_id ORDER BY occurred_at DESC LIMIT :limit"
                ),
                {"activity_id": str(activity_id), "limit": min(max(limit, 1), 500)},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "id": str(row["id"]),
            "registration_id": str(row["registration_id"]) if row["registration_id"] else None,
            "operator_id": str(row["operator_id"]),
            "operation": row["operation"],
            "outcome": row["outcome"],
            "method": row["method"],
            "device_reference": row["device_reference"],
            "reason": row["reason"],
            "metadata": row["metadata"],
            "occurred_at": row["occurred_at"].isoformat(),
        }
        for row in rows
    ]


async def list_window_overrides(
    session: AsyncSession, *, activity_id: UUID, limit: int = 100
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,registration_id,operator_id,window_state,reason,occurred_at "
                    "FROM checkin_window_overrides WHERE activity_id=:activity_id "
                    "ORDER BY occurred_at DESC LIMIT :limit"
                ),
                {"activity_id": str(activity_id), "limit": min(max(limit, 1), 500)},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "id": str(row["id"]),
            "registration_id": str(row["registration_id"]),
            "operator_id": str(row["operator_id"]),
            "window_state": row["window_state"],
            "reason": row["reason"],
            "occurred_at": row["occurred_at"].isoformat(),
        }
        for row in rows
    ]


async def request_last_four_backfill(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Record a request to populate ``last_four_hmac`` for existing rows.

    Migration ``20260812_0105`` backfills nothing on purpose: the stored phone
    value is encrypted, so there is no plaintext in the database from which SQL
    could derive a last-four. Populating the column therefore requires a job
    running with the privacy decryption key. This endpoint books that job and
    records who asked for it; the worker reads the queued row, decrypts in
    batches, writes ``last_four_hmac`` and reports progress back here.

    Until that job has run, a member whose contact row predates this migration
    simply does not appear in a last-four lookup - which is the correct failure
    mode. The alternative, silently matching on a partial HMAC of the full
    number, would be a lookup that sometimes lies.
    """

    checkin_operations_enabled()
    run_id = uuid4()
    pending = (
        await session.execute(
            text(
                "SELECT count(*) FROM user_contact_points "
                "WHERE contact_type='phone' AND last_four_hmac IS NULL"
            )
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO checkin_last_four_backfill_runs "
            "(id,requested_by,batch_size,salt_version,dry_run,pending_rows,status) "
            "VALUES (:id,:actor,:batch_size,:salt_version,:dry_run,:pending,'queued')"
        ),
        {
            "id": str(run_id),
            "actor": str(actor_id),
            "batch_size": int(payload["batch_size"]),
            "salt_version": payload["salt_version"],
            "dry_run": bool(payload["dry_run"]),
            "pending": int(pending),
        },
    )
    await _publish(
        session,
        "checkin.last_four_backfill.requested.v1",
        "checkin_last_four_backfill_run",
        run_id,
        {
            "run_id": str(run_id),
            "batch_size": int(payload["batch_size"]),
            "salt_version": payload["salt_version"],
            "dry_run": bool(payload["dry_run"]),
        },
    )
    return {
        "run_id": str(run_id),
        "status": "queued",
        "pending_rows": int(pending),
        "dry_run": bool(payload["dry_run"]),
    }


def contact_point_write_values(raw_phone: str) -> dict[str, str]:
    """Both HMACs a contact-point write must store, from one plaintext read.

    Exists so the identity module's phone-verification path has a single place
    to call: ``value_hmac`` keeps its existing meaning (exact-match lookup of a
    whole number) and ``last_four_hmac`` is the new narrowing column. See
    PATCHES.md - this is the one existing code path that must change.
    """

    from vav.modules.checkin_operations.domain import last_four_of, normalize_phone_digits

    digits = normalize_phone_digits(raw_phone)
    return {
        "value_hmac": searchable_hmac(digits),
        "last_four_hmac": last_four_hmac(
            last_four_of(digits),
            key=_lookup_key(),
            salt_version=get_settings().checkin_last_four_salt_version,
        ),
    }
