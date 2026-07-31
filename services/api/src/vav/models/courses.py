from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column

from vav.models.base import Base


def uuid_pk() -> MappedColumn[UUID]:
    return mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def created_at() -> MappedColumn[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def updated_at() -> MappedColumn[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CourseCompletionPolicy(Base):
    __tablename__ = "course_completion_policies"

    id: Mapped[UUID] = uuid_pk()
    policy_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    required_lesson_completion_basis_points: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("10000")
    )
    require_all_required_lessons: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    required_exercise_pass_basis_points: Mapped[int | None] = mapped_column(Integer)
    require_all_required_exercises: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    minimum_total_score_basis_points: Mapped[int | None] = mapped_column(Integer)
    certificate_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    policy_schema: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[UUID] = uuid_pk()
    course_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    internal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    course_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'public'")
    )
    default_locale: Mapped[str] = mapped_column(String(16), nullable=False)
    difficulty_level: Mapped[str | None] = mapped_column(String(32))
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    enrollment_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrollment_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_release_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'all_at_once'")
    )
    unpublished_access_policy: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'block_new_enrollment_only'")
    )
    free_access_policy: Mapped[str | None] = mapped_column(String(32))
    catalog_product_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id")
    )
    primary_catalog_sku_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_skus.id")
    )
    completion_policy_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_completion_policies.id")
    )
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    updated_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CourseLocalization(Base):
    __tablename__ = "course_localizations"
    __table_args__ = (
        UniqueConstraint("course_id", "locale"),
        UniqueConstraint("locale", "slug"),
    )

    id: Mapped[UUID] = uuid_pk()
    course_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("courses.id"))
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    description_blocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    learning_outcomes: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    target_audience: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    prerequisites: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    instructor_summary: Mapped[str | None] = mapped_column(Text)
    refund_notice: Mapped[str | None] = mapped_column(Text)
    seo_title: Mapped[str | None] = mapped_column(String(300))
    seo_description: Mapped[str | None] = mapped_column(String(500))
    cover_media_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id")
    )
    translation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'draft'")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CourseInstructor(Base):
    __tablename__ = "course_instructors"

    id: Mapped[UUID] = uuid_pk()
    instructor_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    linked_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id")
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    avatar_media_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CourseInstructorAssignment(Base):
    __tablename__ = "course_instructor_assignments"
    __table_args__ = (PrimaryKeyConstraint("course_id", "instructor_id", "role"),)

    course_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("courses.id"))
    instructor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_instructors.id")
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class CourseVersion(Base):
    __tablename__ = "course_versions"
    __table_args__ = (UniqueConstraint("course_id", "version_number"),)

    id: Mapped[UUID] = uuid_pk()
    course_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("courses.id"))
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    curriculum_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class CourseModule(Base):
    __tablename__ = "course_modules"
    __table_args__ = (UniqueConstraint("course_id", "module_code"),)

    id: Mapped[UUID] = uuid_pk()
    course_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("courses.id"))
    module_code: Mapped[str] = mapped_column(String(128), nullable=False)
    internal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    release_offset_days: Mapped[int | None] = mapped_column(Integer)
    release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CourseModuleLocalization(Base):
    __tablename__ = "course_module_localizations"
    __table_args__ = (PrimaryKeyConstraint("module_id", "locale"),)

    module_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("course_modules.id"))
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class CourseLesson(Base):
    __tablename__ = "course_lessons"
    __table_args__ = (UniqueConstraint("module_id", "lesson_code"),)

    id: Mapped[UUID] = uuid_pk()
    module_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("course_modules.id"))
    lesson_code: Mapped[str] = mapped_column(String(128), nullable=False)
    internal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    lesson_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    preview_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'none'")
    )
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    completion_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    completion_threshold: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    release_offset_days: Mapped[int | None] = mapped_column(Integer)
    release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CourseLessonLocalization(Base):
    __tablename__ = "course_lesson_localizations"
    __table_args__ = (PrimaryKeyConstraint("lesson_id", "locale"),)

    lesson_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("course_lessons.id"))
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    content_blocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class LessonPrerequisite(Base):
    __tablename__ = "lesson_prerequisites"
    __table_args__ = (PrimaryKeyConstraint("lesson_id", "prerequisite_lesson_id"),)

    lesson_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("course_lessons.id"))
    prerequisite_lesson_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_lessons.id")
    )
    required_completion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    minimum_score_basis_points: Mapped[int | None] = mapped_column(Integer)


class CourseSkuMapping(Base):
    __tablename__ = "course_sku_mappings"
    __table_args__ = (UniqueConstraint("catalog_sku_id", "course_id"),)

    id: Mapped[UUID] = uuid_pk()
    catalog_sku_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_skus.id")
    )
    course_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("courses.id"))
    access_duration_days: Mapped[int | None] = mapped_column(Integer)
    access_start_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    course_version_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = created_at()


class CourseVideoAsset(Base):
    __tablename__ = "course_video_assets"

    id: Mapped[UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_environment: Mapped[str] = mapped_column(String(16), nullable=False)
    media_asset_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id")
    )
    provider_video_id: Mapped[str | None] = mapped_column(String(255))
    private_reference_encrypted: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    playback_format: Mapped[str | None] = mapped_column(String(32))
    drm_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'none'")
    )
    original_source_visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'private'")
    )
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class LessonVideoResource(Base):
    __tablename__ = "lesson_video_resources"

    lesson_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_lessons.id"), primary_key=True
    )
    video_asset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_video_assets.id")
    )
    required_watch_basis_points: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("9000")
    )
    allow_seek: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    allow_playback_speed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    captions_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CourseEnrollment(Base):
    __tablename__ = "course_enrollments"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    course_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("courses.id"))
    course_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_versions.id")
    )
    entitlement_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entitlements.id")
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    access_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CourseInboxEvent(Base):
    __tablename__ = "course_inbox_events"

    id: Mapped[UUID] = uuid_pk()
    source_event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = created_at()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CoursePlaybackSession(Base):
    __tablename__ = "course_playback_sessions"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    enrollment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_enrollments.id")
    )
    lesson_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("course_lessons.id"))
    video_asset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_video_assets.id")
    )
    access_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_position_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    maximum_position_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    valid_played_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    device_session_hash: Mapped[str | None] = mapped_column(String(128))
    ip_address_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class LessonProgress(Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (UniqueConstraint("enrollment_id", "lesson_id"),)

    id: Mapped[UUID] = uuid_pk()
    enrollment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_enrollments.id")
    )
    lesson_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("course_lessons.id"))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'not_started'")
    )
    progress_basis_points: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_position_seconds: Mapped[int | None] = mapped_column(Integer)
    maximum_position_seconds: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_source: Mapped[str | None] = mapped_column(String(32))
    completion_evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class LearningEvent(Base):
    __tablename__ = "learning_events"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "idempotency_key"),
        UniqueConstraint("enrollment_id", "event_sequence"),
    )

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    enrollment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_enrollments.id")
    )
    lesson_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_lessons.id")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = created_at()


class CourseExercise(Base):
    __tablename__ = "course_exercises"
    __table_args__ = (UniqueConstraint("lesson_id", "exercise_code"),)

    id: Mapped[UUID] = uuid_pk()
    lesson_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("course_lessons.id"))
    exercise_code: Mapped[str] = mapped_column(String(128), nullable=False)
    exercise_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    grading_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    passing_score_basis_points: Mapped[int | None] = mapped_column(Integer)
    maximum_attempts: Mapped[int | None] = mapped_column(Integer)
    cooldown_minutes: Mapped[int | None] = mapped_column(Integer)
    randomize_questions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    randomize_options: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    reveal_answers_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ExerciseQuestion(Base):
    __tablename__ = "exercise_questions"

    id: Mapped[UUID] = uuid_pk()
    exercise_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_exercises.id")
    )
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    question_schema: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    answer_key_encrypted: Mapped[str | None] = mapped_column(Text)
    grading_schema: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ExerciseQuestionLocalization(Base):
    __tablename__ = "exercise_question_localizations"
    __table_args__ = (PrimaryKeyConstraint("question_id", "locale"),)

    question_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercise_questions.id")
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt_blocks: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    options: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    explanation_blocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class ExerciseAttempt(Base):
    __tablename__ = "exercise_attempts"
    __table_args__ = (UniqueConstraint("exercise_id", "enrollment_id", "attempt_number"),)

    id: Mapped[UUID] = uuid_pk()
    exercise_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_exercises.id")
    )
    enrollment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_enrollments.id")
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    question_snapshot: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    response_snapshot_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    auto_score_basis_points: Mapped[int | None] = mapped_column(Integer)
    manual_score_basis_points: Mapped[int | None] = mapped_column(Integer)
    final_score_basis_points: Mapped[int | None] = mapped_column(Integer)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    graded_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    grader_feedback_encrypted: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CourseCompletionRecord(Base):
    __tablename__ = "course_completion_records"

    id: Mapped[UUID] = uuid_pk()
    enrollment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_enrollments.id"), unique=True
    )
    course_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("courses.id"))
    course_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_versions.id")
    )
    completion_policy_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    completion_evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evaluated_by: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at()


class CourseCertificate(Base):
    __tablename__ = "course_certificates"

    id: Mapped[UUID] = uuid_pk()
    certificate_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    completion_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_completion_records.id"), unique=True
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    course_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("courses.id"))
    recipient_name_snapshot: Mapped[str] = mapped_column(String(300), nullable=False)
    course_title_snapshot: Mapped[str] = mapped_column(String(300), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    certificate_document_media_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    replaced_by_certificate_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("course_certificates.id")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
