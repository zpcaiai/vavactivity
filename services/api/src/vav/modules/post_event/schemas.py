"""Request payloads for the post-event closure module."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_STRICT = ConfigDict(extra="forbid")


class _Base(BaseModel):
    model_config = _STRICT


# ---------------------------------------------------------------------------
# B09 candidate freeze / selection
# ---------------------------------------------------------------------------


class SelectionPolicyRequest(_Base):
    visibility_mode: Literal["opposite_gender", "same_gender", "all_genders", "custom"] = (
        "opposite_gender"
    )
    max_selections: Annotated[int, Field(ge=1, le=3)] = 3
    min_selections: Annotated[int, Field(ge=0, le=3)] = 0
    edit_window_hours: Annotated[int, Field(ge=0, le=720)] = 24
    allow_edit_after_submit: bool = True
    custom_rule: dict[str, Any] = Field(default_factory=dict)


class PassReasonOptionRequest(_Base):
    reason_code: Annotated[
        str, Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]{1,63}$")
    ]
    sort_order: Annotated[int, Field(ge=0, le=999)] = 0
    requires_note: bool = False
    is_active: bool = True


class FreezeCandidatesRequest(_Base):
    """Freeze the candidate list. ``cutoff_at`` defaults to the freeze moment."""

    cutoff_at: datetime | None = None
    freeze_note: Annotated[str, Field(max_length=1000)] | None = None
    #: Set when re-freezing after a correction; the previous snapshot is
    #: superseded rather than edited.
    supersede_existing: bool = False


class ExcludeCandidateRequest(_Base):
    user_id: UUID
    reason: Annotated[str, Field(min_length=4, max_length=1000)]


class RestoreCandidateRequest(_Base):
    user_id: UUID
    reason: Annotated[str, Field(min_length=4, max_length=1000)]


class SelectionSubmitRequest(_Base):
    selected_user_ids: Annotated[list[UUID], Field(max_length=3)] = Field(default_factory=list)
    no_selection_reason_code: Annotated[str, Field(max_length=64)] | None = None
    no_selection_reason_note: Annotated[str, Field(max_length=1000)] | None = None
    #: ``draft`` autosaves without locking; ``submitted`` runs the full rule set.
    status: Literal["draft", "submitted"] = "submitted"

    @field_validator("selected_user_ids")
    @classmethod
    def _reject_duplicates(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("selected_user_ids must be unique")
        return value


# ---------------------------------------------------------------------------
# B10 survey
# ---------------------------------------------------------------------------


class SurveyQuestionRequest(_Base):
    question_code: Annotated[str, Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    question_type: Literal[
        "rating", "segment_rating", "single_choice", "multi_choice", "open_text", "boolean"
    ]
    prompt: Annotated[str, Field(min_length=1, max_length=2000)]
    help_text: Annotated[str, Field(max_length=2000)] | None = None
    is_required: bool = True
    per_subject: bool = False
    position: Annotated[int, Field(ge=1, le=200)]
    config: dict[str, Any] = Field(default_factory=dict)


class SurveyDefinitionRequest(_Base):
    survey_code: Annotated[str, Field(min_length=2, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")]
    semantic_version: Annotated[str, Field(min_length=1, max_length=32)]
    title: Annotated[str, Field(min_length=1, max_length=300)]
    description: Annotated[str, Field(max_length=4000)] | None = None
    default_locale: Annotated[str, Field(max_length=16)] = "zh-CN"
    scope: Literal["post_event"] = "post_event"
    questions: Annotated[list[SurveyQuestionRequest], Field(min_length=1, max_length=200)]


class SurveyLocalizationRequest(_Base):
    locale: Annotated[str, Field(min_length=2, max_length=16)]
    prompt: Annotated[str, Field(min_length=1, max_length=2000)]
    help_text: Annotated[str, Field(max_length=2000)] | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class SurveyAssignmentRequest(_Base):
    definition_id: UUID
    deadline_at: datetime
    opens_at: datetime | None = None
    display_timezone: Annotated[str, Field(max_length=64)] = "Asia/Shanghai"
    reminder_offsets_hours: Annotated[list[int], Field(max_length=8)] = Field(
        default_factory=lambda: [48, 12]
    )
    #: Bind the survey to a frozen candidate snapshot so per-participant
    #: questions can only rate people the member actually met.
    snapshot_id: UUID | None = None


class SurveyAnswerRequest(_Base):
    question_code: Annotated[str, Field(min_length=1, max_length=64)]
    rating_value: Annotated[int, Field(ge=1, le=10)] | None = None
    boolean_value: bool | None = None
    choice_values: Annotated[list[str], Field(max_length=50)] = Field(default_factory=list)
    text_value: Annotated[str, Field(max_length=4000)] | None = None
    subject_user_id: UUID | None = None


class SurveyResponseRequest(_Base):
    answers: Annotated[list[SurveyAnswerRequest], Field(max_length=500)]
    status: Literal["draft", "submitted"] = "submitted"


class SurveyReopenRequest(_Base):
    reason: Annotated[str, Field(min_length=4, max_length=1000)]
    new_deadline_at: datetime | None = None


# ---------------------------------------------------------------------------
# B11 result letters
# ---------------------------------------------------------------------------


class LetterTemplateRequest(_Base):
    template_code: Annotated[
        str, Field(min_length=2, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")
    ]
    semantic_version: Annotated[str, Field(min_length=1, max_length=32)]
    locale: Annotated[str, Field(min_length=2, max_length=16)]
    outcome: Literal["mutual_match", "no_match", "not_eligible"]
    subject_template: Annotated[str, Field(min_length=1, max_length=500)]
    body_template: Annotated[str, Field(min_length=1, max_length=20000)]


class LetterGenerateRequest(_Base):
    """Generate drafts for every member of a frozen snapshot."""

    snapshot_id: UUID
    locale: Annotated[str, Field(max_length=16)] = "zh-CN"
    template_code: Annotated[str, Field(max_length=128)] | None = None
    #: Regenerate drafts that already exist. Approved/published letters are
    #: never touched; a new version is created instead.
    regenerate: bool = False


class LetterReviewRequest(_Base):
    decision: Literal["approved", "rejected", "changes_requested"]
    comment: Annotated[str, Field(max_length=2000)] | None = None
    #: Hash of the content the reviewer actually read. If the letter changed in
    #: the meantime the decision is rejected rather than applied to new text.
    reviewed_content_hash: Annotated[str, Field(min_length=64, max_length=64)]


class LetterPublishRequest(_Base):
    notify: bool = True


class LetterRevokeRequest(_Base):
    reason: Annotated[str, Field(min_length=4, max_length=1000)]
