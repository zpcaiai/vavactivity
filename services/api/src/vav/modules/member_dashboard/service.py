"""Transactional member dashboard aggregation service (B18 / DASH-001).

Design notes:

* Every section is loaded independently and wrapped: a SQL error, a missing
  table after a partial deploy or a rule violation degrades **that section**
  and nothing else. :func:`get_dashboard` has no code path that raises for a
  section failure, which is what makes "the dashboard never 500s because one
  module is down" a property of the code rather than an aspiration.
* Every section query filters on the authenticated user id in its WHERE clause,
  and the loaded rows are then re-checked against that same id by
  ``domain.assert_rows_belong_to``. The second check exists because the first
  one is a string.
* The matchmaking section is decided by the relationship gate *before* the
  entitlement row is read, so a non-single member's balance is never even
  loaded (MATCH-001).
* All rules live in :mod:`vav.modules.member_dashboard.domain`; this layer only
  loads state and serializes it.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.member_dashboard.domain import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    DashboardRuleError,
    EntitlementRow,
    NotificationRow,
    RegistrationRow,
    ResultLetterRow,
    SectionKey,
    SectionOutcome,
    SelectionRow,
    SurveyTaskRow,
    TaskType,
    assemble_dashboard,
    build_matchmaking_section,
    build_notification_section,
    build_registration_section,
    build_result_letter_section,
    build_selection_section,
    build_survey_section,
    collect_section,
    is_matchmaking_allowed,
    paginate,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: DashboardRuleError, status_code: int = 422) -> VavError:
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


def enabled() -> None:
    if not get_settings().member_dashboard_enabled:
        raise VavError(
            "MEMBER_DASHBOARD_DISABLED", "The member dashboard is not enabled.", status_code=503
        )


async def _publish(
    session: AsyncSession, topic: str, aggregate_id: UUID, payload: dict[str, Any]
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,'member_dashboard',:id,CAST(:payload AS jsonb))"
        ),
        {"topic": topic, "id": str(aggregate_id), "payload": _json(payload)},
    )


async def _record_incident(
    session: AsyncSession, *, user_id: UUID | None, outcome: SectionOutcome
) -> None:
    """Log a degraded section so "the dashboard looked empty" is diagnosable.

    Written on its own statement and deliberately tolerant: if even this fails,
    the member still gets their dashboard.
    """

    try:
        await session.execute(
            text(
                "INSERT INTO member_dashboard_section_incidents "
                "(user_id,section_key,error_code,error_detail) "
                "VALUES (:user_id,:section_key,:error_code,:error_detail)"
            ),
            {
                "user_id": str(user_id) if user_id else None,
                "section_key": outcome.key.value,
                "error_code": outcome.error_code or "SECTION_UNAVAILABLE",
                "error_detail": (outcome.error_message or "")[:2000],
            },
        )
    except Exception:  # noqa: BLE001 - observability must never break the page
        return


# ---------------------------------------------------------------------------
# Section loaders
#
# Each returns rows already scoped to the member. The ownership re-check lives
# in the domain builder, so a loader that forgets its WHERE clause fails loudly
# instead of leaking.
# ---------------------------------------------------------------------------


async def _load_survey_rows(session: AsyncSession, user_id: UUID) -> list[SurveyTaskRow]:
    rows = (
        (
            await session.execute(
                text(
                    # Mirrors post_event.service.list_my_survey_tasks: waived
                    # tasks are excluded at the source, so they are excluded here.
                    "SELECT t.id,t.assignment_id,t.activity_id,t.status,t.due_at "
                    "FROM survey_tasks t "
                    "WHERE t.user_id=:user_id AND t.status <> 'waived' "
                    "ORDER BY t.due_at"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .all()
    )
    return [
        SurveyTaskRow(
            user_id=user_id,
            task_id=UUID(str(row["id"])),
            assignment_id=UUID(str(row["assignment_id"])),
            activity_id=UUID(str(row["activity_id"])),
            status=row["status"],
            due_at=row["due_at"],
        )
        for row in rows
    ]


async def _load_letter_rows(session: AsyncSession, user_id: UUID) -> list[ResultLetterRow]:
    rows = (
        (
            await session.execute(
                text(
                    # Mirrors post_event.service.list_my_letters: the status
                    # filter is in the WHERE clause, not a post-load check.
                    "SELECT id,activity_id,status,published_at,read_at FROM result_letters "
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
        ResultLetterRow(
            user_id=user_id,
            letter_id=UUID(str(row["id"])),
            activity_id=UUID(str(row["activity_id"])),
            status=row["status"],
            published_at=row["published_at"],
            read_at=row["read_at"],
        )
        for row in rows
    ]


async def _load_registration_rows(
    session: AsyncSession, user_id: UUID, *, locale: str
) -> list[RegistrationRow]:
    rows = (
        (
            await session.execute(
                text(
                    # activities carries no title: the localized title lives on
                    # activity_localizations, joined here on the requested
                    # locale and falling back to the activity's default locale.
                    "SELECT r.id,r.activity_id,r.status,r.attendance_status,"
                    "a.starts_at,a.ends_at,a.status AS activity_status,"
                    "COALESCE(l.title, ldef.title, '') AS title "
                    "FROM activity_registrations r "
                    "JOIN activities a ON a.id=r.activity_id "
                    "LEFT JOIN activity_localizations l ON l.activity_id=a.id AND l.locale=:locale "
                    "LEFT JOIN activity_localizations ldef ON ldef.activity_id=a.id AND ldef.locale=a.default_locale "
                    "WHERE r.user_id=:user_id "
                    "ORDER BY a.starts_at DESC"
                ),
                {"user_id": str(user_id), "locale": locale},
            )
        )
        .mappings()
        .all()
    )
    return [
        RegistrationRow(
            user_id=user_id,
            registration_id=UUID(str(row["id"])),
            activity_id=UUID(str(row["activity_id"])),
            registration_status=row["status"],
            attendance_status=row["attendance_status"],
            starts_at=row["starts_at"],
            ends_at=row["ends_at"],
            activity_status=row["activity_status"],
            activity_title_code=row["title"] or "",
        )
        for row in rows
    ]


async def _load_selection_rows(session: AsyncSession, user_id: UUID) -> list[SelectionRow]:
    rows = (
        (
            await session.execute(
                text(
                    # One row per activity the member is a frozen candidate in.
                    # The submission is LEFT JOINed: "never started" and "draft"
                    # are both pending, and the domain decides which is which.
                    "SELECT e.activity_id,s.status AS submission_status,"
                    "a.post_event_choice_enabled,a.post_event_choice_opens_at,a.post_event_choice_closes_at "
                    "FROM activity_candidate_entries e "
                    "JOIN activity_candidate_snapshots snap ON snap.id=e.snapshot_id AND snap.status='frozen' "
                    "JOIN activities a ON a.id=e.activity_id "
                    "LEFT JOIN activity_selection_submissions s "
                    "  ON s.snapshot_id=e.snapshot_id AND s.chooser_user_id=e.user_id "
                    "WHERE e.user_id=:user_id AND e.eligibility='eligible'"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .all()
    )
    return [
        SelectionRow(
            user_id=user_id,
            activity_id=UUID(str(row["activity_id"])),
            submission_status=row["submission_status"],
            choice_enabled=bool(row["post_event_choice_enabled"]),
            choice_opens_at=row["post_event_choice_opens_at"],
            choice_closes_at=row["post_event_choice_closes_at"],
        )
        for row in rows
    ]


async def _load_notification_rows(
    session: AsyncSession, user_id: UUID, *, limit: int
) -> list[NotificationRow]:
    rows = (
        (
            await session.execute(
                text(
                    # There is no `notifications` table in this schema: in-app
                    # delivery is `notification_deliveries`, which models no
                    # read state. So "unread" degrades honestly to "recently
                    # delivered and not yet superseded" and read_at is NULL for
                    # every row. Wire a real read-state column before claiming
                    # an unread badge is accurate.
                    "SELECT d.id, i.category, d.created_at,"
                    " CAST(NULL AS timestamptz) AS read_at "
                    "FROM notification_deliveries d "
                    "JOIN notification_intents i ON i.id=d.notification_intent_id "
                    "WHERE d.user_id=:user_id AND d.channel='in_app' "
                    "  AND d.status IN ('sent','delivered') "
                    "ORDER BY d.created_at DESC LIMIT :limit"
                ),
                {"user_id": str(user_id), "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        NotificationRow(
            user_id=user_id,
            notification_id=UUID(str(row["id"])),
            category=row["category"],
            created_at=row["created_at"],
            read_at=row["read_at"],
        )
        for row in rows
    ]


async def _load_entitlement_row(session: AsyncSession, user_id: UUID) -> EntitlementRow | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT e.granted,e.consumed,e.expires_at,w.status AS wait_pool_status "
                    "FROM matchmaking_entitlements e "
                    "LEFT JOIN matchmaking_wait_pool_entries w ON w.user_id=e.user_id "
                    "WHERE e.user_id=:user_id"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return EntitlementRow(
        user_id=user_id,
        granted=int(row["granted"]),
        consumed=int(row["consumed"]),
        expires_at=row["expires_at"],
        wait_pool_status=row["wait_pool_status"],
    )


async def _relationship_status(session: AsyncSession, user_id: UUID) -> str | None:
    """Read the MATCH-001 gate. A missing row is not "single"."""

    row = (
        (
            await session.execute(
                text("SELECT status FROM member_relationship_statuses WHERE user_id=:user_id"),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    return row["status"] if row else None


async def _dismissed_keys(session: AsyncSession, user_id: UUID) -> set[str]:
    rows = (
        await session.execute(
            text("SELECT task_key FROM member_dashboard_task_dismissals WHERE user_id=:user_id"),
            {"user_id": str(user_id)},
        )
    ).all()
    return {str(row[0]) for row in rows}


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


async def _section(
    session: AsyncSession,
    key: SectionKey,
    loader: Any,
    builder: Any,
    *,
    user_id: UUID,
) -> SectionOutcome:
    """Load one section's rows and build it, degrading on any failure.

    The load and the build are wrapped together on purpose: a transport error
    and a rule violation are the same thing to the member, and both must leave
    the other five sections standing.
    """

    try:
        rows = await loader()
    except Exception as error:  # noqa: BLE001 - deliberate, see docstring
        outcome = SectionOutcome(
            key=key,
            ok=False,
            error_code="SECTION_SOURCE_UNAVAILABLE",
            error_message=f"{type(error).__name__}: {error}",
        )
        await _record_incident(session, user_id=user_id, outcome=outcome)
        return outcome
    outcome = collect_section(key, lambda: builder(rows))
    if not outcome.ok:
        await _record_incident(session, user_id=user_id, outcome=outcome)
    return outcome


async def get_dashboard(
    session: AsyncSession,
    *,
    user_id: UUID,
    locale: str = "zh-CN",
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Aggregate every section a member is authorized to see.

    Returns the sections that worked plus a ``degraded`` list naming the ones
    that did not. A relationship-gated section is dropped entirely for an
    ineligible member and appears in neither list.
    """

    enabled()
    now = _now()
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    relationship_status = await _safe_relationship_status(session, user_id)
    dismissed = await _safe_dismissed_keys(session, user_id)

    outcomes: list[SectionOutcome] = [
        await _section(
            session,
            SectionKey.SURVEY_TASKS,
            lambda: _load_survey_rows(session, user_id),
            lambda rows: build_survey_section(
                rows, user_id=user_id, now=now, limit=limit, offset=offset, dismissed_keys=dismissed
            ),
            user_id=user_id,
        ),
        await _section(
            session,
            SectionKey.RESULT_LETTERS,
            lambda: _load_letter_rows(session, user_id),
            lambda rows: build_result_letter_section(
                rows, user_id=user_id, now=now, limit=limit, offset=offset
            ),
            user_id=user_id,
        ),
        await _section(
            session,
            SectionKey.REGISTRATIONS,
            lambda: _load_registration_rows(session, user_id, locale=locale),
            lambda rows: build_registration_section(
                rows, user_id=user_id, now=now, limit=limit, offset=offset
            ),
            user_id=user_id,
        ),
        await _section(
            session,
            SectionKey.MUTUAL_SELECTION,
            lambda: _load_selection_rows(session, user_id),
            lambda rows: build_selection_section(
                rows, user_id=user_id, now=now, limit=limit, offset=offset
            ),
            user_id=user_id,
        ),
        await _section(
            session,
            SectionKey.NOTIFICATIONS,
            lambda: _load_notification_rows(session, user_id, limit=MAX_PAGE_SIZE),
            lambda rows: build_notification_section(
                rows, user_id=user_id, now=now, limit=limit, offset=offset
            ),
            user_id=user_id,
        ),
    ]
    # MATCH-001: the entitlement row is not even read for an ineligible member.
    if is_matchmaking_allowed(relationship_status):
        outcomes.append(
            await _section(
                session,
                SectionKey.MATCHMAKING,
                lambda: _load_entitlement_row(session, user_id),
                lambda row: build_matchmaking_section(
                    row, user_id=user_id, relationship_status=relationship_status, now=now
                ),
                user_id=user_id,
            )
        )
    view = assemble_dashboard(outcomes, now=now, relationship_status=relationship_status)
    payload = view.as_dict()
    payload["relationship_gate"] = {
        "matchmaking_available": is_matchmaking_allowed(relationship_status)
    }
    return payload


async def _safe_relationship_status(session: AsyncSession, user_id: UUID) -> str | None:
    """A gate that cannot be read is a closed gate."""

    try:
        return await _relationship_status(session, user_id)
    except Exception:  # noqa: BLE001 - fail closed, never open
        return None


async def _safe_dismissed_keys(session: AsyncSession, user_id: UUID) -> set[str]:
    try:
        return await _dismissed_keys(session, user_id)
    except Exception:  # noqa: BLE001 - a missing dismissal list shows more, not less
        return set()


async def get_section(
    session: AsyncSession,
    *,
    user_id: UUID,
    section: str,
    locale: str = "zh-CN",
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Page one section on its own. Used by "show all" links.

    Unlike :func:`get_dashboard` this *does* surface a failure as an error: the
    member explicitly asked for this one thing, so silently returning an empty
    panel would be misleading.
    """

    enabled()
    now = _now()
    try:
        key = SectionKey(section)
    except ValueError as exc:
        raise VavError(
            "DASHBOARD_SECTION_UNKNOWN", "Unknown dashboard section.", status_code=404
        ) from exc
    relationship_status = await _safe_relationship_status(session, user_id)
    if key in (SectionKey.MATCHMAKING,) and not is_matchmaking_allowed(relationship_status):
        # 404, not 403: an ineligible member is not told the section exists.
        raise VavError("DASHBOARD_SECTION_UNKNOWN", "Unknown dashboard section.", status_code=404)
    try:
        if key is SectionKey.SURVEY_TASKS:
            payload = build_survey_section(
                await _load_survey_rows(session, user_id),
                user_id=user_id,
                now=now,
                limit=limit,
                offset=offset,
                dismissed_keys=await _safe_dismissed_keys(session, user_id),
            )
        elif key is SectionKey.RESULT_LETTERS:
            payload = build_result_letter_section(
                await _load_letter_rows(session, user_id),
                user_id=user_id,
                now=now,
                limit=limit,
                offset=offset,
            )
        elif key is SectionKey.REGISTRATIONS:
            payload = build_registration_section(
                await _load_registration_rows(session, user_id, locale=locale),
                user_id=user_id,
                now=now,
                limit=limit,
                offset=offset,
            )
        elif key is SectionKey.MUTUAL_SELECTION:
            payload = build_selection_section(
                await _load_selection_rows(session, user_id),
                user_id=user_id,
                now=now,
                limit=limit,
                offset=offset,
            )
        elif key is SectionKey.NOTIFICATIONS:
            payload = build_notification_section(
                await _load_notification_rows(session, user_id, limit=MAX_PAGE_SIZE),
                user_id=user_id,
                now=now,
                limit=limit,
                offset=offset,
            )
        else:
            payload = build_matchmaking_section(
                await _load_entitlement_row(session, user_id),
                user_id=user_id,
                relationship_status=relationship_status,
                now=now,
            )
    except DashboardRuleError as error:
        raise _fail(error) from error
    return payload.as_dict()


# ---------------------------------------------------------------------------
# Preferences and dismissals
# ---------------------------------------------------------------------------


async def get_preferences(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT hidden_sections,page_size FROM member_dashboard_preferences "
                    "WHERE user_id=:user_id"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return {"hidden_sections": [], "page_size": DEFAULT_PAGE_SIZE}
    return {
        "hidden_sections": list(row["hidden_sections"] or []),
        "page_size": int(row["page_size"]),
    }


async def set_preferences(
    session: AsyncSession, *, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    enabled()
    await session.execute(
        text(
            "INSERT INTO member_dashboard_preferences (user_id,hidden_sections,page_size) "
            "VALUES (:user_id,CAST(:hidden AS jsonb),:page_size) "
            "ON CONFLICT (user_id) DO UPDATE SET hidden_sections=EXCLUDED.hidden_sections,"
            "page_size=EXCLUDED.page_size,updated_at=now()"
        ),
        {
            "user_id": str(user_id),
            "hidden": _json(payload["hidden_sections"]),
            "page_size": int(payload["page_size"]),
        },
    )
    return await get_preferences(session, user_id)


async def dismiss_task(
    session: AsyncSession, *, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Hide one task for this member only.

    Idempotent by unique key: a double tap on a flaky connection dismisses the
    task once. A dismissal never completes the underlying task - the survey is
    still due, it is simply off the home screen.
    """

    enabled()
    try:
        task_type = TaskType(payload["task_type"])
    except ValueError as exc:
        raise VavError(
            "DASHBOARD_TASK_TYPE_UNKNOWN", "Unknown task type.", status_code=422
        ) from exc
    task_key = str(payload["task_key"])
    if not task_key.startswith(f"{task_type.value}:"):
        raise VavError(
            "DASHBOARD_TASK_KEY_MISMATCH",
            "The task key does not belong to the supplied task type.",
            status_code=422,
        )
    await session.execute(
        text(
            "INSERT INTO member_dashboard_task_dismissals (user_id,task_type,task_key) "
            "VALUES (:user_id,:task_type,:task_key) "
            "ON CONFLICT (user_id,task_key) DO NOTHING"
        ),
        {"user_id": str(user_id), "task_type": task_type.value, "task_key": task_key},
    )
    return {"task_key": task_key, "dismissed": True}


async def restore_task(session: AsyncSession, *, user_id: UUID, task_key: str) -> dict[str, Any]:
    enabled()
    await session.execute(
        text(
            "DELETE FROM member_dashboard_task_dismissals "
            "WHERE user_id=:user_id AND task_key=:task_key"
        ),
        {"user_id": str(user_id), "task_key": task_key},
    )
    return {"task_key": task_key, "dismissed": False}


# ---------------------------------------------------------------------------
# Administrative views
# ---------------------------------------------------------------------------


async def list_section_incidents(
    session: AsyncSession, *, section: str | None = None, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    """Operator view of degraded sections: which module, how often, when."""

    enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT section_key,error_code,count(*) AS occurrences,"
                    "max(occurred_at) AS last_seen_at "
                    "FROM member_dashboard_section_incidents "
                    "WHERE (:section IS NULL OR section_key=:section) "
                    "GROUP BY section_key,error_code "
                    "ORDER BY occurrences DESC LIMIT :limit OFFSET :offset"
                ),
                {"section": section, "limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [
            {
                "section_key": row["section_key"],
                "error_code": row["error_code"],
                "occurrences": int(row["occurrences"]),
                "last_seen_at": row["last_seen_at"].isoformat() if row["last_seen_at"] else None,
            }
            for row in rows
        ]
    }


async def upsert_task_type_override(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Point a task type at a different route without a deploy.

    The template is validated as site-relative here *and* re-validated by
    ``domain.build_deep_link`` at render time, so a bad row cannot turn a
    dashboard card into an off-site redirect.
    """

    enabled()
    template = str(payload["deep_link_template"])
    if not template.startswith("/") or template.startswith("//"):
        raise VavError(
            "DEEP_LINK_NOT_RELATIVE", "A deep link must be a site-relative path.", status_code=422
        )
    await session.execute(
        text(
            "INSERT INTO member_dashboard_task_type_overrides "
            "(task_type,deep_link_template,base_priority,is_active,updated_by) "
            "VALUES (:task_type,:template,:priority,:is_active,:actor) "
            "ON CONFLICT (task_type) DO UPDATE SET deep_link_template=EXCLUDED.deep_link_template,"
            "base_priority=EXCLUDED.base_priority,is_active=EXCLUDED.is_active,"
            "updated_by=EXCLUDED.updated_by,updated_at=now()"
        ),
        {
            "task_type": payload["task_type"],
            "template": template,
            "priority": payload["base_priority"],
            "is_active": bool(payload["is_active"]),
            "actor": str(actor_id),
        },
    )
    await _publish(
        session,
        "member_dashboard.task_type.updated.v1",
        actor_id,
        {"task_type": payload["task_type"], "deep_link_template": template},
    )
    return {"task_type": payload["task_type"], "deep_link_template": template}


async def list_task_type_overrides(session: AsyncSession) -> dict[str, Any]:
    enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT task_type,deep_link_template,base_priority,is_active,updated_at "
                    "FROM member_dashboard_task_type_overrides ORDER BY task_type"
                )
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [
            {
                "task_type": row["task_type"],
                "deep_link_template": row["deep_link_template"],
                "base_priority": row["base_priority"],
                "is_active": bool(row["is_active"]),
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in rows
        ]
    }


async def preview_member_dashboard(session: AsyncSession, *, user_id: UUID) -> dict[str, Any]:
    """Support view: exactly what a given member's dashboard renders.

    Deliberately reuses :func:`get_dashboard` rather than a parallel query set,
    so a support agent cannot be shown something the member is not shown.
    """

    return await get_dashboard(session, user_id=user_id)


def paginate_items(items: list[Any], *, limit: int, offset: int) -> dict[str, Any]:
    """Thin wrapper so admin listings paginate the same way member ones do."""

    try:
        return paginate(items, limit=limit, offset=offset).as_dict()
    except DashboardRuleError as error:
        raise _fail(error) from error
