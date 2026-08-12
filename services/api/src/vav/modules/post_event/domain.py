"""Pure post-event closure rules (B09 / B10 / B11).

This module deliberately contains no database, network or settings access so
that every rule below is unit-testable without a real stack. The service layer
owns transactions; this layer owns decisions.

Requirement coverage:

* MUT-001 candidate freeze, no-show exclusion, audited manual exclusion
* MUT-002 gender visibility policy, 0..3 unique selections, pass reason
* SUR-001 survey version freeze, answer validation, deadline/timezone rules
* SUR-002 task eligibility and idempotent reminder planning
* RES-001 result-letter review/publication state machine
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

# ---------------------------------------------------------------------------
# Shared errors
# ---------------------------------------------------------------------------


class PostEventRuleError(Exception):
    """Raised when a caller violates a post-event closure rule.

    ``code`` is a stable machine identifier surfaced to clients; ``message`` is
    an operator-facing English sentence. Member-facing copy is localized in the
    frontend from ``code``, never from ``message``.
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


# ---------------------------------------------------------------------------
# B09 - candidate freeze
# ---------------------------------------------------------------------------


class SnapshotStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"
    SUPERSEDED = "superseded"


class CandidateEligibility(StrEnum):
    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"


class ExclusionKind(StrEnum):
    NOT_CHECKED_IN = "not_checked_in"
    NO_SHOW = "no_show"
    CANCELLED = "cancelled"
    MANUAL = "manual"
    RESTRICTED = "restricted"
    STAFF = "staff"


#: The only registration status that makes someone a *potential* candidate.
#: Mirrors ``vav.modules.activities.domain.RegistrationStatus.CONFIRMED``;
#: everything else (waitlisted, pending payment, rejected, cancelled, expired)
#: never reaches the snapshot.
CONFIRMED_REGISTRATION_STATUSES: frozenset[str] = frozenset({"confirmed"})

#: Attendance states that mean the person did not actually attend. Mirrors
#: ``vav.modules.activities.domain.AttendanceStatus``.
ABSENT_ATTENDANCE_STATUSES: frozenset[str] = frozenset(
    {"not_checked_in", "no_show", "checkin_revoked"}
)

_SNAPSHOT_TRANSITIONS: dict[SnapshotStatus, frozenset[SnapshotStatus]] = {
    SnapshotStatus.DRAFT: frozenset({SnapshotStatus.FROZEN, SnapshotStatus.SUPERSEDED}),
    SnapshotStatus.FROZEN: frozenset({SnapshotStatus.SUPERSEDED}),
    SnapshotStatus.SUPERSEDED: frozenset(),
}


def validate_snapshot_transition(current: str, target: str) -> None:
    """Guard the snapshot lifecycle.

    A frozen snapshot can only be superseded by a *new* version; it is never
    edited in place. That is what makes the candidate list deterministic and
    replayable after the fact (MUT-001).
    """

    try:
        current_status = SnapshotStatus(current)
        target_status = SnapshotStatus(target)
    except ValueError as exc:  # pragma: no cover - defensive
        raise PostEventRuleError(
            "SNAPSHOT_STATUS_UNKNOWN", f"Unknown snapshot status: {exc}"
        ) from exc
    if target_status not in _SNAPSHOT_TRANSITIONS[current_status]:
        raise PostEventRuleError(
            "SNAPSHOT_TRANSITION_INVALID",
            f"Cannot move snapshot from {current_status} to {target_status}.",
            details={"current": current_status.value, "target": target_status.value},
        )


@dataclass(frozen=True)
class AttendanceRecord:
    """One registration considered for the frozen candidate list."""

    user_id: UUID
    registration_id: UUID
    registration_status: str
    gender: str | None
    checked_in_at: datetime | None
    attendance_status: str = "checked_in"
    is_staff: bool = False
    restricted_with: frozenset[UUID] = field(default_factory=frozenset)
    display_name: str = ""
    group_id: UUID | None = None


@dataclass(frozen=True)
class CandidateDecision:
    user_id: UUID
    registration_id: UUID
    gender: str | None
    eligibility: CandidateEligibility
    exclusion_kind: ExclusionKind | None
    exclusion_reason: str | None
    display_name: str
    group_id: UUID | None


def build_candidate_decisions(
    records: Iterable[AttendanceRecord],
    *,
    cutoff_at: datetime,
    manual_exclusions: Mapping[UUID, str] | None = None,
) -> list[CandidateDecision]:
    """Decide, per attendee, whether they belong in the frozen candidate list.

    Rules, in priority order:

    1. Staff/operator registrations never appear as candidates.
    2. A registration that is not confirmed is excluded as cancelled.
    3. No check-in at all, a revoked check-in, or a check-in recorded after the
       cutoff means the person did not attend in time.
    4. An audited manual exclusion wins over "eligible" but is recorded with its
       own kind so raw attendance is never rewritten.

    ``cutoff_at`` must be timezone-aware; naive input is a programming error and
    is rejected rather than silently assumed to be UTC.
    """

    if cutoff_at.tzinfo is None:
        raise PostEventRuleError("CUTOFF_NAIVE_DATETIME", "cutoff_at must be timezone-aware.")
    manual = dict(manual_exclusions or {})
    decisions: list[CandidateDecision] = []
    for record in records:
        kind: ExclusionKind | None = None
        reason: str | None = None
        if record.is_staff:
            kind, reason = ExclusionKind.STAFF, "Staff or operator registration."
        elif record.registration_status not in CONFIRMED_REGISTRATION_STATUSES:
            kind = ExclusionKind.CANCELLED
            reason = f"Registration status {record.registration_status} is not confirmed."
        elif record.checked_in_at is None or record.attendance_status in ABSENT_ATTENDANCE_STATUSES:
            kind = ExclusionKind.NO_SHOW
            reason = f"Attendance status {record.attendance_status} with no valid check-in."
        elif record.checked_in_at > cutoff_at:
            kind = ExclusionKind.NOT_CHECKED_IN
            reason = "Check-in recorded after the candidate freeze cutoff."
        elif record.user_id in manual:
            kind, reason = ExclusionKind.MANUAL, manual[record.user_id]
        decisions.append(
            CandidateDecision(
                user_id=record.user_id,
                registration_id=record.registration_id,
                gender=record.gender,
                eligibility=(
                    CandidateEligibility.EXCLUDED if kind else CandidateEligibility.ELIGIBLE
                ),
                exclusion_kind=kind,
                exclusion_reason=reason,
                display_name=record.display_name,
                group_id=record.group_id,
            )
        )
    return decisions


def require_manual_exclusion_reason(reason: str | None) -> str:
    """A manual exclusion is an administrative override and must be explained."""

    cleaned = (reason or "").strip()
    if len(cleaned) < 4:
        raise PostEventRuleError(
            "EXCLUSION_REASON_REQUIRED",
            "A manual candidate exclusion requires a reason of at least 4 characters.",
        )
    return cleaned[:1000]


# ---------------------------------------------------------------------------
# B09 - candidate visibility policy and selection limits (MUT-002)
# ---------------------------------------------------------------------------


class VisibilityMode(StrEnum):
    #: Default for a heterosexual matchmaking event: show the other gender only.
    OPPOSITE_GENDER = "opposite_gender"
    SAME_GENDER = "same_gender"
    ALL_GENDERS = "all_genders"
    #: Explicit allow-list computed by an administrator; the policy stores the
    #: pairs so the rule stays auditable rather than hidden in code.
    CUSTOM = "custom"


DEFAULT_MAX_SELECTIONS = 3
DEFAULT_MIN_SELECTIONS = 0
ABSOLUTE_MAX_SELECTIONS = 3


@dataclass(frozen=True)
class SelectionPolicy:
    """Per-activity candidate visibility and selection limits.

    Defaults follow DEC-003's safe default: the framework is configurable and
    the platform ships no invented production content. ``max_selections`` is
    hard-capped at :data:`ABSOLUTE_MAX_SELECTIONS` because V1.6 states at most
    three choices; an administrator may lower it but never raise it.
    """

    mode: VisibilityMode = VisibilityMode.OPPOSITE_GENDER
    max_selections: int = DEFAULT_MAX_SELECTIONS
    min_selections: int = DEFAULT_MIN_SELECTIONS
    edit_window_hours: int = 24
    allow_edit_after_submit: bool = True
    custom_pairs: frozenset[tuple[UUID, UUID]] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not 0 <= self.min_selections <= self.max_selections:
            raise PostEventRuleError(
                "SELECTION_POLICY_INVALID",
                "min_selections must be between 0 and max_selections.",
            )
        if not 1 <= self.max_selections <= ABSOLUTE_MAX_SELECTIONS:
            raise PostEventRuleError(
                "SELECTION_POLICY_INVALID",
                f"max_selections must be between 1 and {ABSOLUTE_MAX_SELECTIONS}.",
            )
        if self.edit_window_hours < 0:
            raise PostEventRuleError(
                "SELECTION_POLICY_INVALID", "edit_window_hours cannot be negative."
            )


def is_visible_candidate(
    policy: SelectionPolicy,
    *,
    chooser_id: UUID,
    chooser_gender: str | None,
    candidate_id: UUID,
    candidate_gender: str | None,
    restricted_with: Iterable[UUID] = (),
) -> bool:
    """Server-side visibility rule. The UI mirrors it; the API enforces it."""

    if candidate_id == chooser_id:
        return False
    if candidate_id in set(restricted_with):
        return False
    if policy.mode is VisibilityMode.ALL_GENDERS:
        return True
    if policy.mode is VisibilityMode.CUSTOM:
        return (chooser_id, candidate_id) in policy.custom_pairs
    if chooser_gender is None or candidate_gender is None:
        # An unknown gender cannot satisfy a gender-scoped policy. Failing
        # closed keeps an incomplete profile from leaking into the pool.
        return False
    if policy.mode is VisibilityMode.OPPOSITE_GENDER:
        return chooser_gender != candidate_gender
    return chooser_gender == candidate_gender


def validate_selection(
    policy: SelectionPolicy,
    *,
    chooser_id: UUID,
    selected_ids: Sequence[UUID],
    visible_ids: Iterable[UUID],
    no_selection_reason_code: str | None,
    allowed_reason_codes: Iterable[str],
    reason_note: str | None = None,
    reason_requires_note: bool = False,
) -> list[UUID]:
    """Validate a mutual-selection submission and return the normalized order.

    Enforces MUT-002 in full: at most ``policy.max_selections`` unique choices,
    every choice drawn from the frozen visible pool, no self-selection, and a
    configured reason whenever the member selects nobody.
    """

    if len(selected_ids) > policy.max_selections:
        raise PostEventRuleError(
            "SELECTION_LIMIT_EXCEEDED",
            f"At most {policy.max_selections} candidates may be selected.",
            details={"max_selections": policy.max_selections, "submitted": len(selected_ids)},
        )
    seen: list[UUID] = []
    for candidate_id in selected_ids:
        if candidate_id == chooser_id:
            raise PostEventRuleError(
                "SELECTION_SELF_NOT_ALLOWED", "A member cannot select themselves."
            )
        if candidate_id in seen:
            raise PostEventRuleError(
                "SELECTION_DUPLICATE",
                "The same candidate was selected more than once.",
                details={"candidate_id": str(candidate_id)},
            )
        seen.append(candidate_id)
    visible = set(visible_ids)
    outside = [str(item) for item in seen if item not in visible]
    if outside:
        raise PostEventRuleError(
            "SELECTION_CANDIDATE_NOT_ELIGIBLE",
            "One or more selected candidates are not in the frozen eligible list.",
            details={"candidate_ids": outside},
        )
    if len(seen) < policy.min_selections:
        raise PostEventRuleError(
            "SELECTION_MINIMUM_NOT_MET",
            f"At least {policy.min_selections} candidates must be selected.",
            details={"min_selections": policy.min_selections},
        )
    if not seen:
        allowed = {code for code in allowed_reason_codes}
        if not allowed:
            raise PostEventRuleError(
                "PASS_REASON_NOT_CONFIGURED",
                "No pass reasons are configured for this activity, so an empty "
                "submission cannot be accepted.",
            )
        if not no_selection_reason_code:
            raise PostEventRuleError(
                "PASS_REASON_REQUIRED",
                "Selecting nobody requires a reason.",
                details={"allowed_reason_codes": sorted(allowed)},
            )
        if no_selection_reason_code not in allowed:
            raise PostEventRuleError(
                "PASS_REASON_UNKNOWN",
                "The submitted reason is not configured for this activity.",
                details={"allowed_reason_codes": sorted(allowed)},
            )
        if reason_requires_note and not (reason_note or "").strip():
            raise PostEventRuleError(
                "PASS_REASON_NOTE_REQUIRED",
                "The selected reason requires an additional note.",
            )
    elif no_selection_reason_code:
        raise PostEventRuleError(
            "PASS_REASON_NOT_APPLICABLE",
            "A pass reason cannot accompany a non-empty selection.",
        )
    return seen


def selection_edit_deadline(policy: SelectionPolicy, submitted_at: datetime) -> datetime:
    if submitted_at.tzinfo is None:
        raise PostEventRuleError("SUBMITTED_AT_NAIVE", "submitted_at must be timezone-aware.")
    return submitted_at + timedelta(hours=policy.edit_window_hours)


def ensure_selection_editable(
    policy: SelectionPolicy, *, submitted_at: datetime, now: datetime
) -> None:
    if not policy.allow_edit_after_submit:
        raise PostEventRuleError(
            "SELECTION_EDIT_DISABLED", "This activity does not allow editing after submission."
        )
    if now > selection_edit_deadline(policy, submitted_at):
        raise PostEventRuleError(
            "SELECTION_EDIT_WINDOW_CLOSED",
            "The edit window for this submission has closed.",
        )


def compute_mutual_pairs(
    submissions: Mapping[UUID, Sequence[UUID]],
) -> list[tuple[UUID, UUID]]:
    """Return deterministic, de-duplicated mutual pairs.

    Ordering is by the pair's string form so the same input always produces the
    same output regardless of dictionary iteration order.
    """

    pairs: set[tuple[UUID, UUID]] = set()
    for chooser, chosen_list in submissions.items():
        for chosen in chosen_list:
            if chooser in submissions.get(chosen, ()):  # reciprocal
                low, high = sorted((chooser, chosen), key=str)
                pairs.add((low, high))
    return sorted(pairs, key=lambda pair: (str(pair[0]), str(pair[1])))


# ---------------------------------------------------------------------------
# B10 - survey definition, answers, deadline
# ---------------------------------------------------------------------------


class QuestionType(StrEnum):
    RATING = "rating"
    SEGMENT_RATING = "segment_rating"
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    OPEN_TEXT = "open_text"
    BOOLEAN = "boolean"


class SurveyStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXPIRED = "expired"
    WAIVED = "waived"


DEFAULT_OPEN_TEXT_MAX_LENGTH = 2000
RATING_SCALE_FLOOR = 1
RATING_SCALE_CEILING = 10


@dataclass(frozen=True)
class QuestionSpec:
    """One frozen question of a published survey version."""

    question_id: UUID
    question_code: str
    question_type: QuestionType
    is_required: bool = True
    position: int = 0
    scale_min: int = 1
    scale_max: int = 5
    options: tuple[str, ...] = ()
    max_length: int = DEFAULT_OPEN_TEXT_MAX_LENGTH
    min_selections: int = 1
    max_selections: int = 1
    #: ``True`` for a per-participant rating; the answer then carries a subject.
    per_subject: bool = False

    def __post_init__(self) -> None:
        if self.question_type in (QuestionType.RATING, QuestionType.SEGMENT_RATING):
            if not RATING_SCALE_FLOOR <= self.scale_min < self.scale_max <= RATING_SCALE_CEILING:
                raise PostEventRuleError(
                    "QUESTION_SCALE_INVALID",
                    "Rating scale must satisfy "
                    f"{RATING_SCALE_FLOOR} <= min < max <= {RATING_SCALE_CEILING}.",
                    details={"question_code": self.question_code},
                )
        if self.question_type in (QuestionType.SINGLE_CHOICE, QuestionType.MULTI_CHOICE):
            if not self.options:
                raise PostEventRuleError(
                    "QUESTION_OPTIONS_REQUIRED",
                    "A choice question requires at least one option.",
                    details={"question_code": self.question_code},
                )
            if len(set(self.options)) != len(self.options):
                raise PostEventRuleError(
                    "QUESTION_OPTIONS_DUPLICATE",
                    "Choice options must be unique.",
                    details={"question_code": self.question_code},
                )


@dataclass(frozen=True)
class SubmittedAnswer:
    question_code: str
    rating_value: int | None = None
    choice_values: tuple[str, ...] = ()
    text_value: str | None = None
    boolean_value: bool | None = None
    subject_user_id: UUID | None = None


def validate_answers(
    questions: Sequence[QuestionSpec],
    answers: Sequence[SubmittedAnswer],
    *,
    subject_user_ids: Iterable[UUID] = (),
    partial: bool = False,
) -> None:
    """Validate a survey submission against its frozen question set.

    ``partial=True`` is used for autosaved drafts: the shape of every supplied
    answer is still checked, but missing required answers are tolerated. A real
    submit always runs with ``partial=False``.
    """

    by_code = {question.question_code: question for question in questions}
    subjects = set(subject_user_ids)
    seen: set[tuple[str, str]] = set()
    for answer in answers:
        question = by_code.get(answer.question_code)
        if question is None:
            raise PostEventRuleError(
                "SURVEY_QUESTION_UNKNOWN",
                "An answer refers to a question that is not part of this survey version.",
                details={"question_code": answer.question_code},
            )
        key = (answer.question_code, str(answer.subject_user_id or "-"))
        if key in seen:
            raise PostEventRuleError(
                "SURVEY_ANSWER_DUPLICATE",
                "The same question was answered more than once.",
                details={"question_code": answer.question_code},
            )
        seen.add(key)
        _validate_single_answer(question, answer, subjects)
    if partial:
        return
    for question in questions:
        if not question.is_required:
            continue
        expected_subjects = subjects if question.per_subject else {None}
        for subject in expected_subjects:
            if (question.question_code, str(subject or "-")) not in seen:
                raise PostEventRuleError(
                    "SURVEY_ANSWER_MISSING",
                    "A required question has not been answered.",
                    details={
                        "question_code": question.question_code,
                        "subject_user_id": str(subject) if subject else None,
                    },
                )


def _validate_single_answer(
    question: QuestionSpec, answer: SubmittedAnswer, subjects: set[UUID]
) -> None:
    if question.per_subject:
        if answer.subject_user_id is None:
            raise PostEventRuleError(
                "SURVEY_SUBJECT_REQUIRED",
                "This question must be answered per participant.",
                details={"question_code": question.question_code},
            )
        if answer.subject_user_id not in subjects:
            raise PostEventRuleError(
                "SURVEY_SUBJECT_NOT_ELIGIBLE",
                "The rated participant is not part of this member's frozen list.",
                details={"question_code": question.question_code},
            )
    elif answer.subject_user_id is not None:
        raise PostEventRuleError(
            "SURVEY_SUBJECT_NOT_APPLICABLE",
            "This question is not answered per participant.",
            details={"question_code": question.question_code},
        )

    if question.question_type in (QuestionType.RATING, QuestionType.SEGMENT_RATING):
        if answer.rating_value is None:
            raise PostEventRuleError(
                "SURVEY_RATING_REQUIRED",
                "A rating value is required.",
                details={"question_code": question.question_code},
            )
        if not question.scale_min <= answer.rating_value <= question.scale_max:
            raise PostEventRuleError(
                "SURVEY_RATING_OUT_OF_RANGE",
                f"Rating must be between {question.scale_min} and {question.scale_max}.",
                details={"question_code": question.question_code},
            )
    elif question.question_type in (QuestionType.SINGLE_CHOICE, QuestionType.MULTI_CHOICE):
        values = list(answer.choice_values)
        if len(set(values)) != len(values):
            raise PostEventRuleError(
                "SURVEY_CHOICE_DUPLICATE",
                "The same option was selected more than once.",
                details={"question_code": question.question_code},
            )
        unknown = [value for value in values if value not in question.options]
        if unknown:
            raise PostEventRuleError(
                "SURVEY_CHOICE_UNKNOWN",
                "An unknown option was submitted.",
                details={"question_code": question.question_code, "values": unknown},
            )
        limit = 1 if question.question_type is QuestionType.SINGLE_CHOICE else question.max_selections
        floor = 1 if question.question_type is QuestionType.SINGLE_CHOICE else question.min_selections
        if not floor <= len(values) <= limit:
            raise PostEventRuleError(
                "SURVEY_CHOICE_COUNT_INVALID",
                f"Between {floor} and {limit} options must be selected.",
                details={"question_code": question.question_code},
            )
    elif question.question_type is QuestionType.OPEN_TEXT:
        text_value = (answer.text_value or "").strip()
        if question.is_required and not text_value:
            raise PostEventRuleError(
                "SURVEY_TEXT_REQUIRED",
                "This question requires written feedback.",
                details={"question_code": question.question_code},
            )
        if len(text_value) > question.max_length:
            raise PostEventRuleError(
                "SURVEY_TEXT_TOO_LONG",
                f"Written feedback is limited to {question.max_length} characters.",
                details={"question_code": question.question_code},
            )
    elif question.question_type is QuestionType.BOOLEAN and answer.boolean_value is None:
        raise PostEventRuleError(
            "SURVEY_BOOLEAN_REQUIRED",
            "A yes/no answer is required.",
            details={"question_code": question.question_code},
        )


def ensure_survey_open(
    *, opens_at: datetime | None, deadline_at: datetime, now: datetime, override: bool = False
) -> None:
    """Deadline rule for SUR-001.

    All three timestamps are compared in UTC. Display timezone is a
    presentation concern and never changes whether a submission is accepted;
    that is what keeps the behaviour testable across timezones.
    """

    for label, value in (("opens_at", opens_at), ("deadline_at", deadline_at), ("now", now)):
        if value is not None and value.tzinfo is None:
            raise PostEventRuleError("SURVEY_NAIVE_DATETIME", f"{label} must be timezone-aware.")
    if override:
        return
    if opens_at is not None and now < opens_at:
        raise PostEventRuleError(
            "SURVEY_NOT_OPEN",
            "This survey is not open yet.",
            details={"opens_at": opens_at.astimezone(UTC).isoformat()},
        )
    if now > deadline_at:
        raise PostEventRuleError(
            "SURVEY_DEADLINE_PASSED",
            "The survey deadline has passed.",
            details={"deadline_at": deadline_at.astimezone(UTC).isoformat()},
        )


def is_survey_task_eligible(
    *,
    registration_status: str,
    checked_in_at: datetime | None,
    attendance_status: str = "checked_in",
    is_staff: bool = False,
) -> bool:
    """Only confirmed members who actually checked in receive a survey task."""

    if is_staff or checked_in_at is None:
        return False
    if attendance_status in ABSENT_ATTENDANCE_STATUSES:
        return False
    return registration_status in CONFIRMED_REGISTRATION_STATUSES


@dataclass(frozen=True)
class ReminderSlot:
    reminder_code: str
    scheduled_for: datetime


def plan_reminders(
    *,
    deadline_at: datetime,
    offsets_hours: Sequence[int],
    now: datetime,
    task_status: str,
) -> list[ReminderSlot]:
    """Plan reminder slots before a deadline.

    Returns an empty list once the task is complete, waived or expired, which is
    what makes the reminder job idempotent and suppression automatic (SUR-002).
    Slots already in the past are dropped rather than fired late.
    """

    if task_status in (TaskStatus.COMPLETED, TaskStatus.WAIVED, TaskStatus.EXPIRED):
        return []
    slots: dict[str, ReminderSlot] = {}
    for hours in offsets_hours:
        if hours <= 0:
            continue
        scheduled_for = deadline_at - timedelta(hours=hours)
        if scheduled_for <= now:
            continue
        code = f"h-{hours}"
        slots[code] = ReminderSlot(reminder_code=code, scheduled_for=scheduled_for)
    return sorted(slots.values(), key=lambda slot: slot.scheduled_for)


def reminder_dedupe_key(task_id: UUID, reminder_code: str) -> str:
    """Stable key so a re-run of the reminder job cannot double-send."""

    return f"survey-reminder:{task_id}:{reminder_code}"


# ---------------------------------------------------------------------------
# B11 - result letter workflow
# ---------------------------------------------------------------------------


class LetterStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    REVOKED = "revoked"


class LetterOutcome(StrEnum):
    MUTUAL_MATCH = "mutual_match"
    NO_MATCH = "no_match"
    NOT_ELIGIBLE = "not_eligible"


_LETTER_TRANSITIONS: dict[LetterStatus, frozenset[LetterStatus]] = {
    LetterStatus.DRAFT: frozenset({LetterStatus.PENDING_REVIEW, LetterStatus.REVOKED}),
    LetterStatus.PENDING_REVIEW: frozenset(
        {LetterStatus.APPROVED, LetterStatus.REJECTED, LetterStatus.REVOKED}
    ),
    # A rejected letter goes back to draft for editing; it is never published.
    LetterStatus.REJECTED: frozenset({LetterStatus.DRAFT, LetterStatus.REVOKED}),
    LetterStatus.APPROVED: frozenset({LetterStatus.PUBLISHED, LetterStatus.REVOKED}),
    LetterStatus.PUBLISHED: frozenset({LetterStatus.REVOKED}),
    LetterStatus.REVOKED: frozenset(),
}

#: The only status in which a member may read the letter.
MEMBER_VISIBLE_LETTER_STATUSES: frozenset[LetterStatus] = frozenset({LetterStatus.PUBLISHED})


def validate_letter_transition(current: str, target: str) -> None:
    try:
        current_status = LetterStatus(current)
        target_status = LetterStatus(target)
    except ValueError as exc:
        raise PostEventRuleError("LETTER_STATUS_UNKNOWN", f"Unknown letter status: {exc}") from exc
    if target_status not in _LETTER_TRANSITIONS[current_status]:
        raise PostEventRuleError(
            "LETTER_TRANSITION_INVALID",
            f"Cannot move result letter from {current_status} to {target_status}.",
            details={"current": current_status.value, "target": target_status.value},
        )


def is_letter_member_visible(status: str) -> bool:
    try:
        return LetterStatus(status) in MEMBER_VISIBLE_LETTER_STATUSES
    except ValueError:
        return False


def ensure_reviewer_is_not_author(*, reviewer_id: UUID, author_id: UUID | None) -> None:
    """Four-eyes rule: the person who drafted a letter cannot approve it."""

    if author_id is not None and reviewer_id == author_id:
        raise PostEventRuleError(
            "LETTER_REVIEW_SELF_APPROVAL",
            "The author of a result letter cannot review it.",
        )


_TEMPLATE_TOKEN_START = "{{"
_TEMPLATE_TOKEN_END = "}}"


def extract_template_variables(template: str) -> list[str]:
    """Extract ``{{ token }}`` names in first-appearance order."""

    variables: list[str] = []
    cursor = 0
    while True:
        start = template.find(_TEMPLATE_TOKEN_START, cursor)
        if start == -1:
            break
        end = template.find(_TEMPLATE_TOKEN_END, start)
        if end == -1:
            raise PostEventRuleError(
                "LETTER_TEMPLATE_UNCLOSED", "A template token is not closed."
            )
        name = template[start + 2 : end].strip()
        if not name:
            raise PostEventRuleError("LETTER_TEMPLATE_EMPTY_TOKEN", "A template token is empty.")
        if name not in variables:
            variables.append(name)
        cursor = end + 2
    return variables


def render_template(template: str, values: Mapping[str, object]) -> str:
    """Render a letter body with strict variable checking.

    Deliberately not a general-purpose template engine: only flat token
    substitution is supported, so a template can never execute code or reach
    into objects. Any missing variable is an error rather than a blank, which
    prevents half-rendered letters from reaching review.
    """

    required = extract_template_variables(template)
    missing = [name for name in required if name not in values]
    if missing:
        raise PostEventRuleError(
            "LETTER_TEMPLATE_VARIABLE_MISSING",
            "The template references variables that were not supplied.",
            details={"missing": missing},
        )
    rendered = template
    for name in required:
        rendered = rendered.replace(f"{{{{{name}}}}}", str(values[name]))
        rendered = rendered.replace(f"{{{{ {name} }}}}", str(values[name]))
    return rendered


def content_fingerprint(subject: str, body: str) -> str:
    """Stable hash used to prove a published letter did not silently change."""

    import hashlib

    digest = hashlib.sha256()
    digest.update(subject.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(body.encode("utf-8"))
    return digest.hexdigest()
