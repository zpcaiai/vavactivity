"""Pure-domain tests for post-event closure rules (B09 / B10 / B11).

These tests deliberately touch no database, no settings and no network, so they
run on any machine including one without PostgreSQL or Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from vav.modules.post_event.domain import (
    AttendanceRecord,
    CandidateEligibility,
    ExclusionKind,
    LetterStatus,
    PostEventRuleError,
    QuestionSpec,
    QuestionType,
    SelectionPolicy,
    SubmittedAnswer,
    TaskStatus,
    VisibilityMode,
    build_candidate_decisions,
    compute_mutual_pairs,
    content_fingerprint,
    ensure_reviewer_is_not_author,
    ensure_selection_editable,
    ensure_survey_open,
    extract_template_variables,
    is_letter_member_visible,
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

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def _uid(value: int) -> UUID:
    return UUID(int=value)


def _record(
    index: int,
    *,
    status: str = "confirmed",
    checked_in: datetime | None = CUTOFF - timedelta(minutes=30),
    attendance: str = "checked_in",
    gender: str | None = "female",
    is_staff: bool = False,
) -> AttendanceRecord:
    return AttendanceRecord(
        user_id=_uid(index),
        registration_id=_uid(1000 + index),
        registration_status=status,
        gender=gender,
        checked_in_at=checked_in,
        attendance_status=attendance,
        is_staff=is_staff,
        display_name=f"member-{index}",
    )


# ---------------------------------------------------------------------------
# MUT-001 candidate freeze
# ---------------------------------------------------------------------------


def test_checked_in_confirmed_attendee_is_eligible() -> None:
    [decision] = build_candidate_decisions([_record(1)], cutoff_at=CUTOFF)
    assert decision.eligibility is CandidateEligibility.ELIGIBLE
    assert decision.exclusion_kind is None


def test_missing_checkin_is_a_no_show() -> None:
    [decision] = build_candidate_decisions(
        [_record(1, checked_in=None, attendance="not_checked_in")], cutoff_at=CUTOFF
    )
    assert decision.eligibility is CandidateEligibility.EXCLUDED
    assert decision.exclusion_kind is ExclusionKind.NO_SHOW


@pytest.mark.parametrize("attendance", ["no_show", "checkin_revoked", "not_checked_in"])
def test_revoked_or_absent_attendance_is_a_no_show_even_with_a_timestamp(attendance: str) -> None:
    """A revoked check-in must not resurrect a candidate through a stale timestamp."""

    [decision] = build_candidate_decisions([_record(1, attendance=attendance)], cutoff_at=CUTOFF)
    assert decision.exclusion_kind is ExclusionKind.NO_SHOW


def test_checkin_after_cutoff_does_not_enter_the_snapshot() -> None:
    late = CUTOFF + timedelta(minutes=1)
    [decision] = build_candidate_decisions([_record(1, checked_in=late)], cutoff_at=CUTOFF)
    assert decision.exclusion_kind is ExclusionKind.NOT_CHECKED_IN


@pytest.mark.parametrize(
    "status", ["waitlisted", "cancelled", "pending_payment", "rejected", "expired", "started"]
)
def test_unconfirmed_registration_never_becomes_a_candidate(status: str) -> None:
    [decision] = build_candidate_decisions([_record(1, status=status)], cutoff_at=CUTOFF)
    assert decision.exclusion_kind is ExclusionKind.CANCELLED


def test_staff_registration_is_excluded_before_any_other_rule() -> None:
    [decision] = build_candidate_decisions(
        [_record(1, is_staff=True, checked_in=None, attendance="not_checked_in")],
        cutoff_at=CUTOFF,
    )
    assert decision.exclusion_kind is ExclusionKind.STAFF


def test_manual_exclusion_is_recorded_with_its_own_kind_and_reason() -> None:
    [decision] = build_candidate_decisions(
        [_record(1)], cutoff_at=CUTOFF, manual_exclusions={_uid(1): "Reported by two attendees."}
    )
    assert decision.exclusion_kind is ExclusionKind.MANUAL
    assert decision.exclusion_reason == "Reported by two attendees."


def test_naive_cutoff_is_rejected() -> None:
    with pytest.raises(PostEventRuleError) as excinfo:
        build_candidate_decisions([_record(1)], cutoff_at=datetime(2026, 8, 12, 10, 0))
    assert excinfo.value.code == "CUTOFF_NAIVE_DATETIME"


def test_manual_exclusion_requires_a_substantive_reason() -> None:
    with pytest.raises(PostEventRuleError) as excinfo:
        require_manual_exclusion_reason("  ok ")
    assert excinfo.value.code == "EXCLUSION_REASON_REQUIRED"
    assert require_manual_exclusion_reason(" duplicate registration ") == "duplicate registration"


def test_frozen_snapshot_cannot_return_to_draft() -> None:
    validate_snapshot_transition("draft", "frozen")
    validate_snapshot_transition("frozen", "superseded")
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_snapshot_transition("frozen", "draft")
    assert excinfo.value.code == "SNAPSHOT_TRANSITION_INVALID"


# ---------------------------------------------------------------------------
# MUT-002 visibility and selection
# ---------------------------------------------------------------------------


def test_opposite_gender_policy_hides_same_gender_and_self() -> None:
    policy = SelectionPolicy()
    assert is_visible_candidate(
        policy,
        chooser_id=_uid(1),
        chooser_gender="male",
        candidate_id=_uid(2),
        candidate_gender="female",
    )
    assert not is_visible_candidate(
        policy,
        chooser_id=_uid(1),
        chooser_gender="male",
        candidate_id=_uid(3),
        candidate_gender="male",
    )
    assert not is_visible_candidate(
        policy,
        chooser_id=_uid(1),
        chooser_gender="male",
        candidate_id=_uid(1),
        candidate_gender="female",
    )


def test_unknown_gender_fails_closed_under_a_gender_scoped_policy() -> None:
    policy = SelectionPolicy()
    assert not is_visible_candidate(
        policy,
        chooser_id=_uid(1),
        chooser_gender=None,
        candidate_id=_uid(2),
        candidate_gender="female",
    )


def test_all_genders_policy_still_respects_restrictions() -> None:
    policy = SelectionPolicy(mode=VisibilityMode.ALL_GENDERS)
    assert not is_visible_candidate(
        policy,
        chooser_id=_uid(1),
        chooser_gender="male",
        candidate_id=_uid(2),
        candidate_gender="male",
        restricted_with=[_uid(2)],
    )


def test_custom_policy_only_admits_explicit_pairs() -> None:
    policy = SelectionPolicy(
        mode=VisibilityMode.CUSTOM, custom_pairs=frozenset({(_uid(1), _uid(2))})
    )
    assert is_visible_candidate(
        policy, chooser_id=_uid(1), chooser_gender="x", candidate_id=_uid(2), candidate_gender="y"
    )
    assert not is_visible_candidate(
        policy, chooser_id=_uid(2), chooser_gender="y", candidate_id=_uid(1), candidate_gender="x"
    )


def test_policy_cannot_raise_the_ceiling_above_three() -> None:
    with pytest.raises(PostEventRuleError):
        SelectionPolicy(max_selections=4)


def test_at_most_three_selections_are_accepted() -> None:
    policy = SelectionPolicy()
    visible = [_uid(i) for i in range(2, 8)]
    assert (
        validate_selection(
            policy,
            chooser_id=_uid(1),
            selected_ids=visible[:3],
            visible_ids=visible,
            no_selection_reason_code=None,
            allowed_reason_codes=["not_ready"],
        )
        == visible[:3]
    )
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_selection(
            policy,
            chooser_id=_uid(1),
            selected_ids=visible[:4],
            visible_ids=visible,
            no_selection_reason_code=None,
            allowed_reason_codes=["not_ready"],
        )
    assert excinfo.value.code == "SELECTION_LIMIT_EXCEEDED"


def test_duplicate_and_self_selection_are_rejected() -> None:
    policy = SelectionPolicy()
    with pytest.raises(PostEventRuleError) as duplicate:
        validate_selection(
            policy,
            chooser_id=_uid(1),
            selected_ids=[_uid(2), _uid(2)],
            visible_ids=[_uid(2)],
            no_selection_reason_code=None,
            allowed_reason_codes=["not_ready"],
        )
    assert duplicate.value.code == "SELECTION_DUPLICATE"
    with pytest.raises(PostEventRuleError) as self_pick:
        validate_selection(
            policy,
            chooser_id=_uid(1),
            selected_ids=[_uid(1)],
            visible_ids=[_uid(1), _uid(2)],
            no_selection_reason_code=None,
            allowed_reason_codes=["not_ready"],
        )
    assert self_pick.value.code == "SELECTION_SELF_NOT_ALLOWED"


def test_selecting_someone_outside_the_frozen_pool_is_rejected() -> None:
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_selection(
            SelectionPolicy(),
            chooser_id=_uid(1),
            selected_ids=[_uid(9)],
            visible_ids=[_uid(2), _uid(3)],
            no_selection_reason_code=None,
            allowed_reason_codes=["not_ready"],
        )
    assert excinfo.value.code == "SELECTION_CANDIDATE_NOT_ELIGIBLE"


def test_empty_selection_requires_a_configured_reason() -> None:
    policy = SelectionPolicy()
    with pytest.raises(PostEventRuleError) as missing:
        validate_selection(
            policy,
            chooser_id=_uid(1),
            selected_ids=[],
            visible_ids=[_uid(2)],
            no_selection_reason_code=None,
            allowed_reason_codes=["not_ready", "no_connection"],
        )
    assert missing.value.code == "PASS_REASON_REQUIRED"

    with pytest.raises(PostEventRuleError) as unknown:
        validate_selection(
            policy,
            chooser_id=_uid(1),
            selected_ids=[],
            visible_ids=[_uid(2)],
            no_selection_reason_code="invented_reason",
            allowed_reason_codes=["not_ready"],
        )
    assert unknown.value.code == "PASS_REASON_UNKNOWN"

    assert (
        validate_selection(
            policy,
            chooser_id=_uid(1),
            selected_ids=[],
            visible_ids=[_uid(2)],
            no_selection_reason_code="not_ready",
            allowed_reason_codes=["not_ready"],
        )
        == []
    )


def test_reason_note_requirement_is_enforced_when_configured() -> None:
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_selection(
            SelectionPolicy(),
            chooser_id=_uid(1),
            selected_ids=[],
            visible_ids=[_uid(2)],
            no_selection_reason_code="other",
            allowed_reason_codes=["other"],
            reason_note="   ",
            reason_requires_note=True,
        )
    assert excinfo.value.code == "PASS_REASON_NOTE_REQUIRED"


def test_reason_cannot_accompany_a_non_empty_selection() -> None:
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_selection(
            SelectionPolicy(),
            chooser_id=_uid(1),
            selected_ids=[_uid(2)],
            visible_ids=[_uid(2)],
            no_selection_reason_code="not_ready",
            allowed_reason_codes=["not_ready"],
        )
    assert excinfo.value.code == "PASS_REASON_NOT_APPLICABLE"


def test_edit_window_closes_after_the_configured_hours() -> None:
    policy = SelectionPolicy(edit_window_hours=24)
    submitted = NOW
    ensure_selection_editable(policy, submitted_at=submitted, now=submitted + timedelta(hours=23))
    with pytest.raises(PostEventRuleError) as excinfo:
        ensure_selection_editable(
            policy, submitted_at=submitted, now=submitted + timedelta(hours=25)
        )
    assert excinfo.value.code == "SELECTION_EDIT_WINDOW_CLOSED"


def test_mutual_pairs_are_deterministic_and_deduplicated() -> None:
    submissions = {
        _uid(1): [_uid(2), _uid(3)],
        _uid(2): [_uid(1)],
        _uid(3): [_uid(4)],
        _uid(4): [],
    }
    assert compute_mutual_pairs(submissions) == [(_uid(1), _uid(2))]
    reordered = {key: submissions[key] for key in reversed(list(submissions))}
    assert compute_mutual_pairs(reordered) == compute_mutual_pairs(submissions)


# ---------------------------------------------------------------------------
# SUR-001 / SUR-002 survey
# ---------------------------------------------------------------------------


def _rating_question(**overrides: object) -> QuestionSpec:
    defaults: dict[str, object] = {
        "question_id": uuid4(),
        "question_code": "overall",
        "question_type": QuestionType.RATING,
        "scale_min": 1,
        "scale_max": 5,
    }
    defaults.update(overrides)
    return QuestionSpec(**defaults)  # type: ignore[arg-type]


def test_rating_must_sit_inside_the_configured_scale() -> None:
    questions = [_rating_question()]
    validate_answers(questions, [SubmittedAnswer("overall", rating_value=5)])
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_answers(questions, [SubmittedAnswer("overall", rating_value=6)])
    assert excinfo.value.code == "SURVEY_RATING_OUT_OF_RANGE"


def test_missing_required_answer_blocks_submit_but_not_a_draft() -> None:
    questions = [_rating_question()]
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_answers(questions, [])
    assert excinfo.value.code == "SURVEY_ANSWER_MISSING"
    validate_answers(questions, [], partial=True)


def test_unknown_question_is_rejected_so_versions_stay_frozen() -> None:
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_answers([_rating_question()], [SubmittedAnswer("from_another_version", 3)])
    assert excinfo.value.code == "SURVEY_QUESTION_UNKNOWN"


def test_segment_rating_requires_an_eligible_subject() -> None:
    question = _rating_question(
        question_code="chemistry", question_type=QuestionType.SEGMENT_RATING, per_subject=True
    )
    subjects = [_uid(2), _uid(3)]
    validate_answers(
        [question],
        [
            SubmittedAnswer("chemistry", rating_value=4, subject_user_id=_uid(2)),
            SubmittedAnswer("chemistry", rating_value=2, subject_user_id=_uid(3)),
        ],
        subject_user_ids=subjects,
    )
    with pytest.raises(PostEventRuleError) as missing_subject:
        validate_answers(
            [question], [SubmittedAnswer("chemistry", rating_value=4)], subject_user_ids=subjects
        )
    assert missing_subject.value.code == "SURVEY_SUBJECT_REQUIRED"
    with pytest.raises(PostEventRuleError) as foreign_subject:
        validate_answers(
            [question],
            [SubmittedAnswer("chemistry", rating_value=4, subject_user_id=_uid(99))],
            subject_user_ids=subjects,
        )
    assert foreign_subject.value.code == "SURVEY_SUBJECT_NOT_ELIGIBLE"


def test_choice_question_validates_options_and_counts() -> None:
    question = QuestionSpec(
        question_id=uuid4(),
        question_code="highlights",
        question_type=QuestionType.MULTI_CHOICE,
        options=("venue", "pacing", "host"),
        min_selections=1,
        max_selections=2,
    )
    validate_answers([question], [SubmittedAnswer("highlights", choice_values=("venue", "host"))])
    with pytest.raises(PostEventRuleError) as too_many:
        validate_answers(
            [question], [SubmittedAnswer("highlights", choice_values=("venue", "host", "pacing"))]
        )
    assert too_many.value.code == "SURVEY_CHOICE_COUNT_INVALID"
    with pytest.raises(PostEventRuleError) as unknown:
        validate_answers([question], [SubmittedAnswer("highlights", choice_values=("bar",))])
    assert unknown.value.code == "SURVEY_CHOICE_UNKNOWN"


def test_open_text_length_is_capped() -> None:
    question = QuestionSpec(
        question_id=uuid4(),
        question_code="notes",
        question_type=QuestionType.OPEN_TEXT,
        max_length=10,
    )
    validate_answers([question], [SubmittedAnswer("notes", text_value="short")])
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_answers([question], [SubmittedAnswer("notes", text_value="x" * 11)])
    assert excinfo.value.code == "SURVEY_TEXT_TOO_LONG"


def test_duplicate_answer_for_the_same_question_is_rejected() -> None:
    question = _rating_question()
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_answers(
            [question],
            [
                SubmittedAnswer("overall", rating_value=3),
                SubmittedAnswer("overall", rating_value=4),
            ],
        )
    assert excinfo.value.code == "SURVEY_ANSWER_DUPLICATE"


def test_deadline_is_compared_in_utc_regardless_of_display_timezone() -> None:
    deadline = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)
    ensure_survey_open(opens_at=None, deadline_at=deadline, now=deadline - timedelta(minutes=1))
    with pytest.raises(PostEventRuleError) as late:
        ensure_survey_open(opens_at=None, deadline_at=deadline, now=deadline + timedelta(minutes=1))
    assert late.value.code == "SURVEY_DEADLINE_PASSED"
    # An audited administrative override is the only way past the deadline.
    ensure_survey_open(
        opens_at=None, deadline_at=deadline, now=deadline + timedelta(days=3), override=True
    )


def test_survey_not_open_before_its_start() -> None:
    opens = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
    with pytest.raises(PostEventRuleError) as excinfo:
        ensure_survey_open(
            opens_at=opens, deadline_at=opens + timedelta(days=3), now=opens - timedelta(hours=1)
        )
    assert excinfo.value.code == "SURVEY_NOT_OPEN"


def test_only_checked_in_confirmed_members_receive_a_task() -> None:
    assert is_survey_task_eligible(registration_status="confirmed", checked_in_at=NOW)
    assert not is_survey_task_eligible(registration_status="confirmed", checked_in_at=None)
    assert not is_survey_task_eligible(registration_status="waitlisted", checked_in_at=NOW)
    assert not is_survey_task_eligible(
        registration_status="confirmed", checked_in_at=NOW, is_staff=True
    )
    assert not is_survey_task_eligible(
        registration_status="confirmed", checked_in_at=NOW, attendance_status="checkin_revoked"
    )


def test_completed_task_plans_no_further_reminders() -> None:
    deadline = NOW + timedelta(days=3)
    assert (
        plan_reminders(
            deadline_at=deadline, offsets_hours=[48, 24], now=NOW, task_status=TaskStatus.COMPLETED
        )
        == []
    )


def test_reminder_slots_are_deduplicated_ordered_and_never_in_the_past() -> None:
    deadline = NOW + timedelta(hours=30)
    slots = plan_reminders(
        deadline_at=deadline,
        offsets_hours=[48, 24, 24, 6, 0, -3],
        now=NOW,
        task_status=TaskStatus.PENDING,
    )
    assert [slot.reminder_code for slot in slots] == ["h-24", "h-6"]
    assert all(slot.scheduled_for > NOW for slot in slots)


def test_reminder_dedupe_key_is_stable() -> None:
    task = _uid(7)
    assert reminder_dedupe_key(task, "h-24") == reminder_dedupe_key(task, "h-24")
    assert reminder_dedupe_key(task, "h-24") != reminder_dedupe_key(task, "h-6")


# ---------------------------------------------------------------------------
# RES-001 result letters
# ---------------------------------------------------------------------------


def test_letter_cannot_skip_review_on_the_way_to_publication() -> None:
    validate_letter_transition("draft", "pending_review")
    validate_letter_transition("pending_review", "approved")
    validate_letter_transition("approved", "published")
    with pytest.raises(PostEventRuleError) as excinfo:
        validate_letter_transition("draft", "published")
    assert excinfo.value.code == "LETTER_TRANSITION_INVALID"


def test_rejected_letter_returns_to_draft_and_is_never_published_directly() -> None:
    validate_letter_transition("rejected", "draft")
    with pytest.raises(PostEventRuleError):
        validate_letter_transition("rejected", "published")


def test_published_letter_can_only_be_revoked() -> None:
    validate_letter_transition("published", "revoked")
    with pytest.raises(PostEventRuleError):
        validate_letter_transition("published", "draft")
    with pytest.raises(PostEventRuleError):
        validate_letter_transition("revoked", "published")


def test_only_published_letters_are_member_visible() -> None:
    assert is_letter_member_visible(LetterStatus.PUBLISHED)
    for status in ("draft", "pending_review", "approved", "rejected", "revoked", "nonsense"):
        assert not is_letter_member_visible(status)


def test_author_cannot_review_their_own_letter() -> None:
    author = _uid(1)
    ensure_reviewer_is_not_author(reviewer_id=_uid(2), author_id=author)
    with pytest.raises(PostEventRuleError) as excinfo:
        ensure_reviewer_is_not_author(reviewer_id=author, author_id=author)
    assert excinfo.value.code == "LETTER_REVIEW_SELF_APPROVAL"


def test_template_variables_are_extracted_in_order_without_duplicates() -> None:
    template = "Hi {{ name }}, you met {{count}} people. Bye {{ name }}."
    assert extract_template_variables(template) == ["name", "count"]


def test_rendering_fails_loudly_on_a_missing_variable() -> None:
    with pytest.raises(PostEventRuleError) as excinfo:
        render_template("Hi {{ name }}", {})
    assert excinfo.value.code == "LETTER_TEMPLATE_VARIABLE_MISSING"
    assert render_template("Hi {{ name }}!", {"name": "Wei"}) == "Hi Wei!"


def test_unclosed_template_token_is_rejected() -> None:
    with pytest.raises(PostEventRuleError) as excinfo:
        extract_template_variables("Hi {{ name")
    assert excinfo.value.code == "LETTER_TEMPLATE_UNCLOSED"


def test_fingerprint_detects_any_change_to_a_published_letter() -> None:
    base = content_fingerprint("Result", "You have a match.")
    assert base == content_fingerprint("Result", "You have a match.")
    assert base != content_fingerprint("Result", "You have a match!")
    assert base != content_fingerprint("Results", "You have a match.")
    # Field boundaries cannot be forged by shifting text between subject/body.
    assert content_fingerprint("ab", "c") != content_fingerprint("a", "bc")
