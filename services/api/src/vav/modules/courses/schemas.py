from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CourseCreateRequest(BaseModel):
    course_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,127}$")
    internal_name: str = Field(min_length=2, max_length=200)
    course_type: Literal["self_paced", "cohort", "hybrid"] = "self_paced"
    default_locale: str = Field(default="zh-CN", max_length=16)
    visibility: Literal["public", "authenticated", "private"] = "public"
    difficulty_level: Literal["beginner", "intermediate", "advanced"] | None = None
    free_access_policy: Literal["free_enrollment"] | None = None


class CourseUpdateRequest(BaseModel):
    expected_version: int = Field(gt=0)
    internal_name: str | None = Field(default=None, min_length=2, max_length=200)
    visibility: Literal["public", "authenticated", "private"] | None = None
    difficulty_level: Literal["beginner", "intermediate", "advanced"] | None = None
    estimated_duration_minutes: int | None = Field(default=None, gt=0, le=100_000)
    featured: bool | None = None
    sort_order: int | None = None
    free_access_policy: Literal["free_enrollment"] | None = None


class CourseLocalizationRequest(BaseModel):
    locale: str = Field(min_length=2, max_length=16)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,199}$")
    title: str = Field(min_length=2, max_length=300)
    subtitle: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=4000)
    description_blocks: list[dict[str, Any]] = Field(default_factory=list)
    learning_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    target_audience: list[dict[str, Any]] = Field(default_factory=list)
    prerequisites: list[dict[str, Any]] = Field(default_factory=list)
    instructor_summary: str | None = Field(default=None, max_length=4000)
    refund_notice: str | None = Field(default=None, max_length=4000)
    translation_status: Literal["draft", "ready"] = "draft"


class InstructorCreateRequest(BaseModel):
    instructor_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,127}$")
    display_name: str = Field(min_length=2, max_length=200)
    linked_user_id: UUID | None = None
    status: Literal["active", "inactive"] = "active"


class InstructorAssignmentRequest(BaseModel):
    instructor_id: UUID
    role: Literal["lead", "co_instructor", "guest"] = "lead"
    sort_order: int = 0


class ModuleCreateRequest(BaseModel):
    module_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,127}$")
    internal_name: str = Field(min_length=2, max_length=200)
    title: str = Field(min_length=2, max_length=300)
    locale: str = "zh-CN"
    sort_order: int = 0
    status: Literal["draft", "published"] = "draft"
    required: bool = True
    release_offset_days: int | None = Field(default=None, ge=0, le=3650)
    release_at: datetime | None = None


class LessonCreateRequest(BaseModel):
    lesson_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,127}$")
    internal_name: str = Field(min_length=2, max_length=200)
    title: str = Field(min_length=2, max_length=300)
    locale: str = "zh-CN"
    lesson_type: Literal[
        "video",
        "rich_text",
        "audio",
        "document",
        "exercise",
        "assignment",
        "external_activity",
    ]
    sort_order: int = 0
    status: Literal["draft", "published"] = "draft"
    required: bool = True
    preview_policy: Literal["none", "public", "authenticated"] = "none"
    completion_mode: Literal["video_watch", "manual", "exercise_pass", "assignment_graded"]
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    estimated_duration_minutes: int | None = Field(default=None, gt=0, le=100_000)
    release_offset_days: int | None = Field(default=None, ge=0, le=3650)
    release_at: datetime | None = None


class PrerequisiteCreateRequest(BaseModel):
    prerequisite_lesson_id: UUID
    required_completion: bool = True
    minimum_score_basis_points: int | None = Field(default=None, ge=0, le=10_000)


class VideoAttachRequest(BaseModel):
    provider_video_id: str = Field(min_length=1, max_length=255)
    private_reference: str = Field(min_length=1, max_length=4000)
    duration_seconds: int = Field(gt=0, le=86400)
    processing_status: Literal["processing", "ready", "failed"] = "ready"
    required_watch_basis_points: int = Field(default=9000, ge=1, le=10000)


class SkuMappingRequest(BaseModel):
    catalog_sku_id: UUID
    access_duration_days: int | None = Field(default=None, gt=0)
    access_start_policy: Literal["entitlement_activation"] = "entitlement_activation"
    course_version_policy: Literal["pin_at_enrollment"] = "pin_at_enrollment"


class CourseTransitionRequest(BaseModel):
    target_status: Literal[
        "draft",
        "in_review",
        "scheduled",
        "published",
        "enrollment_closed",
        "unpublished",
        "archived",
    ]
    reason: str = Field(min_length=2, max_length=2000)


class HeartbeatRequest(BaseModel):
    sequence: int = Field(gt=0)
    position_seconds: int = Field(ge=0)
    played_seconds: int = Field(ge=0, le=300)
    playback_rate: float = Field(default=1, ge=0.25, le=4)
    occurred_at: datetime


class LearningEventRequest(BaseModel):
    lesson_id: UUID
    event_type: Literal["lesson_opened", "manual_completed"]
    event_sequence: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=128)
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class ExerciseCreateRequest(BaseModel):
    lesson_id: UUID
    exercise_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,127}$")
    exercise_type: Literal["quiz", "reflection", "assignment"] = "quiz"
    grading_mode: Literal["automatic", "manual", "hybrid"] = "automatic"
    passing_score_basis_points: int | None = Field(default=7000, ge=0, le=10000)
    maximum_attempts: int | None = Field(default=3, gt=0, le=100)
    cooldown_minutes: int | None = Field(default=None, ge=0, le=43_200)
    reveal_answers_policy: Literal["never", "after_pass", "after_final_attempt"] = "after_pass"


class QuestionCreateRequest(BaseModel):
    question_type: Literal["single_choice", "multiple_choice", "true_false", "text", "file"]
    sort_order: int = 0
    points: int = Field(default=1, gt=0, le=100)
    required: bool = True
    prompt_blocks: list[dict[str, Any]]
    options: list[dict[str, Any]] = Field(default_factory=list)
    answer_key: Any = None
    locale: str = "zh-CN"


class AttemptSubmitRequest(BaseModel):
    responses: dict[str, Any]


class AttemptSaveRequest(BaseModel):
    responses: dict[str, Any]


class ManualGradeRequest(BaseModel):
    score_basis_points: int = Field(ge=0, le=10000)
    feedback: str | None = Field(default=None, max_length=10000)


class EnrollmentActionRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


class AdminEnrollmentGrantRequest(BaseModel):
    user_id: UUID
    access_duration_days: int | None = Field(default=None, gt=0, le=3650)
    reason: str = Field(min_length=2, max_length=2000)


class ProgressResetRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)
