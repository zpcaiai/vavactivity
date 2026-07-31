# ruff: noqa: B008

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.models.catalog import Product, ProductSku
from vav.models.courses import (
    Course,
    CourseCertificate,
    CourseCompletionPolicy,
    CourseEnrollment,
    CourseExercise,
    CourseInstructor,
    CourseInstructorAssignment,
    CourseLesson,
    CourseLessonLocalization,
    CourseLocalization,
    CourseModule,
    CourseModuleLocalization,
    CoursePlaybackSession,
    CourseSkuMapping,
    CourseVersion,
    CourseVideoAsset,
    ExerciseAttempt,
    ExerciseQuestion,
    ExerciseQuestionLocalization,
    LessonPrerequisite,
    LessonProgress,
    LessonVideoResource,
)
from vav.models.identity import User
from vav.modules.courses.crypto import (
    encrypt_sensitive,
    issue_playback_token,
    token_hash,
    verify_playback_token,
)
from vav.modules.courses.domain import CourseStatus
from vav.modules.courses.providers import get_course_video_provider
from vav.modules.courses.schemas import (
    AdminEnrollmentGrantRequest,
    AttemptSaveRequest,
    AttemptSubmitRequest,
    CourseCreateRequest,
    CourseLocalizationRequest,
    CourseTransitionRequest,
    CourseUpdateRequest,
    EnrollmentActionRequest,
    ExerciseCreateRequest,
    HeartbeatRequest,
    InstructorAssignmentRequest,
    InstructorCreateRequest,
    LearningEventRequest,
    LessonCreateRequest,
    ManualGradeRequest,
    ModuleCreateRequest,
    PrerequisiteCreateRequest,
    ProgressResetRequest,
    QuestionCreateRequest,
    SkuMappingRequest,
    VideoAttachRequest,
)
from vav.modules.courses.service import (
    assessment_service,
    certificate_payload,
    completion_service,
    enrollment_payload,
    enrollment_service,
    ensure_lesson_access,
    localized_course_payload,
    progress_payload,
    progress_service,
    publication_service,
)
from vav.modules.identity.audit import record_security_event
from vav.modules.identity.dependencies import (
    AuthenticatedPrincipal,
    require_admin_principal,
    require_authenticated_user,
)
from vav.modules.identity.permissions import require_permission

router = APIRouter()


async def course_or_404(session: AsyncSession, course_id: UUID) -> Course:
    value = await session.get(Course, course_id)
    if value is None:
        raise VavError("COURSE_NOT_FOUND", "Course was not found.", status_code=404)
    return value


async def exercise_or_404(session: AsyncSession, exercise_id: UUID) -> CourseExercise:
    value = await session.get(CourseExercise, exercise_id)
    if value is None:
        raise VavError("COURSE_EXERCISE_NOT_FOUND", "Exercise was not found.", status_code=404)
    return value


@router.get("/public/courses")
@router.get("/courses")
async def list_courses(
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(Course)
                .where(
                    Course.status.in_((CourseStatus.PUBLISHED, CourseStatus.ENROLLMENT_CLOSED)),
                    Course.visibility == "public",
                )
                .order_by(Course.featured.desc(), Course.sort_order, Course.id)
            )
        ).all()
    )
    return success(
        {
            "items": [
                await localized_course_payload(session, item, locale=locale) for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.get("/public/courses/{slug}")
@router.get("/courses/{slug}")
async def course_detail(
    slug: str,
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    localization = await session.scalar(
        select(CourseLocalization).where(
            CourseLocalization.locale == locale, CourseLocalization.slug == slug
        )
    )
    course = await session.get(Course, localization.course_id) if localization else None
    if (
        course is None
        or course.visibility != "public"
        or course.status not in {CourseStatus.PUBLISHED, CourseStatus.ENROLLMENT_CLOSED}
    ):
        raise VavError("COURSE_NOT_FOUND", "Course was not found.", status_code=404)
    return success(
        await localized_course_payload(session, course, locale=locale, include_curriculum=True),
        request_id_from_request(request),
    )


@router.get("/public/courses/{course_id}/curriculum")
async def public_curriculum(
    course_id: UUID,
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    course = await course_or_404(session, course_id)
    if course.visibility != "public" or course.status not in {
        CourseStatus.PUBLISHED,
        CourseStatus.ENROLLMENT_CLOSED,
    }:
        raise VavError("COURSE_NOT_FOUND", "Course was not found.", status_code=404)
    payload = await localized_course_payload(
        session, course, locale=locale, include_curriculum=True
    )
    return success({"items": payload["modules"]}, request_id_from_request(request))


@router.get("/public/courses/{course_id}/access-summary")
async def public_access_summary(
    course_id: UUID,
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    course = await course_or_404(session, course_id)
    if course.visibility != "public" or course.status not in {
        CourseStatus.PUBLISHED,
        CourseStatus.ENROLLMENT_CLOSED,
    }:
        raise VavError("COURSE_NOT_FOUND", "Course was not found.", status_code=404)
    payload = await localized_course_payload(session, course, locale=locale)
    return success(
        {
            "course_id": str(course.id),
            "free_enrollment": payload["free_enrollment"],
            "purchase_required": not payload["free_enrollment"],
            "catalog_product_id": payload["catalog_product_id"],
            "catalog_sku_id": payload["catalog_sku_id"],
            "access_duration_days": payload["access_duration_days"],
            "prices": payload["prices"],
        },
        request_id_from_request(request),
    )


@router.get("/public/courses/{course_id}/lessons/{lesson_id}")
async def public_preview_lesson(
    course_id: UUID,
    lesson_id: UUID,
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    course = await course_or_404(session, course_id)
    lesson = await session.get(CourseLesson, lesson_id)
    module = await session.get(CourseModule, lesson.module_id) if lesson else None
    if (
        course.visibility != "public"
        or course.status not in {CourseStatus.PUBLISHED, CourseStatus.ENROLLMENT_CLOSED}
        or lesson is None
        or module is None
        or module.course_id != course.id
        or lesson.status != "published"
        or lesson.preview_policy != "public"
    ):
        raise VavError("COURSE_PREVIEW_NOT_FOUND", "Preview lesson was not found.", status_code=404)
    localization = await session.scalar(
        select(CourseLessonLocalization)
        .where(
            CourseLessonLocalization.lesson_id == lesson.id,
            CourseLessonLocalization.locale.in_((locale, course.default_locale)),
        )
        .order_by((CourseLessonLocalization.locale == locale).desc())
        .limit(1)
    )
    return success(
        {
            "id": str(lesson.id),
            "title": localization.title if localization else lesson.internal_name,
            "lesson_type": lesson.lesson_type,
            "content_blocks": localization.content_blocks if localization else [],
            "preview": True,
        },
        request_id_from_request(request),
    )


@router.post("/courses/{course_id}/enroll", status_code=201)
@router.post("/courses/{course_id}/enroll-free", status_code=201)
async def free_enroll(
    course_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    course = await course_or_404(session, course_id)
    value = await enrollment_service.free_enroll(session, user_id=principal.user.id, course=course)
    return success(enrollment_payload(value), request_id_from_request(request))


@router.get("/account/courses")
@router.get("/account/course-enrollments")
async def my_courses(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(CourseEnrollment)
                .where(CourseEnrollment.user_id == principal.user.id)
                .order_by(CourseEnrollment.enrolled_at.desc())
            )
        ).all()
    )
    items: list[dict[str, Any]] = []
    for enrollment in values:
        course = await session.get(Course, enrollment.course_id)
        if course:
            item = enrollment_payload(enrollment)
            item["course"] = await localized_course_payload(
                session, course, locale=principal.user.preferred_locale
            )
            items.append(item)
    return success({"items": items}, request_id_from_request(request))


@router.get("/account/courses/{enrollment_id}")
@router.get("/account/course-enrollments/{enrollment_id}")
async def learning_dashboard(
    enrollment_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    enrollment = await enrollment_service.own_active(
        session, enrollment_id=enrollment_id, user_id=principal.user.id
    )
    course = await course_or_404(session, enrollment.course_id)
    value = enrollment_payload(enrollment)
    value["course"] = await localized_course_payload(
        session,
        course,
        locale=principal.user.preferred_locale,
        include_curriculum=True,
    )
    version = await session.get(CourseVersion, enrollment.course_version_id)
    if version is not None:
        value["course"]["modules"] = version.curriculum_snapshot.get("modules", [])
        value["course"]["pinned_version_number"] = version.version_number
    progress = list(
        (
            await session.scalars(
                select(LessonProgress).where(LessonProgress.enrollment_id == enrollment.id)
            )
        ).all()
    )
    value["progress"] = [progress_payload(item) for item in progress]
    return success(value, request_id_from_request(request))


@router.get("/account/courses/{enrollment_id}/lessons/{lesson_id}")
async def learning_lesson(
    enrollment_id: UUID,
    lesson_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    enrollment = await enrollment_service.own_active(
        session, enrollment_id=enrollment_id, user_id=principal.user.id
    )
    lesson = await ensure_lesson_access(session, enrollment, lesson_id)
    localization = await session.scalar(
        select(CourseLessonLocalization)
        .where(
            CourseLessonLocalization.lesson_id == lesson.id,
            CourseLessonLocalization.locale.in_(
                (principal.user.preferred_locale, get_settings().course_default_locale)
            ),
        )
        .order_by((CourseLessonLocalization.locale == principal.user.preferred_locale).desc())
        .limit(1)
    )
    exercise = await session.scalar(
        select(CourseExercise).where(
            CourseExercise.lesson_id == lesson.id,
            CourseExercise.status == "published",
        )
    )
    return success(
        {
            "id": str(lesson.id),
            "title": localization.title if localization else lesson.internal_name,
            "lesson_type": lesson.lesson_type,
            "content_blocks": localization.content_blocks if localization else [],
            "completion_mode": lesson.completion_mode,
            "exercise_id": str(exercise.id) if exercise else None,
        },
        request_id_from_request(request),
    )


@router.post("/account/courses/{enrollment_id}/events")
async def record_learning_event(
    enrollment_id: UUID,
    payload: LearningEventRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    enrollment = await enrollment_service.own_active(
        session, enrollment_id=enrollment_id, user_id=principal.user.id
    )
    lesson = await ensure_lesson_access(session, enrollment, payload.lesson_id)
    value = await progress_service.record(
        session,
        enrollment=enrollment,
        lesson=lesson,
        event_type=payload.event_type,
        event_sequence=payload.event_sequence,
        idempotency_key=payload.idempotency_key,
        occurred_at=payload.occurred_at,
        payload=payload.payload,
    )
    await completion_service.evaluate(session, enrollment)
    return success(progress_payload(value), request_id_from_request(request))


@router.post("/account/courses/{enrollment_id}/lessons/{lesson_id}/playback")
async def start_playback(
    enrollment_id: UUID,
    lesson_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    enrollment = await enrollment_service.own_active(
        session, enrollment_id=enrollment_id, user_id=principal.user.id
    )
    lesson = await ensure_lesson_access(session, enrollment, lesson_id)
    resource = await session.get(LessonVideoResource, lesson_id)
    video = await session.get(CourseVideoAsset, resource.video_asset_id) if resource else None
    if video is None or video.processing_status != "ready":
        raise VavError("COURSE_VIDEO_UNAVAILABLE", "Course video is unavailable.", status_code=409)
    current = datetime.now(UTC)
    active = list(
        (
            await session.scalars(
                select(CoursePlaybackSession).where(
                    CoursePlaybackSession.user_id == principal.user.id,
                    CoursePlaybackSession.status == "active",
                    CoursePlaybackSession.expires_at > current,
                )
            )
        ).all()
    )
    settings = get_settings()
    if len(active) >= settings.course_video_max_concurrent_sessions:
        raise VavError(
            "PLAYBACK_SESSION_LIMIT",
            "The concurrent playback session limit was reached.",
            status_code=429,
        )
    playback = CoursePlaybackSession(
        user_id=principal.user.id,
        enrollment_id=enrollment.id,
        lesson_id=lesson.id,
        video_asset_id=video.id,
        access_token_hash="pending",
        status="active",
        started_at=current,
        expires_at=current + timedelta(minutes=settings.course_video_session_ttl_minutes),
    )
    session.add(playback)
    await session.flush()
    expires_at = int(time.time()) + settings.course_video_playback_url_ttl_seconds
    raw_token = issue_playback_token(str(playback.id), expires_at=expires_at)
    playback.access_token_hash = token_hash(raw_token)
    await session.commit()
    return success(
        {
            "session_id": str(playback.id),
            "playback_url": (f"/api/v1/learning/playback/{playback.id}/manifest?token={raw_token}"),
            "url_expires_at": datetime.fromtimestamp(expires_at, tz=UTC).isoformat(),
            "session_expires_at": playback.expires_at.isoformat(),
            "heartbeat_interval_seconds": settings.course_video_heartbeat_interval_seconds,
            "download_enabled": False,
        },
        request_id_from_request(request),
    )


@router.get("/learning/playback/{session_id}/manifest")
async def playback_manifest(
    session_id: UUID,
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    playback = await session.get(CoursePlaybackSession, session_id)
    if playback is None or token_hash(token) != playback.access_token_hash:
        raise VavError("PLAYBACK_TOKEN_INVALID", "Playback token is invalid.", status_code=401)
    verify_playback_token(token, session_id=str(session_id))
    video = await session.get(CourseVideoAsset, playback.video_asset_id)
    if video is None:
        raise VavError("COURSE_VIDEO_UNAVAILABLE", "Course video is unavailable.", status_code=404)
    manifest = await get_course_video_provider().create_playback_manifest(video)
    return success(
        {
            "provider": manifest.provider,
            "asset_reference": manifest.asset_reference,
            "duration_seconds": manifest.duration_seconds,
            "format": manifest.playback_type,
            "download_enabled": manifest.download_enabled,
        },
        request_id_from_request(request),
    )


@router.post("/account/playback/{session_id}/heartbeat")
async def playback_heartbeat(
    session_id: UUID,
    payload: HeartbeatRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    playback = await session.get(CoursePlaybackSession, session_id)
    if playback is None or playback.user_id != principal.user.id:
        raise VavError(
            "PLAYBACK_SESSION_NOT_FOUND", "Playback session was not found.", status_code=404
        )
    progress = await progress_service.heartbeat(
        session,
        playback=playback,
        position_seconds=payload.position_seconds,
        played_seconds=payload.played_seconds,
        sequence=payload.sequence,
        occurred_at=payload.occurred_at,
    )
    enrollment = await session.get(CourseEnrollment, playback.enrollment_id)
    if enrollment:
        await completion_service.evaluate(session, enrollment)
    return success(progress_payload(progress), request_id_from_request(request))


@router.post("/account/courses/{enrollment_id}/exercises/{exercise_id}/attempts")
async def start_attempt(
    enrollment_id: UUID,
    exercise_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    enrollment = await enrollment_service.own_active(
        session, enrollment_id=enrollment_id, user_id=principal.user.id
    )
    exercise = await exercise_or_404(session, exercise_id)
    await ensure_lesson_access(session, enrollment, exercise.lesson_id)
    attempt = await assessment_service.start(session, exercise=exercise, enrollment=enrollment)
    return success(
        {
            "id": str(attempt.id),
            "attempt_number": attempt.attempt_number,
            "status": attempt.status,
            "questions": attempt.question_snapshot,
        },
        request_id_from_request(request),
    )


@router.post("/account/exercise-attempts/{attempt_id}/submit")
async def submit_attempt(
    attempt_id: UUID,
    payload: AttemptSubmitRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    attempt = await session.get(ExerciseAttempt, attempt_id)
    if attempt is None or attempt.user_id != principal.user.id:
        raise VavError("EXERCISE_ATTEMPT_NOT_FOUND", "Attempt was not found.", status_code=404)
    value = await assessment_service.submit(session, attempt=attempt, responses=payload.responses)
    enrollment = await session.get(CourseEnrollment, attempt.enrollment_id)
    if enrollment:
        await completion_service.evaluate(session, enrollment)
    return success(
        {
            "id": str(value.id),
            "status": value.status,
            "score_basis_points": value.final_score_basis_points,
            "passed": value.passed,
        },
        request_id_from_request(request),
    )


@router.put("/account/exercise-attempts/{attempt_id}/draft")
async def save_attempt_draft(
    attempt_id: UUID,
    payload: AttemptSaveRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    attempt = await session.scalar(
        select(ExerciseAttempt)
        .where(ExerciseAttempt.id == attempt_id)
        .with_for_update()
    )
    if attempt is None or attempt.user_id != principal.user.id:
        raise VavError("EXERCISE_ATTEMPT_NOT_FOUND", "Attempt was not found.", status_code=404)
    if attempt.status != "in_progress":
        raise VavError("EXERCISE_ATTEMPT_FINAL", "Attempt is already final.", status_code=409)
    attempt.response_snapshot_encrypted = encrypt_sensitive(payload.responses)
    await session.commit()
    return success(
        {"id": str(attempt.id), "status": attempt.status, "saved": True},
        request_id_from_request(request),
    )


@router.get("/account/course-certificates")
@router.get("/account/certificates")
async def my_certificates(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(CourseCertificate)
                .where(CourseCertificate.user_id == principal.user.id)
                .order_by(CourseCertificate.issued_at.desc())
            )
        ).all()
    )
    return success(
        {"items": [certificate_payload(item) for item in values]},
        request_id_from_request(request),
    )


@router.get("/certificates/verify/{verification_token}")
async def verify_certificate(
    verification_token: str,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        select(CourseCertificate).where(
            CourseCertificate.verification_token_hash == token_hash(verification_token)
        )
    )
    if value is None:
        raise VavError("CERTIFICATE_NOT_FOUND", "Certificate was not found.", status_code=404)
    return success(certificate_payload(value, public=True), request_id_from_request(request))


@router.get("/admin/courses")
async def admin_courses(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list((await session.scalars(select(Course).order_by(Course.created_at.desc()))).all())
    return success(
        {
            "items": [
                await localized_course_payload(session, item, locale=item.default_locale)
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.get("/admin/course-instructors")
async def admin_course_instructors(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(CourseInstructor).order_by(
                    CourseInstructor.display_name, CourseInstructor.id
                )
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "instructor_code": item.instructor_code,
                    "display_name": item.display_name,
                    "status": item.status,
                    "linked_user_id": str(item.linked_user_id) if item.linked_user_id else None,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/course-instructors", status_code=201)
async def create_course_instructor(
    payload: InstructorCreateRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.linked_user_id and await session.get(User, payload.linked_user_id) is None:
        raise VavError("USER_NOT_FOUND", "User was not found.", status_code=404)
    value = CourseInstructor(**payload.model_dump())
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.get("/admin/courses/{course_id}")
async def admin_course_detail(
    course_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    course = await course_or_404(session, course_id)
    return success(
        await localized_course_payload(
            session,
            course,
            locale=course.default_locale,
            include_curriculum=True,
            public_curriculum_only=False,
        ),
        request_id_from_request(request),
    )


@router.patch("/admin/courses/{course_id}")
async def update_course(
    course_id: UUID,
    payload: CourseUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("courses.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    course = await course_or_404(session, course_id)
    if course.version != payload.expected_version:
        raise VavError(
            "COURSE_VERSION_CONFLICT",
            "Course changed since it was loaded.",
            status_code=409,
        )
    for field, value in payload.model_dump(
        exclude={"expected_version"}, exclude_unset=True
    ).items():
        setattr(course, field, value)
    course.updated_by = principal.user.id
    course.version += 1
    await session.commit()
    return success(
        await localized_course_payload(session, course, locale=course.default_locale),
        request_id_from_request(request),
    )


@router.post("/admin/courses/{course_id}/instructors", status_code=201)
async def assign_course_instructor(
    course_id: UUID,
    payload: InstructorAssignmentRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await course_or_404(session, course_id)
    if await session.get(CourseInstructor, payload.instructor_id) is None:
        raise VavError("COURSE_INSTRUCTOR_NOT_FOUND", "Instructor was not found.", status_code=404)
    key = {
        "course_id": course_id,
        "instructor_id": payload.instructor_id,
        "role": payload.role,
    }
    value = await session.get(CourseInstructorAssignment, key)
    if value is None:
        value = CourseInstructorAssignment(**key, sort_order=payload.sort_order)
        session.add(value)
    else:
        value.sort_order = payload.sort_order
    await session.commit()
    return success(
        {"course_id": str(course_id), "instructor_id": str(payload.instructor_id)},
        request_id_from_request(request),
    )


@router.delete("/admin/courses/{course_id}/instructors/{instructor_id}/{role}")
async def remove_course_instructor(
    course_id: UUID,
    instructor_id: UUID,
    role: str,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(
        CourseInstructorAssignment,
        {"course_id": course_id, "instructor_id": instructor_id, "role": role},
    )
    if value is None:
        raise VavError(
            "COURSE_INSTRUCTOR_NOT_FOUND",
            "Instructor assignment was not found.",
            status_code=404,
        )
    await session.delete(value)
    await session.commit()
    return success({"deleted": True}, request_id_from_request(request))


@router.post("/admin/courses", status_code=201)
async def create_course(
    payload: CourseCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("courses.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    policy = CourseCompletionPolicy(
        policy_code=f"{payload.course_code}-default-v1",
        policy_version=1,
        certificate_enabled=get_settings().course_certificate_enabled,
    )
    session.add(policy)
    await session.flush()
    course = Course(
        **payload.model_dump(),
        status="draft",
        completion_policy_id=policy.id,
        created_by=principal.user.id,
        updated_by=principal.user.id,
    )
    session.add(course)
    await session.commit()
    await session.refresh(course)
    return success(
        await localized_course_payload(session, course, locale=course.default_locale),
        request_id_from_request(request),
    )


@router.put("/admin/courses/{course_id}/localizations/{locale}")
async def upsert_course_localization(
    course_id: UUID,
    locale: str,
    payload: CourseLocalizationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("courses.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    course = await course_or_404(session, course_id)
    value = await session.scalar(
        select(CourseLocalization).where(
            CourseLocalization.course_id == course.id, CourseLocalization.locale == locale
        )
    )
    data = payload.model_dump()
    data["locale"] = locale
    if value is None:
        value = CourseLocalization(course_id=course.id, **data)
        session.add(value)
    else:
        for key, item in data.items():
            setattr(value, key, item)
    course.updated_by = principal.user.id
    course.version += 1
    await session.commit()
    return success({"id": str(value.id), "locale": locale}, request_id_from_request(request))


@router.post("/admin/courses/{course_id}/modules", status_code=201)
async def create_module(
    course_id: UUID,
    payload: ModuleCreateRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.structure.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await course_or_404(session, course_id)
    data = payload.model_dump(exclude={"title", "locale"})
    value = CourseModule(course_id=course_id, **data)
    session.add(value)
    await session.flush()
    session.add(
        CourseModuleLocalization(module_id=value.id, locale=payload.locale, title=payload.title)
    )
    await session.commit()
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.post("/admin/course-modules/{module_id}/lessons", status_code=201)
async def create_lesson(
    module_id: UUID,
    payload: LessonCreateRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.structure.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    module = await session.get(CourseModule, module_id)
    if module is None:
        raise VavError("COURSE_MODULE_NOT_FOUND", "Course module was not found.", status_code=404)
    data = payload.model_dump(exclude={"title", "locale", "content_blocks"})
    value = CourseLesson(module_id=module_id, completion_threshold={}, **data)
    session.add(value)
    await session.flush()
    session.add(
        CourseLessonLocalization(
            lesson_id=value.id,
            locale=payload.locale,
            title=payload.title,
            content_blocks=payload.content_blocks,
        )
    )
    await session.commit()
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.post("/admin/course-lessons/{lesson_id}/prerequisites", status_code=201)
async def create_prerequisite(
    lesson_id: UUID,
    payload: PrerequisiteCreateRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.structure.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    lesson = await session.get(CourseLesson, lesson_id)
    prerequisite = await session.get(CourseLesson, payload.prerequisite_lesson_id)
    if lesson is None or prerequisite is None:
        raise VavError("COURSE_LESSON_NOT_FOUND", "Lesson was not found.", status_code=404)
    lesson_module = await session.get(CourseModule, lesson.module_id)
    prerequisite_module = await session.get(CourseModule, prerequisite.module_id)
    if (
        lesson_id == prerequisite.id
        or lesson_module is None
        or prerequisite_module is None
        or lesson_module.course_id != prerequisite_module.course_id
    ):
        raise VavError(
            "COURSE_PREREQUISITE_INVALID",
            "Prerequisite lessons must be distinct lessons in the same course.",
            status_code=422,
        )
    value = await session.get(
        LessonPrerequisite,
        {"lesson_id": lesson_id, "prerequisite_lesson_id": prerequisite.id},
    )
    if value is None:
        value = LessonPrerequisite(lesson_id=lesson_id, **payload.model_dump())
        session.add(value)
    else:
        value.required_completion = payload.required_completion
        value.minimum_score_basis_points = payload.minimum_score_basis_points
    await session.commit()
    return success(
        {"lesson_id": str(lesson_id), "prerequisite_lesson_id": str(prerequisite.id)},
        request_id_from_request(request),
    )


@router.put("/admin/course-lessons/{lesson_id}/video")
async def attach_video(
    lesson_id: UUID,
    payload: VideoAttachRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("courses.video.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    lesson = await session.get(CourseLesson, lesson_id)
    if lesson is None or lesson.lesson_type != "video":
        raise VavError(
            "COURSE_VIDEO_LESSON_REQUIRED", "A video lesson is required.", status_code=422
        )
    video = CourseVideoAsset(
        provider=get_settings().course_video_provider,
        provider_environment=get_settings().environment,
        provider_video_id=payload.provider_video_id,
        private_reference_encrypted=encrypt_sensitive({"value": payload.private_reference}),
        processing_status=payload.processing_status,
        duration_seconds=payload.duration_seconds,
        playback_format="hls",
        created_by=principal.user.id,
    )
    session.add(video)
    await session.flush()
    existing = await session.get(LessonVideoResource, lesson.id)
    if existing is None:
        existing = LessonVideoResource(
            lesson_id=lesson.id,
            video_asset_id=video.id,
            required_watch_basis_points=payload.required_watch_basis_points,
        )
        session.add(existing)
    else:
        existing.video_asset_id = video.id
        existing.required_watch_basis_points = payload.required_watch_basis_points
    await session.commit()
    return success({"video_asset_id": str(video.id)}, request_id_from_request(request))


@router.post("/admin/courses/{course_id}/catalog-mappings")
@router.put("/admin/courses/{course_id}/sku-mapping")
async def map_course_sku(
    course_id: UUID,
    payload: SkuMappingRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.catalog.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    course = await course_or_404(session, course_id)
    sku = await session.get(ProductSku, payload.catalog_sku_id)
    if sku is None:
        raise VavError("CATALOG_SKU_NOT_FOUND", "Catalog SKU was not found.", status_code=404)
    product = await session.get(Product, sku.product_id)
    if (
        product is None
        or product.product_type not in {"course", "course_bundle"}
        or product.fulfillment_type != "digital_access"
    ):
        raise VavError(
            "COURSE_CATALOG_MAPPING_INVALID",
            "Course mappings require a digital-access course or course-bundle SKU.",
            status_code=422,
        )
    value = await session.scalar(
        select(CourseSkuMapping).where(
            CourseSkuMapping.course_id == course.id,
            CourseSkuMapping.catalog_sku_id == sku.id,
        )
    )
    if value is None:
        value = CourseSkuMapping(course_id=course.id, **payload.model_dump())
        session.add(value)
    else:
        value.access_duration_days = payload.access_duration_days
    course.catalog_product_id = sku.product_id
    course.primary_catalog_sku_id = sku.id
    await session.commit()
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.get("/admin/courses/{course_id}/catalog-mappings")
async def course_catalog_mappings(
    course_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.catalog.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await course_or_404(session, course_id)
    values = list(
        (
            await session.scalars(
                select(CourseSkuMapping)
                .where(CourseSkuMapping.course_id == course_id)
                .order_by(CourseSkuMapping.created_at, CourseSkuMapping.id)
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "catalog_sku_id": str(item.catalog_sku_id),
                    "access_duration_days": item.access_duration_days,
                    "access_start_policy": item.access_start_policy,
                    "course_version_policy": item.course_version_policy,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.delete("/admin/courses/{course_id}/catalog-mappings/{mapping_id}")
async def delete_course_catalog_mapping(
    course_id: UUID,
    mapping_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.catalog.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        select(CourseSkuMapping).where(
            CourseSkuMapping.id == mapping_id,
            CourseSkuMapping.course_id == course_id,
        )
    )
    if value is None:
        raise VavError("COURSE_SKU_MAPPING_NOT_FOUND", "Mapping was not found.", status_code=404)
    await session.delete(value)
    await session.commit()
    return success({"deleted": True}, request_id_from_request(request))


@router.post("/admin/courses/{course_id}/transition")
async def transition_course(
    course_id: UUID,
    payload: CourseTransitionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    permission = {
        "draft": "courses.update",
        "in_review": "courses.review",
        "scheduled": "courses.publish",
        "published": "courses.publish",
        "enrollment_closed": "courses.update",
        "unpublished": "courses.unpublish",
        "archived": "courses.archive",
    }[payload.target_status]
    principal.require(permission)
    course = await course_or_404(session, course_id)
    version = await publication_service.transition(
        session,
        course,
        target=payload.target_status,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    return success(
        {
            "id": str(course.id),
            "status": course.status,
            "course_version_id": str(version.id) if version else None,
        },
        request_id_from_request(request),
    )


@router.post("/admin/courses/{course_id}/submit-review")
@router.post("/admin/courses/{course_id}/approve")
@router.post("/admin/courses/{course_id}/publish")
@router.post("/admin/courses/{course_id}/schedule")
@router.post("/admin/courses/{course_id}/close-enrollment")
@router.post("/admin/courses/{course_id}/unpublish")
@router.post("/admin/courses/{course_id}/archive")
async def transition_course_action(
    course_id: UUID,
    payload: EnrollmentActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    action = request.url.path.rsplit("/", 1)[-1]
    targets = {
        "submit-review": "in_review",
        "approve": "published",
        "publish": "published",
        "schedule": "scheduled",
        "close-enrollment": "enrollment_closed",
        "unpublish": "unpublished",
        "archive": "archived",
    }
    target = targets.get(action)
    if target is None:
        raise VavError("COURSE_ACTION_INVALID", "Course action is invalid.", status_code=404)
    permission = {
        "in_review": "courses.review",
        "scheduled": "courses.publish",
        "published": "courses.publish",
        "enrollment_closed": "courses.update",
        "unpublished": "courses.unpublish",
        "archived": "courses.archive",
    }[target]
    principal.require(permission)
    course = await course_or_404(session, course_id)
    version = await publication_service.transition(
        session,
        course,
        target=target,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    return success(
        {
            "id": str(course.id),
            "status": course.status,
            "course_version_id": str(version.id) if version else None,
        },
        request_id_from_request(request),
    )


@router.post("/admin/course-exercises", status_code=201)
async def create_exercise(
    payload: ExerciseCreateRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.exercises.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    lesson = await session.get(CourseLesson, payload.lesson_id)
    if lesson is None:
        raise VavError("COURSE_LESSON_NOT_FOUND", "Lesson was not found.", status_code=404)
    value = CourseExercise(**payload.model_dump(), status="published")
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.post("/admin/course-exercises/{exercise_id}/questions", status_code=201)
async def create_question(
    exercise_id: UUID,
    payload: QuestionCreateRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.exercises.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await exercise_or_404(session, exercise_id)
    value = ExerciseQuestion(
        exercise_id=exercise_id,
        question_type=payload.question_type,
        sort_order=payload.sort_order,
        points=payload.points,
        required=payload.required,
        question_schema={},
        answer_key_encrypted=(
            encrypt_sensitive(payload.answer_key) if payload.answer_key is not None else None
        ),
        grading_schema={},
    )
    session.add(value)
    await session.flush()
    session.add(
        ExerciseQuestionLocalization(
            question_id=value.id,
            locale=payload.locale,
            prompt_blocks=payload.prompt_blocks,
            options=payload.options,
        )
    )
    await session.commit()
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.post("/admin/exercise-attempts/{attempt_id}/grade")
async def manual_grade(
    attempt_id: UUID,
    payload: ManualGradeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("courses.exercises.grade")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    attempt = await session.get(ExerciseAttempt, attempt_id)
    if attempt is None:
        raise VavError("EXERCISE_ATTEMPT_NOT_FOUND", "Attempt was not found.", status_code=404)
    exercise = await session.get(CourseExercise, attempt.exercise_id)
    attempt.manual_score_basis_points = payload.score_basis_points
    attempt.final_score_basis_points = payload.score_basis_points
    attempt.passed = payload.score_basis_points >= (
        exercise.passing_score_basis_points or 0 if exercise else 0
    )
    attempt.status = "graded"
    attempt.graded_at = datetime.now(UTC)
    attempt.graded_by = principal.user.id
    attempt.grader_feedback_encrypted = (
        encrypt_sensitive({"feedback": payload.feedback}) if payload.feedback else None
    )
    if attempt.passed:
        from vav.modules.courses.service import complete_assessment_lesson

        await complete_assessment_lesson(session, attempt)
    await session.commit()
    return success(
        {"id": str(attempt.id), "passed": attempt.passed},
        request_id_from_request(request),
    )


@router.post("/admin/course-enrollments/{enrollment_id}/{action}")
async def enrollment_action(
    enrollment_id: UUID,
    action: str,
    payload: EnrollmentActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_admin_principal),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if action not in {"suspend", "restore", "revoke"}:
        raise VavError(
            "COURSE_ENROLLMENT_ACTION_INVALID", "Enrollment action is invalid.", status_code=422
        )
    principal.require(
        "courses.enrollments.revoke" if action == "revoke" else "courses.enrollments.suspend"
    )
    value = await session.get(CourseEnrollment, enrollment_id)
    if value is None:
        raise VavError("COURSE_ENROLLMENT_NOT_FOUND", "Enrollment was not found.", status_code=404)
    value.status = {"suspend": "suspended", "restore": "active", "revoke": "revoked"}[action]
    value.suspended_at = datetime.now(UTC) if action == "suspend" else value.suspended_at
    value.revoked_at = datetime.now(UTC) if action == "revoke" else value.revoked_at
    value.version += 1
    record_security_event(
        session,
        event_type=f"course.enrollment.{action}",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="course_enrollment",
        target_id=value.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(enrollment_payload(value), request_id_from_request(request))


@router.get("/admin/course-enrollments")
async def admin_enrollments(
    request: Request,
    course_id: UUID | None = None,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.enrollments.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    query = select(CourseEnrollment)
    if course_id is not None:
        query = query.where(CourseEnrollment.course_id == course_id)
    values = list(
        (
            await session.scalars(
                query.order_by(CourseEnrollment.enrolled_at.desc(), CourseEnrollment.id)
            )
        ).all()
    )
    return success(
        {"items": [enrollment_payload(item) for item in values]},
        request_id_from_request(request),
    )


@router.post("/admin/courses/{course_id}/enrollments", status_code=201)
async def grant_enrollment(
    course_id: UUID,
    payload: AdminEnrollmentGrantRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("courses.enrollments.grant")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    course = await course_or_404(session, course_id)
    user = await session.get(User, payload.user_id)
    if user is None:
        raise VavError("USER_NOT_FOUND", "User was not found.", status_code=404)
    value = await session.scalar(
        select(CourseEnrollment).where(
            CourseEnrollment.user_id == user.id,
            CourseEnrollment.course_id == course.id,
            CourseEnrollment.entitlement_id.is_(None),
            CourseEnrollment.status != "revoked",
        )
    )
    if value is None:
        version = await enrollment_service.latest_version(session, course.id)
        started = datetime.now(UTC)
        value = CourseEnrollment(
            user_id=user.id,
            course_id=course.id,
            course_version_id=version.id,
            source_type="admin_grant",
            status="active",
            access_starts_at=started,
            access_expires_at=(
                started + timedelta(days=payload.access_duration_days)
                if payload.access_duration_days
                else None
            ),
            enrolled_at=started,
        )
        session.add(value)
        await session.flush()
    record_security_event(
        session,
        event_type="course.enrollment.granted",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="course_enrollment",
        target_id=value.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(enrollment_payload(value), request_id_from_request(request))


@router.post("/admin/course-progress/{progress_id}/reset")
async def reset_progress(
    progress_id: UUID,
    payload: ProgressResetRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("courses.progress.reset")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(LessonProgress, progress_id)
    if value is None:
        raise VavError("COURSE_PROGRESS_NOT_FOUND", "Progress was not found.", status_code=404)
    before = progress_payload(value)
    value.status = "not_started"
    value.progress_basis_points = 0
    value.last_position_seconds = None
    value.maximum_position_seconds = None
    value.started_at = None
    value.last_accessed_at = None
    value.completed_at = None
    value.completion_source = "admin_reset"
    value.completion_evidence = {}
    value.version += 1
    record_security_event(
        session,
        event_type="course.progress.reset",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="lesson_progress",
        target_id=value.id,
        reason=payload.reason,
        before_state=before,
        after_state=progress_payload(value),
    )
    await session.commit()
    return success(progress_payload(value), request_id_from_request(request))


@router.post("/admin/course-certificates/{certificate_id}/revoke")
async def revoke_certificate(
    certificate_id: UUID,
    payload: EnrollmentActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("courses.certificates.revoke")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(CourseCertificate, certificate_id)
    if value is None:
        raise VavError("CERTIFICATE_NOT_FOUND", "Certificate was not found.", status_code=404)
    value.status = "revoked"
    value.revoked_at = datetime.now(UTC)
    value.revoked_by = principal.user.id
    value.revoke_reason = payload.reason
    await session.commit()
    return success(certificate_payload(value), request_id_from_request(request))


@router.get("/admin/course-certificates")
async def admin_certificates(
    request: Request,
    course_id: UUID | None = None,
    _: AuthenticatedPrincipal = Depends(require_permission("courses.certificates.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    query = select(CourseCertificate)
    if course_id is not None:
        query = query.where(CourseCertificate.course_id == course_id)
    values = list(
        (
            await session.scalars(
                query.order_by(CourseCertificate.issued_at.desc(), CourseCertificate.id)
            )
        ).all()
    )
    return success(
        {
            "items": [
                {"id": str(item.id), **certificate_payload(item)}
                for item in values
            ]
        },
        request_id_from_request(request),
    )
