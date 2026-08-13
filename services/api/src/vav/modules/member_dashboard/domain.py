"""Pure member dashboard aggregation rules (B18 / DASH-001).

The dashboard owns no data. Every number it shows belongs to another module,
so the one thing this file must guarantee is that the dashboard's predicates
are *the same* predicates the source modules use. Where a rule already exists
in :mod:`vav.modules.post_event.domain` or
:mod:`vav.modules.matchmaking_entitlements.domain`, the constant below is a
deliberate mirror with a pointer back to the original; it is never a rewritten
approximation. A count that disagrees with the module it came from is a bug in
this file, not a display choice.

Requirement coverage:

* DASH-001 authorization-aware aggregation, stable task types, deep links,
  priority, due dates, pagination
* DASH-001 graceful degradation: one failing section degrades that section only
* DASH-001 no cross-user leakage: every builder re-checks row ownership
* MATCH-001 relationship gate: a member who is not single/separated/widowed
  sees no matchmaking section at all - not an empty one, not a locked one

No database, settings, network or clock access lives here: ``now`` is always an
argument, so every rule below is testable on a machine with no PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID


class DashboardRuleError(Exception):
    """Raised when a caller violates a dashboard aggregation rule.

    ``code`` is a stable machine identifier; ``message`` is operator-facing
    English. Member-facing copy is localized in the frontend from ``code``.
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


# ---------------------------------------------------------------------------
# Mirrored predicates
#
# Each frozenset below states which module it mirrors. Changing one without the
# other is what makes a dashboard badge disagree with the page it links to.
# ---------------------------------------------------------------------------

#: Mirrors ``post_event.domain.CONFIRMED_REGISTRATION_STATUSES``. Only a
#: confirmed registration is a confirmed attendance anywhere in the platform.
CONFIRMED_REGISTRATION_STATUSES: frozenset[str] = frozenset({"confirmed"})

#: Registration statuses that still represent a live intent to attend, and so
#: belong on the dashboard's "upcoming" list. Cancelled, rejected and expired
#: registrations are gone; they appear in neither bucket.
ACTIVE_REGISTRATION_STATUSES: frozenset[str] = frozenset(
    {
        "confirmed",
        "pending_approval",
        "approved_pending_payment",
        "pending_payment",
        "payment_processing",
        "waitlisted",
    }
)

#: Registration statuses that end the relationship with the activity.
CLOSED_REGISTRATION_STATUSES: frozenset[str] = frozenset({"rejected", "cancelled", "expired"})

#: Mirrors ``post_event.domain.ABSENT_ATTENDANCE_STATUSES``.
ABSENT_ATTENDANCE_STATUSES: frozenset[str] = frozenset(
    {"not_checked_in", "no_show", "checkin_revoked"}
)

#: Mirrors ``post_event.domain.MEMBER_VISIBLE_LETTER_STATUSES``. A letter that
#: is drafted, in review, approved-but-unpublished or revoked is invisible.
MEMBER_VISIBLE_LETTER_STATUSES: frozenset[str] = frozenset({"published"})

#: Mirrors ``post_event.domain.TaskStatus``: the two states in which a survey
#: task is still actionable by the member.
OPEN_SURVEY_TASK_STATUSES: frozenset[str] = frozenset({"pending", "in_progress"})

#: Mirrors ``post_event.domain.TaskStatus``: terminal states.
CLOSED_SURVEY_TASK_STATUSES: frozenset[str] = frozenset({"completed", "expired", "waived"})

#: Mirrors ``matchmaking_entitlements.domain.MATCHMAKING_ELIGIBLE_STATUSES``
#: (MATCH-001). ``undisclosed`` is deliberately absent: a member who never
#: answered is not single, and the gate fails closed.
MATCHMAKING_ELIGIBLE_STATUSES: frozenset[str] = frozenset({"single", "separated", "widowed"})


def is_matchmaking_allowed(relationship_status: str | None) -> bool:
    """MATCH-001, mirrored for the dashboard.

    Returns ``False`` for ``None`` and for any unknown value, so a schema drift
    or a missing row closes matchmaking rather than opening it.
    """

    if relationship_status is None:
        return False
    return relationship_status in MATCHMAKING_ELIGIBLE_STATUSES


# ---------------------------------------------------------------------------
# Sections and task types
# ---------------------------------------------------------------------------


class SectionKey(StrEnum):
    """Stable section identifiers. The frontend keys its layout on these."""

    SURVEY_TASKS = "survey_tasks"
    RESULT_LETTERS = "result_letters"
    REGISTRATIONS = "registrations"
    MUTUAL_SELECTION = "mutual_selection"
    MATCHMAKING = "matchmaking"
    NOTIFICATIONS = "notifications"


#: Sections that only exist for a member who passes the MATCH-001 gate.
RELATIONSHIP_GATED_SECTIONS: frozenset[SectionKey] = frozenset({SectionKey.MATCHMAKING})


class TaskType(StrEnum):
    """Stable task-type identifiers.

    These strings are an API contract: they are stored in dismissal rows, sent
    in notification payloads and used by the mobile client to pick an icon.
    Renaming one is a breaking change; adding one is not.
    """

    SURVEY_PENDING = "survey_pending"
    MUTUAL_SELECTION_PENDING = "mutual_selection_pending"
    RESULT_LETTER_UNREAD = "result_letter_unread"
    REGISTRATION_UPCOMING = "registration_upcoming"
    MATCHMAKING_ATTEMPT_AVAILABLE = "matchmaking_attempt_available"
    NOTIFICATION_UNREAD = "notification_unread"


TASK_TYPE_SECTIONS: Mapping[TaskType, SectionKey] = {
    TaskType.SURVEY_PENDING: SectionKey.SURVEY_TASKS,
    TaskType.MUTUAL_SELECTION_PENDING: SectionKey.MUTUAL_SELECTION,
    TaskType.RESULT_LETTER_UNREAD: SectionKey.RESULT_LETTERS,
    TaskType.REGISTRATION_UPCOMING: SectionKey.REGISTRATIONS,
    TaskType.MATCHMAKING_ATTEMPT_AVAILABLE: SectionKey.MATCHMAKING,
    TaskType.NOTIFICATION_UNREAD: SectionKey.NOTIFICATIONS,
}

#: Relative in-app routes. They are relative on purpose: the dashboard never
#: emits an absolute URL, so a compromised row cannot redirect a member off the
#: platform. An operator may override a template through the registry table;
#: these are the defaults the code ships with.
DEEP_LINK_TEMPLATES: Mapping[TaskType, str] = {
    TaskType.SURVEY_PENDING: "/account/surveys/{assignment_id}",
    TaskType.MUTUAL_SELECTION_PENDING: "/account/activities/{activity_id}/selection",
    TaskType.RESULT_LETTER_UNREAD: "/account/result-letters/{letter_id}",
    TaskType.REGISTRATION_UPCOMING: "/account/registrations/{registration_id}",
    TaskType.MATCHMAKING_ATTEMPT_AVAILABLE: "/account/matchmaking",
    TaskType.NOTIFICATION_UNREAD: "/account/notifications/{notification_id}",
}


def build_deep_link(
    task_type: TaskType,
    params: Mapping[str, object],
    *,
    templates: Mapping[TaskType, str] | None = None,
) -> str:
    """Render a relative deep link, refusing anything that is not one.

    A missing placeholder is an error rather than an empty segment: a link to
    ``/account/surveys/`` would silently send the member to a list page and
    look like the task vanished.
    """

    table = dict(templates or DEEP_LINK_TEMPLATES)
    template = table.get(task_type)
    if not template:
        raise DashboardRuleError(
            "DEEP_LINK_TEMPLATE_MISSING",
            "No deep-link template is configured for this task type.",
            details={"task_type": task_type.value},
        )
    if not template.startswith("/") or template.startswith("//"):
        raise DashboardRuleError(
            "DEEP_LINK_NOT_RELATIVE",
            "A deep link must be a site-relative path.",
            details={"task_type": task_type.value, "template": template},
        )
    rendered = template
    cursor = 0
    while True:
        start = rendered.find("{", cursor)
        if start == -1:
            break
        end = rendered.find("}", start)
        if end == -1:
            raise DashboardRuleError(
                "DEEP_LINK_TEMPLATE_MALFORMED", "A deep-link placeholder is not closed."
            )
        name = rendered[start + 1 : end]
        if name not in params or params[name] is None:
            raise DashboardRuleError(
                "DEEP_LINK_PARAMETER_MISSING",
                "A deep-link placeholder has no value.",
                details={"task_type": task_type.value, "parameter": name},
            )
        value = str(params[name])
        if "/" in value or ".." in value:
            raise DashboardRuleError(
                "DEEP_LINK_PARAMETER_INVALID",
                "A deep-link parameter may not contain path separators.",
                details={"task_type": task_type.value, "parameter": name},
            )
        rendered = rendered[:start] + value + rendered[end + 1 :]
        cursor = start + len(value)
    return rendered


# ---------------------------------------------------------------------------
# Priority and task shape
# ---------------------------------------------------------------------------


class TaskPriority(StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


PRIORITY_RANK: Mapping[TaskPriority, int] = {
    TaskPriority.URGENT: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.NORMAL: 2,
    TaskPriority.LOW: 3,
}

URGENT_WINDOW = timedelta(hours=6)
HIGH_WINDOW = timedelta(hours=24)
NORMAL_WINDOW = timedelta(days=3)


def due_priority(
    due_at: datetime | None, now: datetime, *, base: TaskPriority = TaskPriority.NORMAL
) -> TaskPriority:
    """Derive urgency from the remaining time, never from a stored guess.

    A task with no deadline keeps its base priority. A task already past its
    deadline is urgent rather than hidden, because the member may still be able
    to act on it (the source module decides that, not the dashboard).
    """

    if due_at is None:
        return base
    _require_aware(due_at=due_at, now=now)
    remaining = due_at - now
    if remaining <= URGENT_WINDOW:
        return TaskPriority.URGENT
    if remaining <= HIGH_WINDOW:
        return TaskPriority.HIGH
    if remaining <= NORMAL_WINDOW:
        return TaskPriority.NORMAL
    return TaskPriority.LOW


def _require_aware(**values: datetime | None) -> None:
    for label, value in values.items():
        if value is not None and value.tzinfo is None:
            raise DashboardRuleError("DASHBOARD_NAIVE_DATETIME", f"{label} must be timezone-aware.")


@dataclass(frozen=True)
class DashboardTask:
    """One actionable item, in the shape every section emits."""

    task_type: TaskType
    #: Stable, per-member unique key. Dismissals and read-marks are keyed on it,
    #: so it must not change between two renders of the same underlying row.
    task_key: str
    subject_id: UUID
    deep_link: str
    priority: TaskPriority
    due_at: datetime | None = None
    activity_id: UUID | None = None
    #: An identifier the frontend localizes. The backend ships no display copy.
    title_code: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def section(self) -> SectionKey:
        return TASK_TYPE_SECTIONS[self.task_type]

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type.value,
            "task_key": self.task_key,
            "section": self.section.value,
            "subject_id": str(self.subject_id),
            "deep_link": self.deep_link,
            "priority": self.priority.value,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "activity_id": str(self.activity_id) if self.activity_id else None,
            "title_code": self.title_code,
            "metadata": dict(self.metadata),
        }


def sort_tasks(tasks: Iterable[DashboardTask]) -> list[DashboardTask]:
    """Deterministic ordering: urgency first, then deadline, then key.

    The ``task_key`` tie-break is what makes pagination stable - without it two
    equally urgent tasks could swap places between page 1 and page 2 and the
    member would never see one of them.
    """

    far_future = datetime.max.replace(tzinfo=None)

    def key(task: DashboardTask) -> tuple[int, str, str]:
        deadline = task.due_at.isoformat() if task.due_at else far_future.isoformat()
        return (PRIORITY_RANK[task.priority], deadline, task.task_key)

    return sorted(tasks, key=key)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class Page:
    items: tuple[Any, ...]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": [item.as_dict() if hasattr(item, "as_dict") else item for item in self.items],
            "total": self.total,
            "limit": self.limit,
            "offset": self.offset,
            "has_more": self.has_more,
        }


def paginate(
    items: Sequence[Any],
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    max_limit: int = MAX_PAGE_SIZE,
) -> Page:
    """Slice an already-ordered sequence.

    ``total`` is the count *before* slicing, so a badge stays correct while the
    member is on page three.
    """

    if limit < 1:
        raise DashboardRuleError("PAGE_LIMIT_INVALID", "limit must be at least 1.")
    if limit > max_limit:
        raise DashboardRuleError(
            "PAGE_LIMIT_TOO_LARGE",
            f"limit must not exceed {max_limit}.",
            details={"max_limit": max_limit},
        )
    if offset < 0:
        raise DashboardRuleError("PAGE_OFFSET_INVALID", "offset must not be negative.")
    return Page(
        items=tuple(items[offset : offset + limit]),
        total=len(items),
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Ownership guard (no cross-user leakage)
# ---------------------------------------------------------------------------


def assert_rows_belong_to(
    user_id: UUID, rows: Iterable[Any], *, attribute: str = "user_id"
) -> None:
    """Refuse to render a row that belongs to somebody else.

    This is a second line of defence: every query is already filtered by the
    authenticated user id. It exists because the first line is a WHERE clause
    in a string, and a mistake there is invisible until it is a data breach.
    Raising here degrades the section (see :func:`collect_section`) instead of
    emitting the row, so the failure mode is a missing panel, not a leak.
    """

    for row in rows:
        owner = getattr(row, attribute, None)
        if owner is None and isinstance(row, Mapping):
            owner = row.get(attribute)
        if owner != user_id:
            raise DashboardRuleError(
                "DASHBOARD_ROW_OWNER_MISMATCH",
                "A dashboard row does not belong to the authenticated member.",
                details={"expected_user_id": str(user_id)},
            )


# ---------------------------------------------------------------------------
# Section inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SurveyTaskRow:
    user_id: UUID
    task_id: UUID
    assignment_id: UUID
    activity_id: UUID
    status: str
    due_at: datetime
    activity_title_code: str = ""


@dataclass(frozen=True)
class ResultLetterRow:
    user_id: UUID
    letter_id: UUID
    activity_id: UUID
    status: str
    published_at: datetime | None = None
    read_at: datetime | None = None


@dataclass(frozen=True)
class RegistrationRow:
    user_id: UUID
    registration_id: UUID
    activity_id: UUID
    registration_status: str
    attendance_status: str
    starts_at: datetime
    ends_at: datetime | None = None
    activity_status: str = "published"
    activity_title_code: str = ""


@dataclass(frozen=True)
class SelectionRow:
    user_id: UUID
    activity_id: UUID
    #: ``None`` means the member has not started a submission at all.
    submission_status: str | None
    choice_enabled: bool
    choice_opens_at: datetime | None
    choice_closes_at: datetime | None
    activity_title_code: str = ""


@dataclass(frozen=True)
class EntitlementRow:
    user_id: UUID
    granted: int
    consumed: int
    expires_at: datetime | None = None
    wait_pool_status: str | None = None


@dataclass(frozen=True)
class NotificationRow:
    user_id: UUID
    notification_id: UUID
    category: str
    created_at: datetime
    read_at: datetime | None = None


# ---------------------------------------------------------------------------
# Task-state resolution (completed / expired stay consistent)
# ---------------------------------------------------------------------------


class TaskState(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    EXPIRED = "expired"
    WAIVED = "waived"


def resolve_survey_task_state(*, status: str, due_at: datetime, now: datetime) -> TaskState:
    """Resolve what a survey task really is *right now*.

    The stored status lags: the sweeper that flips ``pending`` to ``expired``
    runs on a schedule. The dashboard therefore derives expiry from the same
    ``due_at`` the sweeper uses, so a member never sees an actionable card for
    a task the API would refuse. When the sweeper catches up, nothing changes -
    which is exactly the consistency DASH-001 asks for.
    """

    _require_aware(due_at=due_at, now=now)
    if status == "completed":
        return TaskState.COMPLETED
    if status == "waived":
        return TaskState.WAIVED
    if status == "expired":
        return TaskState.EXPIRED
    if status not in OPEN_SURVEY_TASK_STATUSES:
        raise DashboardRuleError(
            "SURVEY_TASK_STATUS_UNKNOWN",
            "Unknown survey task status.",
            details={"status": status},
        )
    return TaskState.EXPIRED if now > due_at else TaskState.OPEN


class RegistrationBucket(StrEnum):
    UPCOMING = "upcoming"
    IN_PROGRESS = "in_progress"
    PAST = "past"
    #: Cancelled, rejected or expired: shown in neither list.
    INACTIVE = "inactive"


def classify_registration(row: RegistrationRow, *, now: datetime) -> RegistrationBucket:
    _require_aware(starts_at=row.starts_at, ends_at=row.ends_at, now=now)
    if row.registration_status in CLOSED_REGISTRATION_STATUSES:
        return RegistrationBucket.INACTIVE
    if row.registration_status not in ACTIVE_REGISTRATION_STATUSES:
        raise DashboardRuleError(
            "REGISTRATION_STATUS_UNKNOWN",
            "Unknown registration status.",
            details={"status": row.registration_status},
        )
    end = row.ends_at or row.starts_at
    if now < row.starts_at:
        return RegistrationBucket.UPCOMING
    if now <= end:
        return RegistrationBucket.IN_PROGRESS
    return RegistrationBucket.PAST


def is_letter_unread(row: ResultLetterRow) -> bool:
    """Unread means published *and* never opened. An unpublished letter is not
    "unread" - it does not exist as far as the member is concerned."""

    return row.status in MEMBER_VISIBLE_LETTER_STATUSES and row.read_at is None


def is_selection_pending(row: SelectionRow, *, now: datetime) -> bool:
    """Pending means the member still has an open window and no submission.

    A ``draft`` submission is still pending: autosaving is not choosing. A
    ``submitted`` one is done, even if the edit window is open, because the
    member has nothing they must do.
    """

    _require_aware(
        choice_opens_at=row.choice_opens_at, choice_closes_at=row.choice_closes_at, now=now
    )
    if not row.choice_enabled:
        return False
    if row.submission_status == "submitted":
        return False
    if row.choice_opens_at is not None and now < row.choice_opens_at:
        return False
    return row.choice_closes_at is None or now <= row.choice_closes_at


def entitlement_balance(row: EntitlementRow, *, now: datetime) -> int:
    """Mirrors ``matchmaking_entitlements.domain.EntitlementState.balance``.

    An expired entitlement reports zero rather than its raw arithmetic, so the
    dashboard badge and the generation endpoint agree.
    """

    _require_aware(expires_at=row.expires_at, now=now)
    if row.expires_at is not None and now >= row.expires_at:
        return 0
    return max(0, row.granted - row.consumed)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionPayload:
    key: SectionKey
    #: The badge number. Always the pre-pagination total.
    count: int
    page: Page
    extra: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key.value, "count": self.count, **self.page.as_dict(), **self.extra}


def build_survey_section(
    rows: Sequence[SurveyTaskRow],
    *,
    user_id: UUID,
    now: datetime,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    dismissed_keys: Iterable[str] = (),
) -> SectionPayload:
    assert_rows_belong_to(user_id, rows)
    dismissed = set(dismissed_keys)
    tasks: list[DashboardTask] = []
    for row in rows:
        if (
            resolve_survey_task_state(status=row.status, due_at=row.due_at, now=now)
            is not TaskState.OPEN
        ):
            continue
        task_key = task_key_for(TaskType.SURVEY_PENDING, row.task_id)
        if task_key in dismissed:
            continue
        tasks.append(
            DashboardTask(
                task_type=TaskType.SURVEY_PENDING,
                task_key=task_key,
                subject_id=row.assignment_id,
                deep_link=build_deep_link(
                    TaskType.SURVEY_PENDING, {"assignment_id": row.assignment_id}
                ),
                priority=due_priority(row.due_at, now),
                due_at=row.due_at,
                activity_id=row.activity_id,
                title_code=row.activity_title_code,
            )
        )
    ordered = sort_tasks(tasks)
    return SectionPayload(
        key=SectionKey.SURVEY_TASKS,
        count=len(ordered),
        page=paginate(ordered, limit=limit, offset=offset),
    )


def build_result_letter_section(
    rows: Sequence[ResultLetterRow],
    *,
    user_id: UUID,
    now: datetime,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> SectionPayload:
    assert_rows_belong_to(user_id, rows)
    tasks = [
        DashboardTask(
            task_type=TaskType.RESULT_LETTER_UNREAD,
            task_key=task_key_for(TaskType.RESULT_LETTER_UNREAD, row.letter_id),
            subject_id=row.letter_id,
            deep_link=build_deep_link(TaskType.RESULT_LETTER_UNREAD, {"letter_id": row.letter_id}),
            # A letter has no deadline; it is high because it is the payoff of
            # the whole event and members ask about it.
            priority=TaskPriority.HIGH,
            due_at=None,
            activity_id=row.activity_id,
            metadata={"published_at": row.published_at.isoformat() if row.published_at else None},
        )
        for row in rows
        if is_letter_unread(row)
    ]
    ordered = sort_tasks(tasks)
    return SectionPayload(
        key=SectionKey.RESULT_LETTERS,
        count=len(ordered),
        page=paginate(ordered, limit=limit, offset=offset),
    )


def build_registration_section(
    rows: Sequence[RegistrationRow],
    *,
    user_id: UUID,
    now: datetime,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> SectionPayload:
    """Upcoming registrations become tasks; past ones are a count and a list.

    ``confirmed_count`` uses the mirrored confirmed predicate so it matches the
    activities module's own "you are attending" number exactly.
    """

    assert_rows_belong_to(user_id, rows)
    upcoming: list[DashboardTask] = []
    past: list[dict[str, Any]] = []
    in_progress = 0
    confirmed_upcoming = 0
    for row in rows:
        bucket = classify_registration(row, now=now)
        if bucket is RegistrationBucket.INACTIVE:
            continue
        if bucket is RegistrationBucket.PAST:
            past.append(
                {
                    "registration_id": str(row.registration_id),
                    "activity_id": str(row.activity_id),
                    "registration_status": row.registration_status,
                    "attendance_status": row.attendance_status,
                    "attended": (
                        row.registration_status in CONFIRMED_REGISTRATION_STATUSES
                        and row.attendance_status not in ABSENT_ATTENDANCE_STATUSES
                    ),
                    "starts_at": row.starts_at.isoformat(),
                    "title_code": row.activity_title_code,
                }
            )
            continue
        if bucket is RegistrationBucket.IN_PROGRESS:
            in_progress += 1
        if row.registration_status in CONFIRMED_REGISTRATION_STATUSES:
            confirmed_upcoming += 1
        upcoming.append(
            DashboardTask(
                task_type=TaskType.REGISTRATION_UPCOMING,
                task_key=task_key_for(TaskType.REGISTRATION_UPCOMING, row.registration_id),
                subject_id=row.registration_id,
                deep_link=build_deep_link(
                    TaskType.REGISTRATION_UPCOMING, {"registration_id": row.registration_id}
                ),
                priority=due_priority(row.starts_at, now, base=TaskPriority.LOW),
                due_at=row.starts_at,
                activity_id=row.activity_id,
                title_code=row.activity_title_code,
                metadata={"registration_status": row.registration_status, "bucket": bucket.value},
            )
        )
    ordered = sort_tasks(upcoming)
    past.sort(key=lambda item: (item["starts_at"], item["registration_id"]), reverse=True)
    return SectionPayload(
        key=SectionKey.REGISTRATIONS,
        count=len(ordered),
        page=paginate(ordered, limit=limit, offset=offset),
        extra={
            "confirmed_upcoming_count": confirmed_upcoming,
            "in_progress_count": in_progress,
            "past": past[:limit],
            "past_count": len(past),
        },
    )


def build_selection_section(
    rows: Sequence[SelectionRow],
    *,
    user_id: UUID,
    now: datetime,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> SectionPayload:
    assert_rows_belong_to(user_id, rows)
    tasks = [
        DashboardTask(
            task_type=TaskType.MUTUAL_SELECTION_PENDING,
            task_key=task_key_for(TaskType.MUTUAL_SELECTION_PENDING, row.activity_id),
            subject_id=row.activity_id,
            deep_link=build_deep_link(
                TaskType.MUTUAL_SELECTION_PENDING, {"activity_id": row.activity_id}
            ),
            priority=due_priority(row.choice_closes_at, now),
            due_at=row.choice_closes_at,
            activity_id=row.activity_id,
            title_code=row.activity_title_code,
            metadata={"submission_status": row.submission_status},
        )
        for row in rows
        if is_selection_pending(row, now=now)
    ]
    ordered = sort_tasks(tasks)
    return SectionPayload(
        key=SectionKey.MUTUAL_SELECTION,
        count=len(ordered),
        page=paginate(ordered, limit=limit, offset=offset),
    )


def build_matchmaking_section(
    row: EntitlementRow | None,
    *,
    user_id: UUID,
    relationship_status: str | None,
    now: datetime,
) -> SectionPayload:
    """Build the matchmaking panel for a member who has already passed the gate.

    Callers must not reach this function for an ineligible member - see
    :func:`assemble_dashboard`, which drops the section before it is built. The
    check is repeated here anyway so a future caller cannot bypass MATCH-001 by
    calling the builder directly.
    """

    if not is_matchmaking_allowed(relationship_status):
        raise DashboardRuleError(
            "MATCHMAKING_NOT_AVAILABLE",
            "Matchmaking is only available to members who have declared they are single.",
            details={"relationship_status": relationship_status or "undisclosed"},
        )
    if row is not None:
        assert_rows_belong_to(user_id, [row])
    balance = entitlement_balance(row, now=now) if row is not None else 0
    tasks: list[DashboardTask] = []
    if balance > 0:
        tasks.append(
            DashboardTask(
                task_type=TaskType.MATCHMAKING_ATTEMPT_AVAILABLE,
                task_key=task_key_for(TaskType.MATCHMAKING_ATTEMPT_AVAILABLE, user_id),
                subject_id=user_id,
                deep_link=build_deep_link(TaskType.MATCHMAKING_ATTEMPT_AVAILABLE, {}),
                priority=TaskPriority.NORMAL,
            )
        )
    return SectionPayload(
        key=SectionKey.MATCHMAKING,
        count=balance,
        page=paginate(sort_tasks(tasks), limit=max(1, len(tasks))),
        extra={
            "balance": balance,
            "granted": row.granted if row else 0,
            "consumed": row.consumed if row else 0,
            "expires_at": row.expires_at.isoformat() if row and row.expires_at else None,
            "wait_pool_status": row.wait_pool_status if row else None,
        },
    )


def build_notification_section(
    rows: Sequence[NotificationRow],
    *,
    user_id: UUID,
    now: datetime,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> SectionPayload:
    assert_rows_belong_to(user_id, rows)
    tasks = [
        DashboardTask(
            task_type=TaskType.NOTIFICATION_UNREAD,
            task_key=task_key_for(TaskType.NOTIFICATION_UNREAD, row.notification_id),
            subject_id=row.notification_id,
            deep_link=build_deep_link(
                TaskType.NOTIFICATION_UNREAD, {"notification_id": row.notification_id}
            ),
            priority=TaskPriority.LOW,
            due_at=None,
            metadata={"category": row.category, "created_at": row.created_at.isoformat()},
        )
        for row in rows
        if row.read_at is None
    ]
    ordered = sort_tasks(tasks)
    return SectionPayload(
        key=SectionKey.NOTIFICATIONS,
        count=len(ordered),
        page=paginate(ordered, limit=limit, offset=offset),
    )


def task_key_for(task_type: TaskType, subject_id: UUID) -> str:
    """The stable identity of a task across renders, devices and releases."""

    return f"{task_type.value}:{subject_id}"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionOutcome:
    key: SectionKey
    ok: bool
    payload: SectionPayload | None = None
    error_code: str | None = None
    error_message: str | None = None


def collect_section(key: SectionKey, builder: Callable[[], SectionPayload]) -> SectionOutcome:
    """Run one section builder and turn any failure into a degraded outcome.

    This is the whole graceful-degradation guarantee in one place: the
    dashboard aggregates six independent modules, and the probability that all
    six are healthy is lower than the probability that any one of them is. A
    broken survey module must cost the member their survey panel, not their
    home screen.

    ``BaseException`` is deliberately *not* caught: a cancellation or a
    keyboard interrupt is not a degraded section.
    """

    try:
        return SectionOutcome(key=key, ok=True, payload=builder())
    except DashboardRuleError as error:
        return SectionOutcome(key=key, ok=False, error_code=error.code, error_message=error.message)
    except Exception as error:  # noqa: BLE001 - deliberate: see docstring
        return SectionOutcome(
            key=key,
            ok=False,
            error_code="SECTION_UNAVAILABLE",
            error_message=f"{type(error).__name__}: {error}",
        )


@dataclass(frozen=True)
class DashboardView:
    sections: Mapping[str, Any]
    degraded: tuple[str, ...]
    counts: Mapping[str, int]
    generated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "sections": dict(self.sections),
            "degraded": list(self.degraded),
            "counts": dict(self.counts),
            "total_open_tasks": sum(self.counts.values()),
            "generated_at": self.generated_at.isoformat(),
        }


def assemble_dashboard(
    outcomes: Sequence[SectionOutcome],
    *,
    now: datetime,
    relationship_status: str | None = None,
) -> DashboardView:
    """Combine section outcomes into the response, applying the MATCH-001 gate.

    Two rules that are easy to get wrong and are therefore enforced here:

    1. A relationship-gated section is removed entirely for an ineligible
       member. It appears in neither ``sections`` nor ``degraded``, because
       "unavailable to you" and "temporarily broken" must not look alike - the
       first would tell an ineligible member that matchmaking exists and is
       merely down right now.
    2. A degraded section contributes no count. A missing number is honest; a
       zero would read as "nothing to do".
    """

    _require_aware(now=now)
    allowed = is_matchmaking_allowed(relationship_status)
    sections: dict[str, Any] = {}
    degraded: list[str] = []
    counts: dict[str, int] = {}
    for outcome in outcomes:
        if outcome.key in RELATIONSHIP_GATED_SECTIONS and not allowed:
            continue
        if outcome.ok and outcome.payload is not None:
            sections[outcome.key.value] = outcome.payload.as_dict()
            counts[outcome.key.value] = outcome.payload.count
        else:
            degraded.append(outcome.key.value)
            sections[outcome.key.value] = {
                "key": outcome.key.value,
                "available": False,
                "error_code": outcome.error_code or "SECTION_UNAVAILABLE",
            }
    return DashboardView(
        sections=sections,
        degraded=tuple(sorted(degraded)),
        counts=counts,
        generated_at=now,
    )
