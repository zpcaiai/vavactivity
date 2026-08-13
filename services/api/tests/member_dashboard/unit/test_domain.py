"""Pure-domain tests for member dashboard aggregation (B18 / DASH-001).

No database, no settings, no network: every rule under test takes its inputs as
arguments, including ``now``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from vav.modules.member_dashboard.domain import (
    ACTIVE_REGISTRATION_STATUSES,
    CONFIRMED_REGISTRATION_STATUSES,
    MATCHMAKING_ELIGIBLE_STATUSES,
    MEMBER_VISIBLE_LETTER_STATUSES,
    DashboardRuleError,
    EntitlementRow,
    NotificationRow,
    RegistrationBucket,
    RegistrationRow,
    ResultLetterRow,
    SectionKey,
    SectionOutcome,
    SelectionRow,
    SurveyTaskRow,
    TaskPriority,
    TaskState,
    TaskType,
    assemble_dashboard,
    assert_rows_belong_to,
    build_deep_link,
    build_matchmaking_section,
    build_notification_section,
    build_registration_section,
    build_result_letter_section,
    build_selection_section,
    build_survey_section,
    classify_registration,
    collect_section,
    due_priority,
    entitlement_balance,
    is_letter_unread,
    is_matchmaking_allowed,
    is_selection_pending,
    paginate,
    resolve_survey_task_state,
    sort_tasks,
    task_key_for,
)

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _uid(value: int) -> UUID:
    return UUID(int=value)


MEMBER_A = _uid(1)
MEMBER_B = _uid(2)
ACTIVITY = _uid(100)


def _survey(
    index: int, *, user_id: UUID = MEMBER_A, status: str = "pending", due_in_hours: int = 48
) -> SurveyTaskRow:
    return SurveyTaskRow(
        user_id=user_id,
        task_id=_uid(1000 + index),
        assignment_id=_uid(2000 + index),
        activity_id=ACTIVITY,
        status=status,
        due_at=NOW + timedelta(hours=due_in_hours),
    )


def _letter(
    index: int, *, user_id: UUID = MEMBER_A, status: str = "published", read: bool = False
) -> ResultLetterRow:
    return ResultLetterRow(
        user_id=user_id,
        letter_id=_uid(3000 + index),
        activity_id=ACTIVITY,
        status=status,
        published_at=NOW - timedelta(days=1),
        read_at=NOW - timedelta(hours=1) if read else None,
    )


def _registration(
    index: int,
    *,
    user_id: UUID = MEMBER_A,
    status: str = "confirmed",
    starts_in_hours: int = 72,
    attendance: str = "not_checked_in",
) -> RegistrationRow:
    starts = NOW + timedelta(hours=starts_in_hours)
    return RegistrationRow(
        user_id=user_id,
        registration_id=_uid(4000 + index),
        activity_id=_uid(100 + index),
        registration_status=status,
        attendance_status=attendance,
        starts_at=starts,
        ends_at=starts + timedelta(hours=3),
    )


def _selection(
    index: int,
    *,
    user_id: UUID = MEMBER_A,
    submission_status: str | None = None,
    enabled: bool = True,
    closes_in_hours: int = 24,
) -> SelectionRow:
    return SelectionRow(
        user_id=user_id,
        activity_id=_uid(5000 + index),
        submission_status=submission_status,
        choice_enabled=enabled,
        choice_opens_at=NOW - timedelta(hours=1),
        choice_closes_at=NOW + timedelta(hours=closes_in_hours),
    )


# ---------------------------------------------------------------------------
# Mirrored predicates: the dashboard must not invent its own filters
# ---------------------------------------------------------------------------


def test_confirmed_predicate_mirrors_the_post_event_module() -> None:
    """Only ``confirmed`` counts as confirmed, exactly as post_event says."""

    assert frozenset({"confirmed"}) == CONFIRMED_REGISTRATION_STATUSES
    assert "waitlisted" not in CONFIRMED_REGISTRATION_STATUSES
    assert "pending_payment" not in CONFIRMED_REGISTRATION_STATUSES


def test_letter_visibility_predicate_mirrors_the_post_event_module() -> None:
    assert frozenset({"published"}) == MEMBER_VISIBLE_LETTER_STATUSES


def test_matchmaking_eligibility_mirrors_match_001() -> None:
    assert frozenset({"single", "separated", "widowed"}) == MATCHMAKING_ELIGIBLE_STATUSES


@pytest.mark.parametrize("status", ["single", "separated", "widowed"])
def test_eligible_relationship_statuses_open_matchmaking(status: str) -> None:
    assert is_matchmaking_allowed(status) is True


@pytest.mark.parametrize(
    "status", [None, "undisclosed", "dating", "engaged", "married", "nonsense"]
)
def test_every_other_relationship_status_fails_closed(status: str | None) -> None:
    assert is_matchmaking_allowed(status) is False


def test_active_registration_statuses_exclude_terminal_ones() -> None:
    for status in ("cancelled", "rejected", "expired"):
        assert status not in ACTIVE_REGISTRATION_STATUSES


# ---------------------------------------------------------------------------
# No cross-user leakage
# ---------------------------------------------------------------------------


def test_ownership_guard_rejects_another_members_row() -> None:
    with pytest.raises(DashboardRuleError) as excinfo:
        assert_rows_belong_to(MEMBER_A, [_survey(1, user_id=MEMBER_B)])
    assert excinfo.value.code == "DASHBOARD_ROW_OWNER_MISMATCH"


@pytest.mark.parametrize(
    ("builder", "rows"),
    [
        (build_survey_section, [_survey(1, user_id=MEMBER_B)]),
        (build_result_letter_section, [_letter(1, user_id=MEMBER_B)]),
        (build_registration_section, [_registration(1, user_id=MEMBER_B)]),
        (build_selection_section, [_selection(1, user_id=MEMBER_B)]),
    ],
)
def test_no_section_builder_can_emit_another_members_row(builder, rows) -> None:
    """User A's dashboard can never render user B's row - it raises instead."""

    with pytest.raises(DashboardRuleError) as excinfo:
        builder(rows, user_id=MEMBER_A, now=NOW)
    assert excinfo.value.code == "DASHBOARD_ROW_OWNER_MISMATCH"


def test_a_leaking_section_degrades_instead_of_leaking() -> None:
    """The guard and the degradation path compose: a leak becomes a missing panel."""

    outcome = collect_section(
        SectionKey.SURVEY_TASKS,
        lambda: build_survey_section([_survey(1, user_id=MEMBER_B)], user_id=MEMBER_A, now=NOW),
    )
    assert outcome.ok is False
    assert outcome.error_code == "DASHBOARD_ROW_OWNER_MISMATCH"
    assert outcome.payload is None


def test_notification_builder_also_guards_ownership() -> None:
    rows = [
        NotificationRow(
            user_id=MEMBER_B, notification_id=_uid(9001), category="system", created_at=NOW
        )
    ]
    with pytest.raises(DashboardRuleError):
        build_notification_section(rows, user_id=MEMBER_A, now=NOW)


def test_matchmaking_builder_guards_ownership_too() -> None:
    row = EntitlementRow(user_id=MEMBER_B, granted=3, consumed=0)
    with pytest.raises(DashboardRuleError):
        build_matchmaking_section(row, user_id=MEMBER_A, relationship_status="single", now=NOW)


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def _boom() -> None:
    raise RuntimeError("survey module is down")


def test_a_failing_section_is_captured_not_raised() -> None:
    outcome = collect_section(SectionKey.SURVEY_TASKS, _boom)
    assert outcome.ok is False
    assert outcome.error_code == "SECTION_UNAVAILABLE"
    assert "RuntimeError" in (outcome.error_message or "")


def test_dashboard_returns_working_sections_and_names_the_broken_one() -> None:
    healthy = collect_section(
        SectionKey.RESULT_LETTERS,
        lambda: build_result_letter_section([_letter(1)], user_id=MEMBER_A, now=NOW),
    )
    broken = collect_section(SectionKey.SURVEY_TASKS, _boom)
    view = assemble_dashboard([healthy, broken], now=NOW, relationship_status="dating")
    payload = view.as_dict()
    assert payload["degraded"] == ["survey_tasks"]
    assert payload["sections"]["result_letters"]["count"] == 1
    assert payload["sections"]["survey_tasks"]["available"] is False


def test_a_degraded_section_contributes_no_count() -> None:
    """A missing number is honest; a zero would read as "nothing to do"."""

    view = assemble_dashboard(
        [collect_section(SectionKey.SURVEY_TASKS, _boom)], now=NOW, relationship_status="single"
    )
    assert "survey_tasks" not in view.counts
    assert view.as_dict()["total_open_tasks"] == 0


def test_every_section_failing_still_produces_a_dashboard() -> None:
    outcomes = [collect_section(key, _boom) for key in SectionKey]
    view = assemble_dashboard(outcomes, now=NOW, relationship_status="single")
    assert len(view.degraded) == len(list(SectionKey))
    assert view.counts == {}


def test_base_exceptions_are_not_swallowed() -> None:
    """A cancellation is not a degraded section."""

    def cancelled() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        collect_section(SectionKey.SURVEY_TASKS, cancelled)


# ---------------------------------------------------------------------------
# MATCH-001 relationship gate
# ---------------------------------------------------------------------------


def test_an_ineligible_member_sees_no_matchmaking_section_at_all() -> None:
    """Not empty, not degraded, not locked: absent."""

    matchmaking = collect_section(
        SectionKey.MATCHMAKING,
        lambda: build_matchmaking_section(
            EntitlementRow(user_id=MEMBER_A, granted=3, consumed=0),
            user_id=MEMBER_A,
            relationship_status="single",
            now=NOW,
        ),
    )
    view = assemble_dashboard([matchmaking], now=NOW, relationship_status="married")
    payload = view.as_dict()
    assert "matchmaking" not in payload["sections"]
    assert "matchmaking" not in payload["degraded"]
    assert "matchmaking" not in payload["counts"]


def test_a_broken_matchmaking_section_is_still_hidden_from_an_ineligible_member() -> None:
    view = assemble_dashboard(
        [collect_section(SectionKey.MATCHMAKING, _boom)], now=NOW, relationship_status="undisclosed"
    )
    assert view.degraded == ()
    assert view.sections == {}


def test_an_eligible_member_sees_the_matchmaking_section() -> None:
    matchmaking = collect_section(
        SectionKey.MATCHMAKING,
        lambda: build_matchmaking_section(
            EntitlementRow(user_id=MEMBER_A, granted=3, consumed=1),
            user_id=MEMBER_A,
            relationship_status="single",
            now=NOW,
        ),
    )
    view = assemble_dashboard([matchmaking], now=NOW, relationship_status="single")
    assert view.sections["matchmaking"]["balance"] == 2
    assert view.counts["matchmaking"] == 2


def test_the_builder_refuses_an_ineligible_member_even_when_called_directly() -> None:
    with pytest.raises(DashboardRuleError) as excinfo:
        build_matchmaking_section(None, user_id=MEMBER_A, relationship_status="married", now=NOW)
    assert excinfo.value.code == "MATCHMAKING_NOT_AVAILABLE"


def test_an_expired_entitlement_reports_a_zero_balance() -> None:
    row = EntitlementRow(
        user_id=MEMBER_A, granted=3, consumed=0, expires_at=NOW - timedelta(seconds=1)
    )
    assert entitlement_balance(row, now=NOW) == 0


# ---------------------------------------------------------------------------
# Counts derived from the source predicates
# ---------------------------------------------------------------------------


def test_only_open_survey_tasks_are_counted() -> None:
    rows = [
        _survey(1, status="pending"),
        _survey(2, status="in_progress"),
        _survey(3, status="completed"),
        _survey(4, status="waived"),
        _survey(5, status="pending", due_in_hours=-1),  # deadline already passed
    ]
    section = build_survey_section(rows, user_id=MEMBER_A, now=NOW)
    assert section.count == 2


def test_a_task_past_its_deadline_is_expired_before_the_sweeper_runs() -> None:
    state = resolve_survey_task_state(status="pending", due_at=NOW - timedelta(minutes=1), now=NOW)
    assert state is TaskState.EXPIRED


def test_a_stored_completed_status_wins_over_the_deadline() -> None:
    assert (
        resolve_survey_task_state(status="completed", due_at=NOW - timedelta(days=9), now=NOW)
        is TaskState.COMPLETED
    )


def test_unknown_survey_status_is_refused_rather_than_guessed() -> None:
    with pytest.raises(DashboardRuleError) as excinfo:
        resolve_survey_task_state(status="somethings_wrong", due_at=NOW, now=NOW)
    assert excinfo.value.code == "SURVEY_TASK_STATUS_UNKNOWN"


def test_only_published_and_unread_letters_are_counted() -> None:
    rows = [
        _letter(1),
        _letter(2, read=True),
        _letter(3, status="approved"),
        _letter(4, status="draft"),
        _letter(5, status="revoked"),
    ]
    section = build_result_letter_section(rows, user_id=MEMBER_A, now=NOW)
    assert section.count == 1
    assert is_letter_unread(_letter(3, status="approved")) is False
    assert is_letter_unread(_letter(6)) is True


def test_registration_buckets_follow_the_clock_not_the_status() -> None:
    assert (
        classify_registration(_registration(1, starts_in_hours=5), now=NOW)
        is RegistrationBucket.UPCOMING
    )
    assert (
        classify_registration(_registration(2, starts_in_hours=-1), now=NOW)
        is RegistrationBucket.IN_PROGRESS
    )
    assert (
        classify_registration(_registration(3, starts_in_hours=-100), now=NOW)
        is RegistrationBucket.PAST
    )
    assert (
        classify_registration(_registration(4, status="cancelled"), now=NOW)
        is RegistrationBucket.INACTIVE
    )


def test_registration_section_separates_upcoming_from_past_and_counts_confirmed() -> None:
    rows = [
        _registration(1, status="confirmed", starts_in_hours=48),
        _registration(2, status="waitlisted", starts_in_hours=48),
        _registration(3, status="cancelled", starts_in_hours=48),
        _registration(4, status="confirmed", starts_in_hours=-200, attendance="checked_in"),
    ]
    section = build_registration_section(rows, user_id=MEMBER_A, now=NOW)
    assert section.count == 2
    assert section.extra["confirmed_upcoming_count"] == 1
    assert section.extra["past_count"] == 1
    assert section.extra["past"][0]["attended"] is True


def test_a_no_show_past_registration_is_not_reported_as_attended() -> None:
    rows = [_registration(1, starts_in_hours=-200, attendance="no_show")]
    section = build_registration_section(rows, user_id=MEMBER_A, now=NOW)
    assert section.extra["past"][0]["attended"] is False


def test_selection_is_pending_until_it_is_submitted() -> None:
    assert is_selection_pending(_selection(1), now=NOW) is True
    assert is_selection_pending(_selection(2, submission_status="draft"), now=NOW) is True
    assert is_selection_pending(_selection(3, submission_status="submitted"), now=NOW) is False
    assert is_selection_pending(_selection(4, enabled=False), now=NOW) is False
    assert is_selection_pending(_selection(5, closes_in_hours=-1), now=NOW) is False


def test_selection_section_counts_only_pending_windows() -> None:
    rows = [
        _selection(1),
        _selection(2, submission_status="submitted"),
        _selection(3, enabled=False),
    ]
    assert build_selection_section(rows, user_id=MEMBER_A, now=NOW).count == 1


def test_unread_notifications_are_the_notification_count() -> None:
    rows = [
        NotificationRow(user_id=MEMBER_A, notification_id=_uid(1), category="a", created_at=NOW),
        NotificationRow(
            user_id=MEMBER_A,
            notification_id=_uid(2),
            category="b",
            created_at=NOW,
            read_at=NOW,
        ),
    ]
    assert build_notification_section(rows, user_id=MEMBER_A, now=NOW).count == 1


# ---------------------------------------------------------------------------
# Task types, deep links, priority, pagination
# ---------------------------------------------------------------------------


def test_task_types_are_stable_strings() -> None:
    assert TaskType.SURVEY_PENDING.value == "survey_pending"
    assert TaskType.RESULT_LETTER_UNREAD.value == "result_letter_unread"
    assert task_key_for(TaskType.SURVEY_PENDING, _uid(7)) == f"survey_pending:{_uid(7)}"


def test_deep_links_are_site_relative_and_fully_substituted() -> None:
    link = build_deep_link(TaskType.SURVEY_PENDING, {"assignment_id": _uid(7)})
    assert link == f"/account/surveys/{_uid(7)}"
    assert link.startswith("/")


def test_a_missing_deep_link_parameter_is_an_error_not_a_blank_segment() -> None:
    with pytest.raises(DashboardRuleError) as excinfo:
        build_deep_link(TaskType.RESULT_LETTER_UNREAD, {})
    assert excinfo.value.code == "DEEP_LINK_PARAMETER_MISSING"


def test_a_deep_link_parameter_cannot_inject_path_segments() -> None:
    with pytest.raises(DashboardRuleError) as excinfo:
        build_deep_link(TaskType.RESULT_LETTER_UNREAD, {"letter_id": "../../admin"})
    assert excinfo.value.code == "DEEP_LINK_PARAMETER_INVALID"


def test_an_absolute_deep_link_template_is_refused() -> None:
    with pytest.raises(DashboardRuleError) as excinfo:
        build_deep_link(
            TaskType.SURVEY_PENDING,
            {"assignment_id": _uid(7)},
            templates={TaskType.SURVEY_PENDING: "//evil.example/steal"},
        )
    assert excinfo.value.code == "DEEP_LINK_NOT_RELATIVE"


def test_priority_tightens_as_the_deadline_approaches() -> None:
    assert due_priority(NOW + timedelta(hours=1), NOW) is TaskPriority.URGENT
    assert due_priority(NOW + timedelta(hours=12), NOW) is TaskPriority.HIGH
    assert due_priority(NOW + timedelta(hours=48), NOW) is TaskPriority.NORMAL
    assert due_priority(NOW + timedelta(days=30), NOW) is TaskPriority.LOW
    assert due_priority(None, NOW, base=TaskPriority.HIGH) is TaskPriority.HIGH


def test_an_overdue_item_is_urgent_rather_than_hidden() -> None:
    assert due_priority(NOW - timedelta(hours=1), NOW) is TaskPriority.URGENT


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(DashboardRuleError) as excinfo:
        due_priority(datetime(2026, 8, 12, 12, 0), NOW)
    assert excinfo.value.code == "DASHBOARD_NAIVE_DATETIME"


def test_tasks_sort_by_urgency_then_deadline_then_key() -> None:
    rows = [
        _survey(1, due_in_hours=100),
        _survey(2, due_in_hours=2),
        _survey(3, due_in_hours=20),
    ]
    section = build_survey_section(rows, user_id=MEMBER_A, now=NOW)
    priorities = [task.priority for task in section.page.items]
    assert priorities == [TaskPriority.URGENT, TaskPriority.HIGH, TaskPriority.LOW]


def test_sorting_is_stable_for_equally_urgent_tasks() -> None:
    rows = [_survey(index, due_in_hours=100) for index in (3, 1, 2)]
    first = build_survey_section(rows, user_id=MEMBER_A, now=NOW).page.items
    second = build_survey_section(list(reversed(rows)), user_id=MEMBER_A, now=NOW).page.items
    assert [task.task_key for task in first] == [task.task_key for task in second]
    assert sort_tasks(first) == list(first)


def test_pagination_keeps_the_badge_count_whole() -> None:
    rows = [_survey(index) for index in range(10)]
    section = build_survey_section(rows, user_id=MEMBER_A, now=NOW, limit=3, offset=3)
    assert section.count == 10
    assert len(section.page.items) == 3
    assert section.page.has_more is True
    assert section.page.offset == 3


def test_the_last_page_reports_no_more() -> None:
    page = paginate(list(range(5)), limit=3, offset=3)
    assert page.items == (3, 4)
    assert page.has_more is False


@pytest.mark.parametrize(
    ("limit", "offset", "code"),
    [
        (0, 0, "PAGE_LIMIT_INVALID"),
        (10_000, 0, "PAGE_LIMIT_TOO_LARGE"),
        (10, -1, "PAGE_OFFSET_INVALID"),
    ],
)
def test_pagination_arguments_are_validated(limit: int, offset: int, code: str) -> None:
    with pytest.raises(DashboardRuleError) as excinfo:
        paginate([1, 2, 3], limit=limit, offset=offset)
    assert excinfo.value.code == code


def test_dismissed_tasks_disappear_from_the_section() -> None:
    rows = [_survey(1), _survey(2)]
    dismissed = {task_key_for(TaskType.SURVEY_PENDING, _uid(1001))}
    section = build_survey_section(rows, user_id=MEMBER_A, now=NOW, dismissed_keys=dismissed)
    assert section.count == 1
    assert section.page.items[0].task_key == task_key_for(TaskType.SURVEY_PENDING, _uid(1002))


def test_task_serialization_carries_the_contract_fields() -> None:
    section = build_survey_section([_survey(1)], user_id=MEMBER_A, now=NOW)
    payload = section.page.items[0].as_dict()
    for key in ("task_type", "task_key", "section", "deep_link", "priority", "due_at"):
        assert key in payload
    assert payload["section"] == SectionKey.SURVEY_TASKS.value


def test_assembled_view_reports_generated_at_and_total() -> None:
    outcomes = [
        SectionOutcome(
            key=SectionKey.RESULT_LETTERS,
            ok=True,
            payload=build_result_letter_section([_letter(1)], user_id=MEMBER_A, now=NOW),
        )
    ]
    payload = assemble_dashboard(outcomes, now=NOW, relationship_status="single").as_dict()
    assert payload["generated_at"] == NOW.isoformat()
    assert payload["total_open_tasks"] == 1
