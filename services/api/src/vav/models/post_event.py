"""Post-event closure ORM models (B09 candidate freeze, B10 survey, B11 letters).

Table names keep the ``activity_`` / ``survey_`` / ``result_letter_`` prefixes
already used by the activities module so the schema stays navigable. Every
sensitive free-text column is stored through the privacy crypto helpers by the
service layer; the columns themselves are opaque text here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.activities import created_at, updated_at, uuid_pk
from vav.models.base import Base

# ---------------------------------------------------------------------------
# B09 candidate freeze
# ---------------------------------------------------------------------------


class ActivityCandidateSnapshot(Base):
    """An immutable, versioned candidate list produced at the freeze cutoff."""

    __tablename__ = "activity_candidate_snapshots"
    __table_args__ = (UniqueConstraint("activity_id", "snapshot_version"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'draft'"))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    frozen_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_snapshot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    considered_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    freeze_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityCandidateEntry(Base):
    """One attendee's frozen standing inside a snapshot."""

    __tablename__ = "activity_candidate_entries"
    __table_args__ = (UniqueConstraint("snapshot_id", "user_id"),)

    id: Mapped[UUID] = uuid_pk()
    snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("activity_candidate_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    registration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_registrations.id"), nullable=False
    )
    gender: Mapped[str | None] = mapped_column(String(32))
    group_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    eligibility: Mapped[str] = mapped_column(String(16), nullable=False)
    exclusion_kind: Mapped[str | None] = mapped_column(String(32))
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    excluded_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class ActivitySelectionPolicy(Base):
    """Per-activity candidate visibility and selection limits (DEC-003)."""

    __tablename__ = "activity_selection_policies"
    __table_args__ = (UniqueConstraint("activity_id"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    visibility_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'opposite_gender'")
    )
    max_selections: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    min_selections: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    edit_window_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("24")
    )
    allow_edit_after_submit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    custom_rule: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityPassReasonOption(Base):
    """Configurable "selected nobody" reasons.

    ``activity_id`` NULL means the platform-wide default set. No production
    copy ships in code: administrators create the codes and the frontend
    localizes them, which is DEC-003's safe default.
    """

    __tablename__ = "activity_pass_reason_options"

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id")
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    requires_note: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivitySelectionSubmission(Base):
    """A member's mutual-selection submission against one frozen snapshot."""

    __tablename__ = "activity_selection_submissions"
    __table_args__ = (UniqueConstraint("snapshot_id", "chooser_user_id"),)

    id: Mapped[UUID] = uuid_pk()
    snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_candidate_snapshots.id"), nullable=False
    )
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    chooser_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    selection_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    no_selection_reason_code: Mapped[str | None] = mapped_column(String(64))
    no_selection_reason_note: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    editable_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivitySelectionItem(Base):
    __tablename__ = "activity_selection_items"
    __table_args__ = (
        UniqueConstraint("submission_id", "chosen_user_id"),
        UniqueConstraint("submission_id", "rank"),
    )

    id: Mapped[UUID] = uuid_pk()
    submission_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("activity_selection_submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chosen_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created_at()


class ActivitySelectionAudit(Base):
    """Append-only trail for freeze, exclusion and submission edits."""

    __tablename__ = "activity_selection_audits"

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    snapshot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()


# ---------------------------------------------------------------------------
# B10 post-event survey
# ---------------------------------------------------------------------------


class SurveyDefinition(Base):
    __tablename__ = "survey_definitions"
    __table_args__ = (UniqueConstraint("survey_code", "semantic_version"),)

    id: Mapped[UUID] = uuid_pk()
    survey_code: Mapped[str] = mapped_column(String(128), nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'post_event'")
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_locale: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'zh-CN'")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class SurveyQuestion(Base):
    __tablename__ = "survey_questions"
    __table_args__ = (
        UniqueConstraint("definition_id", "question_code"),
        UniqueConstraint("definition_id", "position"),
    )

    id: Mapped[UUID] = uuid_pk()
    definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("survey_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_code: Mapped[str] = mapped_column(String(64), nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    help_text: Mapped[str | None] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    per_subject: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at()


class SurveyQuestionLocalization(Base):
    __tablename__ = "survey_question_localizations"
    __table_args__ = (UniqueConstraint("question_id", "locale"),)

    id: Mapped[UUID] = uuid_pk()
    question_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("survey_questions.id", ondelete="CASCADE"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    help_text: Mapped[str | None] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at()


class ActivitySurveyAssignment(Base):
    """Freezes one published survey version onto one activity."""

    __tablename__ = "activity_survey_assignments"
    __table_args__ = (UniqueConstraint("activity_id", "definition_id"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("survey_definitions.id"), nullable=False
    )
    snapshot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_candidate_snapshots.id")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'scheduled'")
    )
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    display_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'Asia/Shanghai'")
    )
    reminder_offsets_hours: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[48, 12]'::jsonb")
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class SurveyTask(Base):
    __tablename__ = "survey_tasks"
    __table_args__ = (UniqueConstraint("assignment_id", "user_id"),)

    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_survey_assignments.id"), nullable=False
    )
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    __table_args__ = (UniqueConstraint("assignment_id", "user_id"),)

    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_survey_assignments.id"), nullable=False
    )
    definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("survey_definitions.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    override_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    override_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class SurveyAnswer(Base):
    """One answer. ``subject_key`` is ``'-'`` for event-level questions."""

    __tablename__ = "survey_answers"
    __table_args__ = (UniqueConstraint("response_id", "question_id", "subject_key"),)

    id: Mapped[UUID] = uuid_pk()
    response_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("survey_responses.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("survey_questions.id"), nullable=False
    )
    subject_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    subject_key: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'-'"))
    rating_value: Mapped[int | None] = mapped_column(Integer)
    boolean_value: Mapped[bool | None] = mapped_column(Boolean)
    choice_values: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    text_value_encrypted: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime] = created_at()


class SurveyReminderDispatch(Base):
    __tablename__ = "survey_reminder_dispatches"
    __table_args__ = (UniqueConstraint("dedupe_key"),)

    id: Mapped[UUID] = uuid_pk()
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("survey_tasks.id", ondelete="CASCADE"), nullable=False
    )
    reminder_code: Mapped[str] = mapped_column(String(32), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'scheduled'")
    )
    created_at: Mapped[datetime] = created_at()


# ---------------------------------------------------------------------------
# B11 result letters
# ---------------------------------------------------------------------------


class ResultLetterTemplate(Base):
    __tablename__ = "result_letter_templates"
    __table_args__ = (UniqueConstraint("template_code", "semantic_version", "locale"),)

    id: Mapped[UUID] = uuid_pk()
    template_code: Mapped[str] = mapped_column(String(128), nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(32), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    declared_variables: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ResultLetter(Base):
    __tablename__ = "result_letters"
    __table_args__ = (UniqueConstraint("activity_id", "recipient_user_id", "version"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_candidate_snapshots.id"), nullable=False
    )
    recipient_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    template_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("result_letter_templates.id")
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'draft'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    subject_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    body_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    matched_user_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    authored_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ResultLetterReview(Base):
    __tablename__ = "result_letter_reviews"

    id: Mapped[UUID] = uuid_pk()
    letter_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("result_letters.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    reviewed_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at()


class ResultLetterRelease(Base):
    """Immutable published snapshot. Never updated, only superseded."""

    __tablename__ = "result_letter_releases"
    __table_args__ = (UniqueConstraint("letter_id", "version"),)

    id: Mapped[UUID] = uuid_pk()
    letter_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("result_letters.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    body_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    released_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notification_dedupe_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at()
