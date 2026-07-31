from __future__ import annotations

import secrets
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.catalog import Price, Product, ProductSku
from vav.models.commerce import Entitlement
from vav.models.courses import (
    Course,
    CourseCertificate,
    CourseCompletionPolicy,
    CourseCompletionRecord,
    CourseEnrollment,
    CourseExercise,
    CourseInboxEvent,
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
    ExerciseAttempt,
    ExerciseQuestion,
    ExerciseQuestionLocalization,
    LearningEvent,
    LessonPrerequisite,
    LessonProgress,
    LessonVideoResource,
)
from vav.models.identity import User
from vav.models.system import OutboxEvent
from vav.modules.courses.crypto import (
    decrypt_sensitive,
    encrypt_sensitive,
    token_hash,
)
from vav.modules.courses.domain import (
    CourseStatus,
    assert_acyclic_prerequisites,
    ensure_course_transition,
    mask_public_name,
    monotonic_progress,
    score_response,
)
from vav.modules.identity.audit import record_security_event


def now() -> datetime:
    return datetime.now(UTC)


async def transaction_lock(session: AsyncSession, key: str) -> None:
    """Serialize course writes that must remain idempotent across workers."""
    await session.scalar(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


def version_lesson_ids(version: CourseVersion) -> set[UUID]:
    """Return the immutable lesson set pinned into a published course version."""
    result: set[UUID] = set()
    modules = version.curriculum_snapshot.get("modules", [])
    if not isinstance(modules, list):
        return result
    for module in modules:
        if not isinstance(module, dict) or not isinstance(module.get("lessons"), list):
            continue
        for lesson in module["lessons"]:
            if isinstance(lesson, str):
                with suppress(ValueError):
                    result.add(UUID(lesson))
                continue
            if not isinstance(lesson, dict):
                continue
            try:
                result.add(UUID(str(lesson["id"])))
            except (KeyError, TypeError, ValueError):
                continue
    return result


async def localized_course_payload(
    session: AsyncSession,
    course: Course,
    *,
    locale: str,
    include_curriculum: bool = False,
    public_curriculum_only: bool = True,
) -> dict[str, Any]:
    localization = await session.scalar(
        select(CourseLocalization)
        .where(
            CourseLocalization.course_id == course.id,
            CourseLocalization.locale.in_((locale, course.default_locale)),
        )
        .order_by((CourseLocalization.locale == locale).desc())
        .limit(1)
    )
    mapping = await session.scalar(
        select(CourseSkuMapping).where(CourseSkuMapping.course_id == course.id).limit(1)
    )
    current = now()
    prices = (
        list(
            (
                await session.scalars(
                    select(Price)
                    .where(
                        Price.sku_id == mapping.catalog_sku_id,
                        Price.status == "active",
                        Price.valid_from <= current,
                        or_(Price.valid_until.is_(None), Price.valid_until > current),
                    )
                    .order_by(Price.currency_code, Price.unit_amount_minor)
                )
            ).all()
        )
        if mapping
        else []
    )
    value: dict[str, Any] = {
        "id": str(course.id),
        "course_code": course.course_code,
        "course_type": course.course_type,
        "status": course.status,
        "visibility": course.visibility,
        "title": localization.title if localization else course.internal_name,
        "slug": localization.slug if localization else course.course_code,
        "subtitle": localization.subtitle if localization else None,
        "summary": localization.summary if localization else None,
        "description_blocks": localization.description_blocks if localization else [],
        "learning_outcomes": localization.learning_outcomes if localization else [],
        "target_audience": localization.target_audience if localization else [],
        "prerequisites": localization.prerequisites if localization else [],
        "instructor_summary": localization.instructor_summary if localization else None,
        "difficulty_level": course.difficulty_level,
        "estimated_duration_minutes": course.estimated_duration_minutes,
        "featured": course.featured,
        "free_enrollment": course.free_access_policy == "free_enrollment",
        "catalog_product_id": str(course.catalog_product_id) if course.catalog_product_id else None,
        "catalog_sku_id": str(mapping.catalog_sku_id) if mapping else None,
        "access_duration_days": mapping.access_duration_days if mapping else None,
        "prices": [
            {
                "currency": price.currency_code,
                "unit_amount_minor": price.unit_amount_minor,
                "billing_type": price.billing_type,
            }
            for price in prices
        ],
    }
    assignments = list(
        (
            await session.scalars(
                select(CourseInstructorAssignment)
                .where(CourseInstructorAssignment.course_id == course.id)
                .order_by(
                    CourseInstructorAssignment.sort_order,
                    CourseInstructorAssignment.instructor_id,
                )
            )
        ).all()
    )
    instructors: list[dict[str, Any]] = []
    for assignment in assignments:
        instructor = await session.get(CourseInstructor, assignment.instructor_id)
        if instructor is not None and instructor.status == "active":
            instructors.append(
                {
                    "id": str(instructor.id),
                    "display_name": instructor.display_name,
                    "role": assignment.role,
                }
            )
    value["instructors"] = instructors
    if include_curriculum:
        value["modules"] = await curriculum_payload(
            session,
            course.id,
            locale=locale,
            public_only=public_curriculum_only,
        )
    return value


async def curriculum_payload(
    session: AsyncSession,
    course_id: UUID,
    *,
    locale: str,
    public_only: bool = True,
) -> list[dict[str, Any]]:
    module_query = select(CourseModule).where(CourseModule.course_id == course_id)
    if public_only:
        module_query = module_query.where(CourseModule.status == "published")
    modules = list(
        (
            await session.scalars(module_query.order_by(CourseModule.sort_order, CourseModule.id))
        ).all()
    )
    result: list[dict[str, Any]] = []
    for module in modules:
        localization = await session.scalar(
            select(CourseModuleLocalization)
            .where(
                CourseModuleLocalization.module_id == module.id,
                CourseModuleLocalization.locale == locale,
            )
            .limit(1)
        )
        lesson_query = select(CourseLesson).where(CourseLesson.module_id == module.id)
        if public_only:
            lesson_query = lesson_query.where(CourseLesson.status == "published")
        lessons = list(
            (
                await session.scalars(
                    lesson_query.order_by(CourseLesson.sort_order, CourseLesson.id)
                )
            ).all()
        )
        lesson_values: list[dict[str, Any]] = []
        for lesson in lessons:
            lesson_l10n = await session.scalar(
                select(CourseLessonLocalization)
                .where(
                    CourseLessonLocalization.lesson_id == lesson.id,
                    CourseLessonLocalization.locale == locale,
                )
                .limit(1)
            )
            exercise = await session.scalar(
                select(CourseExercise).where(
                    CourseExercise.lesson_id == lesson.id,
                    CourseExercise.status == "published",
                )
            )
            prerequisite_rows = list(
                (
                    await session.scalars(
                        select(LessonPrerequisite).where(LessonPrerequisite.lesson_id == lesson.id)
                    )
                ).all()
            )
            lesson_values.append(
                {
                    "id": str(lesson.id),
                    "lesson_code": lesson.lesson_code,
                    "title": lesson_l10n.title if lesson_l10n else lesson.internal_name,
                    "summary": lesson_l10n.summary if lesson_l10n else None,
                    "lesson_type": lesson.lesson_type,
                    "required": lesson.required,
                    "preview_policy": lesson.preview_policy,
                    "estimated_duration_minutes": lesson.estimated_duration_minutes,
                    "release_offset_days": lesson.release_offset_days,
                    "release_at": lesson.release_at.isoformat() if lesson.release_at else None,
                    "completion_mode": lesson.completion_mode,
                    "exercise_id": str(exercise.id) if exercise else None,
                    "prerequisites": [
                        {
                            "lesson_id": str(item.prerequisite_lesson_id),
                            "required_completion": item.required_completion,
                            "minimum_score_basis_points": item.minimum_score_basis_points,
                        }
                        for item in prerequisite_rows
                    ],
                    "content_blocks": (
                        lesson_l10n.content_blocks
                        if lesson_l10n
                        and lesson.lesson_type == "rich_text"
                        and (not public_only or lesson.preview_policy == "public")
                        else []
                    ),
                }
            )
        result.append(
            {
                "id": str(module.id),
                "module_code": module.module_code,
                "title": localization.title if localization else module.internal_name,
                "required": module.required,
                "lessons": lesson_values,
            }
        )
    return result


class PublicationService:
    async def validate(self, session: AsyncSession, course: Course) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        localization = await session.scalar(
            select(CourseLocalization).where(
                CourseLocalization.course_id == course.id,
                CourseLocalization.locale == course.default_locale,
                CourseLocalization.translation_status == "ready",
            )
        )
        if localization is None:
            errors.append(
                {"field": "localization", "message": "Default localization is not ready."}
            )
        instructor = await session.scalar(
            select(CourseInstructor)
            .join(
                CourseInstructorAssignment,
                CourseInstructorAssignment.instructor_id == CourseInstructor.id,
            )
            .where(
                CourseInstructorAssignment.course_id == course.id,
                CourseInstructor.status == "active",
            )
            .limit(1)
        )
        if instructor is None:
            errors.append({"field": "instructors", "message": "An active instructor is required."})
        modules = list(
            (
                await session.scalars(
                    select(CourseModule).where(
                        CourseModule.course_id == course.id,
                        CourseModule.status == "published",
                    )
                )
            ).all()
        )
        if not modules:
            errors.append(
                {"field": "modules", "message": "At least one published module is required."}
            )
        module_ids = [item.id for item in modules]
        lessons = (
            list(
                (
                    await session.scalars(
                        select(CourseLesson).where(
                            CourseLesson.module_id.in_(module_ids),
                            CourseLesson.status == "published",
                        )
                    )
                ).all()
            )
            if module_ids
            else []
        )
        if not lessons:
            errors.append(
                {"field": "lessons", "message": "At least one published lesson is required."}
            )
        lesson_ids = [item.id for item in lessons]
        edges = (
            list(
                (
                    await session.execute(
                        select(
                            LessonPrerequisite.lesson_id,
                            LessonPrerequisite.prerequisite_lesson_id,
                        ).where(LessonPrerequisite.lesson_id.in_(lesson_ids))
                    )
                ).all()
            )
            if lesson_ids
            else []
        )
        try:
            assert_acyclic_prerequisites([(row[0], row[1]) for row in edges])
        except VavError as error:
            errors.append({"field": "prerequisites", "message": error.message})
        for lesson in lessons:
            if lesson.lesson_type == "video":
                resource = await session.get(LessonVideoResource, lesson.id)
                if resource is None:
                    errors.append(
                        {"field": f"lesson:{lesson.id}", "message": "Video resource is missing."}
                    )
                elif resource:
                    from vav.models.courses import CourseVideoAsset

                    video = await session.get(CourseVideoAsset, resource.video_asset_id)
                    if video is None or video.processing_status != "ready":
                        errors.append(
                            {"field": f"lesson:{lesson.id}", "message": "Video is not ready."}
                        )
            if lesson.lesson_type in {"exercise", "assignment"}:
                exercise = await session.scalar(
                    select(CourseExercise).where(
                        CourseExercise.lesson_id == lesson.id,
                        CourseExercise.status == "published",
                    )
                )
                if exercise is None:
                    errors.append(
                        {"field": f"lesson:{lesson.id}", "message": "Exercise is not published."}
                    )
                elif (
                    await session.scalar(
                        select(func.count())
                        .select_from(ExerciseQuestion)
                        .where(ExerciseQuestion.exercise_id == exercise.id)
                    )
                    == 0
                ):
                    errors.append(
                        {"field": f"lesson:{lesson.id}", "message": "Exercise has no questions."}
                    )
                else:
                    questions = list(
                        (
                            await session.scalars(
                                select(ExerciseQuestion).where(
                                    ExerciseQuestion.exercise_id == exercise.id
                                )
                            )
                        ).all()
                    )
                    if exercise.grading_mode in {"automatic", "hybrid"} and any(
                        question.question_type in {"single_choice", "multiple_choice", "true_false"}
                        and question.answer_key_encrypted is None
                        for question in questions
                    ):
                        errors.append(
                            {
                                "field": f"lesson:{lesson.id}",
                                "message": "Automatically graded questions require answer keys.",
                            }
                        )
        if course.completion_policy_id is None:
            errors.append(
                {"field": "completion_policy", "message": "Completion policy is required."}
            )
        if course.free_access_policy != "free_enrollment":
            mapping = await session.scalar(
                select(CourseSkuMapping).where(CourseSkuMapping.course_id == course.id)
            )
            sku = await session.get(ProductSku, mapping.catalog_sku_id) if mapping else None
            product = await session.get(Product, sku.product_id) if sku else None
            if (
                mapping is None
                or sku is None
                or sku.status != "active"
                or product is None
                or product.product_type not in {"course", "course_bundle"}
                or product.fulfillment_type != "digital_access"
            ):
                errors.append(
                    {"field": "catalog", "message": "An active Catalog SKU mapping is required."}
                )
        return errors

    async def snapshot(
        self, session: AsyncSession, course: Course, *, actor_id: UUID, reason: str
    ) -> CourseVersion:
        errors = await self.validate(session, course)
        if errors:
            raise VavError(
                "COURSE_PUBLICATION_INVALID",
                "Course is not ready to publish.",
                status_code=422,
                details=errors,
            )
        latest = (
            await session.scalar(
                select(func.max(CourseVersion.version_number)).where(
                    CourseVersion.course_id == course.id
                )
            )
            or 0
        )
        snapshot = {
            "schema_version": 1,
            "course_id": str(course.id),
            "course_code": course.course_code,
            "completion_policy_id": str(course.completion_policy_id),
            "modules": await curriculum_payload(
                session, course.id, locale=course.default_locale, public_only=True
            ),
        }
        version = CourseVersion(
            course_id=course.id,
            version_number=latest + 1,
            curriculum_snapshot=snapshot,
            change_summary=reason,
            created_by=actor_id,
            published_at=now(),
        )
        session.add(version)
        await session.flush()
        return version

    async def transition(
        self,
        session: AsyncSession,
        course: Course,
        *,
        target: str,
        actor_id: UUID,
        reason: str,
    ) -> CourseVersion | None:
        ensure_course_transition(course.status, target)
        version = None
        if target == CourseStatus.PUBLISHED:
            version = await self.snapshot(session, course, actor_id=actor_id, reason=reason)
        before = course.status
        course.status = target
        course.updated_by = actor_id
        course.version += 1
        record_security_event(
            session,
            event_type=f"course.{target}",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="course",
            target_id=course.id,
            reason=reason,
            before_state={"status": before},
            after_state={
                "status": target,
                "course_version_id": str(version.id) if version else None,
            },
        )
        session.add(
            OutboxEvent(
                topic=f"course.{target}",
                aggregate_type="course",
                aggregate_id=str(course.id),
                payload={"course_id": str(course.id), "version": course.version},
            )
        )
        await session.commit()
        return version


class EnrollmentService:
    async def latest_version(self, session: AsyncSession, course_id: UUID) -> CourseVersion:
        value = await session.scalar(
            select(CourseVersion)
            .where(CourseVersion.course_id == course_id, CourseVersion.published_at.is_not(None))
            .order_by(CourseVersion.version_number.desc())
            .limit(1)
        )
        if value is None:
            raise VavError(
                "COURSE_VERSION_UNAVAILABLE",
                "A published course version is required.",
                status_code=409,
            )
        return value

    async def free_enroll(
        self, session: AsyncSession, *, user_id: UUID, course: Course
    ) -> CourseEnrollment:
        settings = get_settings()
        if (
            not settings.course_allow_free_enrollment
            or course.free_access_policy != "free_enrollment"
            or course.status != CourseStatus.PUBLISHED
        ):
            raise VavError(
                "FREE_ENROLLMENT_NOT_ALLOWED",
                "This course does not allow free enrollment.",
                status_code=409,
            )
        existing = await session.scalar(
            select(CourseEnrollment).where(
                CourseEnrollment.user_id == user_id,
                CourseEnrollment.course_id == course.id,
                CourseEnrollment.entitlement_id.is_(None),
                CourseEnrollment.status != "revoked",
            )
        )
        if existing:
            return existing
        version = await self.latest_version(session, course.id)
        enrollment = CourseEnrollment(
            user_id=user_id,
            course_id=course.id,
            course_version_id=version.id,
            source_type="free_enrollment",
            status="active",
            access_starts_at=now(),
            enrolled_at=now(),
        )
        session.add(enrollment)
        await session.flush()
        record_security_event(
            session,
            event_type="course.enrollment.created",
            actor_type="user",
            actor_user_id=user_id,
            target_type="course_enrollment",
            target_id=enrollment.id,
            metadata={"source": "free_enrollment", "course_id": str(course.id)},
        )
        await session.commit()
        return enrollment

    async def project_entitlement(
        self, session: AsyncSession, entitlement: Entitlement
    ) -> list[CourseEnrollment]:
        if entitlement.entitlement_type != "course_access":
            return []
        source_event_id = uuid5(
            NAMESPACE_URL,
            f"entitlement:{entitlement.id}:activated:v{entitlement.version}",
        )
        inbox = await session.scalar(
            select(CourseInboxEvent).where(CourseInboxEvent.source_event_id == source_event_id)
        )
        if inbox is not None and inbox.processing_status == "processed":
            return list(
                (
                    await session.scalars(
                        select(CourseEnrollment).where(
                            CourseEnrollment.entitlement_id == entitlement.id
                        )
                    )
                ).all()
            )
        if inbox is None:
            inbox = CourseInboxEvent(
                source_event_id=source_event_id,
                event_type="entitlement.activated",
                processing_status="processing",
            )
            session.add(inbox)
            await session.flush()
        snapshot = entitlement.configuration_snapshot
        raw_items: list[Any]
        included_courses = snapshot.get("included_courses")
        if isinstance(included_courses, list):
            raw_items = list(included_courses)
        elif entitlement.resource_id:
            raw_items = [entitlement.resource_id]
        elif snapshot.get("course_id"):
            raw_items = [snapshot["course_id"]]
        else:
            raw_items = []
        created: list[CourseEnrollment] = []
        for raw_item in raw_items:
            item = raw_item if isinstance(raw_item, dict) else {"course_id": raw_item}
            try:
                course_id = UUID(str(item["course_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            course = await session.get(Course, course_id)
            if course is None:
                continue
            existing = await session.scalar(
                select(CourseEnrollment).where(
                    CourseEnrollment.user_id == entitlement.user_id,
                    CourseEnrollment.course_id == course.id,
                    CourseEnrollment.entitlement_id == entitlement.id,
                )
            )
            if existing:
                created.append(existing)
                continue
            requested_version = item.get("course_version")
            version = (
                await session.scalar(
                    select(CourseVersion).where(
                        CourseVersion.course_id == course.id,
                        CourseVersion.version_number == int(str(requested_version)),
                        CourseVersion.published_at.is_not(None),
                    )
                )
                if requested_version is not None
                else await self.latest_version(session, course.id)
            )
            if version is None:
                raise VavError(
                    "COURSE_BUNDLE_VERSION_UNAVAILABLE",
                    "A snapshotted bundle course version is unavailable.",
                    status_code=409,
                )
            duration = item.get("access_duration_days")
            access_expires_at = entitlement.expires_at
            if duration is not None:
                item_expiry = (entitlement.starts_at or now()) + timedelta(days=int(str(duration)))
                access_expires_at = min(
                    [value for value in (access_expires_at, item_expiry) if value is not None]
                )
            value = CourseEnrollment(
                user_id=entitlement.user_id,
                course_id=course.id,
                course_version_id=version.id,
                entitlement_id=entitlement.id,
                source_type=(
                    "bundle_purchase"
                    if isinstance(snapshot.get("included_courses"), list)
                    else "purchase"
                ),
                source_reference_id=entitlement.order_item_id,
                status="active",
                access_starts_at=entitlement.starts_at or now(),
                access_expires_at=access_expires_at,
                enrolled_at=now(),
            )
            session.add(value)
            await session.flush()
            created.append(value)
        inbox.processing_status = "processed"
        inbox.processed_at = now()
        return created

    async def sync_entitlement(self, session: AsyncSession, entitlement: Entitlement) -> None:
        source_event_id = uuid5(
            NAMESPACE_URL,
            f"entitlement:{entitlement.id}:{entitlement.status}:v{entitlement.version}",
        )
        inbox = await session.scalar(
            select(CourseInboxEvent).where(CourseInboxEvent.source_event_id == source_event_id)
        )
        if inbox is not None and inbox.processing_status == "processed":
            return
        if inbox is None:
            inbox = CourseInboxEvent(
                source_event_id=source_event_id,
                event_type=f"entitlement.{entitlement.status}",
                processing_status="processing",
            )
            session.add(inbox)
            await session.flush()
        status_map = {
            "active": "active",
            "suspended": "suspended",
            "revoked": "revoked",
            "expired": "expired",
            "exhausted": "suspended",
        }
        enrollments = list(
            (
                await session.scalars(
                    select(CourseEnrollment).where(
                        CourseEnrollment.entitlement_id == entitlement.id
                    )
                )
            ).all()
        )
        for enrollment in enrollments:
            enrollment.status = status_map.get(str(entitlement.status), "suspended")
            enrollment.access_expires_at = entitlement.expires_at
            enrollment.version += 1
            if enrollment.status == "suspended":
                enrollment.suspended_at = now()
            if enrollment.status == "revoked":
                enrollment.revoked_at = now()
        inbox.processing_status = "processed"
        inbox.processed_at = now()

    async def own_active(
        self, session: AsyncSession, *, enrollment_id: UUID, user_id: UUID
    ) -> CourseEnrollment:
        enrollment = await session.get(CourseEnrollment, enrollment_id)
        if enrollment is None or enrollment.user_id != user_id:
            raise VavError(
                "COURSE_ENROLLMENT_NOT_FOUND", "Enrollment was not found.", status_code=404
            )
        current = now()
        if (
            enrollment.status not in {"active", "completed"}
            or (enrollment.access_starts_at and enrollment.access_starts_at > current)
            or (enrollment.access_expires_at and enrollment.access_expires_at <= current)
        ):
            raise VavError(
                "COURSE_ACCESS_INACTIVE", "Course access is not active.", status_code=403
            )
        if enrollment.entitlement_id:
            entitlement = await session.get(Entitlement, enrollment.entitlement_id)
            if (
                entitlement is None
                or str(entitlement.status) != "active"
                or (entitlement.expires_at and entitlement.expires_at <= current)
            ):
                raise VavError(
                    "COURSE_ENTITLEMENT_INACTIVE",
                    "The entitlement for this course is not active.",
                    status_code=403,
                )
        return enrollment


async def ensure_lesson_access(
    session: AsyncSession,
    enrollment: CourseEnrollment,
    lesson_id: UUID,
) -> CourseLesson:
    version = await session.get(CourseVersion, enrollment.course_version_id)
    if version is None or lesson_id not in version_lesson_ids(version):
        raise VavError(
            "COURSE_LESSON_NOT_IN_VERSION",
            "Lesson is not part of the enrollment's pinned course version.",
            status_code=404,
        )
    lesson = await session.get(CourseLesson, lesson_id)
    module = await session.get(CourseModule, lesson.module_id) if lesson else None
    if lesson is None or module is None or module.course_id != enrollment.course_id:
        raise VavError("COURSE_LESSON_NOT_FOUND", "Lesson was not found.", status_code=404)
    if lesson.status != "published":
        raise VavError("COURSE_LESSON_UNAVAILABLE", "Lesson is not published.", status_code=403)
    release = lesson.release_at
    if release is None and lesson.release_offset_days is not None:
        release = enrollment.enrolled_at + timedelta(days=lesson.release_offset_days)
    if release and release > now():
        raise VavError("COURSE_LESSON_NOT_RELEASED", "Lesson is not released yet.", status_code=403)
    prerequisites = list(
        (
            await session.scalars(
                select(LessonPrerequisite).where(LessonPrerequisite.lesson_id == lesson.id)
            )
        ).all()
    )
    for prerequisite in prerequisites:
        progress = await session.scalar(
            select(LessonProgress).where(
                LessonProgress.enrollment_id == enrollment.id,
                LessonProgress.lesson_id == prerequisite.prerequisite_lesson_id,
            )
        )
        if prerequisite.required_completion and (
            progress is None or progress.status != "completed"
        ):
            raise VavError(
                "COURSE_PREREQUISITE_INCOMPLETE",
                "Complete prerequisite lessons before opening this lesson.",
                status_code=403,
            )
    return lesson


class ProgressService:
    async def record(
        self,
        session: AsyncSession,
        *,
        enrollment: CourseEnrollment,
        lesson: CourseLesson,
        event_type: str,
        event_sequence: int,
        idempotency_key: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> LessonProgress:
        await transaction_lock(session, f"course-progress:{enrollment.id}:{lesson.id}")
        existing_event = await session.scalar(
            select(LearningEvent).where(
                LearningEvent.enrollment_id == enrollment.id,
                or_(
                    LearningEvent.idempotency_key == idempotency_key,
                    LearningEvent.event_sequence == event_sequence,
                ),
            )
        )
        progress = await session.scalar(
            select(LessonProgress)
            .where(
                LessonProgress.enrollment_id == enrollment.id,
                LessonProgress.lesson_id == lesson.id,
            )
            .with_for_update()
        )
        if progress is None:
            progress = LessonProgress(
                enrollment_id=enrollment.id,
                lesson_id=lesson.id,
                status="not_started",
                progress_basis_points=0,
                completion_evidence={},
                version=1,
            )
            session.add(progress)
            await session.flush()
        if existing_event is not None:
            if existing_event.lesson_id != lesson.id or existing_event.event_type != event_type:
                raise VavError(
                    "LEARNING_EVENT_CONFLICT",
                    "The idempotency key or event sequence was reused for another event.",
                    status_code=409,
                )
            return progress
        session.add(
            LearningEvent(
                user_id=enrollment.user_id,
                enrollment_id=enrollment.id,
                lesson_id=lesson.id,
                event_type=event_type,
                event_sequence=event_sequence,
                idempotency_key=idempotency_key,
                event_payload=payload,
                occurred_at=occurred_at,
            )
        )
        current = now()
        progress.started_at = progress.started_at or current
        progress.last_accessed_at = current
        if event_type == "manual_completed":
            if (
                lesson.completion_mode != "manual"
                or not get_settings().course_progress_allow_manual_completion
            ):
                raise VavError(
                    "MANUAL_COMPLETION_NOT_ALLOWED",
                    "This lesson cannot be manually completed.",
                    status_code=409,
                )
            progress.status = "completed"
            progress.progress_basis_points = 10_000
            progress.completed_at = progress.completed_at or current
            progress.completion_source = "manual"
        elif progress.status != "completed":
            progress.status = "in_progress"
            progress.progress_basis_points = monotonic_progress(
                progress.progress_basis_points, int(payload.get("progress_basis_points", 1))
            )
        progress.version += 1
        await session.commit()
        return progress

    async def heartbeat(
        self,
        session: AsyncSession,
        *,
        playback: CoursePlaybackSession,
        position_seconds: int,
        played_seconds: int,
        sequence: int,
        occurred_at: datetime,
    ) -> LessonProgress:
        from vav.models.courses import CourseVideoAsset

        await transaction_lock(session, f"course-playback:{playback.id}")
        locked_playback = await session.scalar(
            select(CoursePlaybackSession)
            .where(CoursePlaybackSession.id == playback.id)
            .with_for_update()
        )
        if locked_playback is None:
            raise VavError(
                "PLAYBACK_SESSION_INACTIVE", "Playback session is not active.", status_code=410
            )
        playback = locked_playback
        current = now()
        if playback.status != "active" or playback.expires_at <= current:
            raise VavError(
                "PLAYBACK_SESSION_INACTIVE", "Playback session is not active.", status_code=410
            )
        if sequence == playback.last_sequence:
            existing_progress = await session.scalar(
                select(LessonProgress).where(
                    LessonProgress.enrollment_id == playback.enrollment_id,
                    LessonProgress.lesson_id == playback.lesson_id,
                )
            )
            if existing_progress is None:
                raise VavError(
                    "PLAYBACK_SEQUENCE_STALE", "Playback heartbeat is stale.", status_code=409
                )
            return existing_progress
        if sequence < playback.last_sequence:
            raise VavError(
                "PLAYBACK_SEQUENCE_STALE", "Playback heartbeat is stale.", status_code=409
            )
        settings = get_settings()
        elapsed = (
            (occurred_at - playback.last_heartbeat_at).total_seconds()
            if playback.last_heartbeat_at
            else settings.course_video_heartbeat_interval_seconds
        )
        if (
            elapsed < 0
            or played_seconds > elapsed + settings.course_video_heartbeat_tolerance_seconds
        ):
            raise VavError(
                "PLAYBACK_HEARTBEAT_IMPLAUSIBLE",
                "Playback heartbeat timing is not plausible.",
                status_code=422,
            )
        video = await session.get(CourseVideoAsset, playback.video_asset_id)
        resource = await session.get(LessonVideoResource, playback.lesson_id)
        if video is None or resource is None or not video.duration_seconds:
            raise VavError(
                "COURSE_VIDEO_UNAVAILABLE", "Course video is unavailable.", status_code=409
            )
        playback.last_sequence = sequence
        playback.last_position_seconds = min(position_seconds, video.duration_seconds)
        playback.maximum_position_seconds = max(
            playback.maximum_position_seconds, playback.last_position_seconds
        )
        playback.valid_played_seconds = min(
            video.duration_seconds, playback.valid_played_seconds + played_seconds
        )
        playback.last_heartbeat_at = occurred_at
        progress = await session.scalar(
            select(LessonProgress).where(
                LessonProgress.enrollment_id == playback.enrollment_id,
                LessonProgress.lesson_id == playback.lesson_id,
            )
        )
        if progress is None:
            progress = LessonProgress(
                enrollment_id=playback.enrollment_id,
                lesson_id=playback.lesson_id,
                status="not_started",
                progress_basis_points=0,
                completion_evidence={},
                version=1,
            )
            session.add(progress)
        basis_points = int(playback.valid_played_seconds * 10_000 / video.duration_seconds)
        progress.progress_basis_points = monotonic_progress(
            progress.progress_basis_points, basis_points
        )
        progress.maximum_position_seconds = max(
            progress.maximum_position_seconds or 0, playback.maximum_position_seconds
        )
        progress.last_position_seconds = playback.last_position_seconds
        progress.started_at = progress.started_at or current
        progress.last_accessed_at = current
        if basis_points >= resource.required_watch_basis_points:
            progress.status = "completed"
            progress.completed_at = progress.completed_at or current
            progress.completion_source = "verified_video_watch"
            progress.completion_evidence = {
                "playback_session_id": str(playback.id),
                "valid_played_seconds": playback.valid_played_seconds,
                "duration_seconds": video.duration_seconds,
            }
            playback.completed_at = playback.completed_at or current
        elif progress.status != "completed":
            progress.status = "in_progress"
        progress.version += 1
        await session.commit()
        return progress


class AssessmentService:
    async def start(
        self,
        session: AsyncSession,
        *,
        exercise: CourseExercise,
        enrollment: CourseEnrollment,
    ) -> ExerciseAttempt:
        await transaction_lock(session, f"course-attempt:{exercise.id}:{enrollment.id}")
        count = (
            await session.scalar(
                select(func.count())
                .select_from(ExerciseAttempt)
                .where(
                    ExerciseAttempt.exercise_id == exercise.id,
                    ExerciseAttempt.enrollment_id == enrollment.id,
                )
            )
            or 0
        )
        if exercise.maximum_attempts is not None and count >= exercise.maximum_attempts:
            raise VavError(
                "EXERCISE_ATTEMPT_LIMIT",
                "No further attempts are available.",
                status_code=409,
            )
        latest_attempt = await session.scalar(
            select(ExerciseAttempt)
            .where(
                ExerciseAttempt.exercise_id == exercise.id,
                ExerciseAttempt.enrollment_id == enrollment.id,
            )
            .order_by(ExerciseAttempt.attempt_number.desc())
            .limit(1)
        )
        if (
            latest_attempt is not None
            and exercise.cooldown_minutes
            and latest_attempt.created_at + timedelta(minutes=exercise.cooldown_minutes) > now()
        ):
            raise VavError(
                "EXERCISE_COOLDOWN_ACTIVE",
                "The exercise cooldown period is still active.",
                status_code=409,
            )
        questions = list(
            (
                await session.scalars(
                    select(ExerciseQuestion)
                    .where(ExerciseQuestion.exercise_id == exercise.id)
                    .order_by(ExerciseQuestion.sort_order, ExerciseQuestion.id)
                )
            ).all()
        )
        snapshot: list[dict[str, Any]] = []
        for question in questions:
            localization = await session.scalar(
                select(ExerciseQuestionLocalization)
                .where(ExerciseQuestionLocalization.question_id == question.id)
                .limit(1)
            )
            snapshot.append(
                {
                    "id": str(question.id),
                    "question_type": question.question_type,
                    "points": question.points,
                    "required": question.required,
                    "question_schema": question.question_schema,
                    "prompt_blocks": localization.prompt_blocks if localization else [],
                    "options": localization.options if localization else [],
                }
            )
        attempt = ExerciseAttempt(
            exercise_id=exercise.id,
            enrollment_id=enrollment.id,
            user_id=enrollment.user_id,
            attempt_number=count + 1,
            status="in_progress",
            question_snapshot=snapshot,
            response_snapshot_encrypted=encrypt_sensitive({}),
        )
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        return attempt

    async def submit(
        self,
        session: AsyncSession,
        *,
        attempt: ExerciseAttempt,
        responses: dict[str, Any],
    ) -> ExerciseAttempt:
        if attempt.status != "in_progress":
            raise VavError("EXERCISE_ATTEMPT_FINAL", "Attempt is already final.", status_code=409)
        questions = list(
            (
                await session.scalars(
                    select(ExerciseQuestion).where(
                        ExerciseQuestion.exercise_id == attempt.exercise_id
                    )
                )
            ).all()
        )
        total_points = sum(item.points for item in questions)
        earned = 0
        manual_required = False
        for question in questions:
            if question.answer_key_encrypted is None:
                manual_required = True
                continue
            expected = decrypt_sensitive(question.answer_key_encrypted)
            correct = score_response(
                question.question_type, expected, responses.get(str(question.id))
            )
            if correct is None:
                manual_required = True
            elif correct:
                earned += question.points
        score = int(earned * 10_000 / total_points) if total_points else 0
        exercise = await session.get(CourseExercise, attempt.exercise_id)
        attempt.response_snapshot_encrypted = encrypt_sensitive(responses)
        attempt.auto_score_basis_points = score
        attempt.submitted_at = now()
        if manual_required or (exercise and exercise.grading_mode != "automatic"):
            attempt.status = "pending_manual_grade"
        else:
            attempt.status = "graded"
            attempt.final_score_basis_points = score
            attempt.passed = (
                score >= (exercise.passing_score_basis_points or 0) if exercise else False
            )
            attempt.graded_at = now()
            if attempt.passed:
                await complete_assessment_lesson(session, attempt)
        await session.commit()
        return attempt


async def complete_assessment_lesson(
    session: AsyncSession, attempt: ExerciseAttempt
) -> LessonProgress | None:
    exercise = await session.get(CourseExercise, attempt.exercise_id)
    lesson = await session.get(CourseLesson, exercise.lesson_id) if exercise else None
    if (
        exercise is None
        or lesson is None
        or lesson.completion_mode
        not in {
            "exercise_pass",
            "assignment_graded",
        }
    ):
        return None
    progress = await session.scalar(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == attempt.enrollment_id,
            LessonProgress.lesson_id == lesson.id,
        )
    )
    if progress is None:
        progress = LessonProgress(
            enrollment_id=attempt.enrollment_id,
            lesson_id=lesson.id,
            status="not_started",
            progress_basis_points=0,
            completion_evidence={},
            version=1,
        )
        session.add(progress)
    current = now()
    progress.status = "completed"
    progress.progress_basis_points = 10_000
    progress.started_at = progress.started_at or attempt.created_at or current
    progress.last_accessed_at = current
    progress.completed_at = progress.completed_at or current
    progress.completion_source = "exercise_pass" if exercise.exercise_type == "quiz" else "graded"
    progress.completion_evidence = {
        "exercise_id": str(exercise.id),
        "attempt_id": str(attempt.id),
        "score_basis_points": attempt.final_score_basis_points,
    }
    progress.version += 1
    return progress


class CompletionService:
    async def evaluate(
        self, session: AsyncSession, enrollment: CourseEnrollment
    ) -> tuple[CourseCompletionRecord | None, CourseCertificate | None, str | None]:
        await transaction_lock(session, f"course-completion:{enrollment.id}")
        existing = await session.scalar(
            select(CourseCompletionRecord).where(
                CourseCompletionRecord.enrollment_id == enrollment.id
            )
        )
        if existing:
            certificate = await session.scalar(
                select(CourseCertificate).where(
                    CourseCertificate.completion_record_id == existing.id
                )
            )
            return existing, certificate, None
        course = await session.get(Course, enrollment.course_id)
        policy = (
            await session.get(CourseCompletionPolicy, course.completion_policy_id)
            if course and course.completion_policy_id
            else None
        )
        if course is None or policy is None:
            return None, None, None
        course_version = await session.get(CourseVersion, enrollment.course_version_id)
        if course_version is None:
            return None, None, None
        lesson_ids: list[UUID] = []
        modules = course_version.curriculum_snapshot.get("modules", [])
        if isinstance(modules, list):
            for module in modules:
                if not isinstance(module, dict) or not isinstance(module.get("lessons"), list):
                    continue
                for lesson in module["lessons"]:
                    if isinstance(lesson, str):
                        with suppress(ValueError):
                            lesson_ids.append(UUID(lesson))
                        continue
                    if not isinstance(lesson, dict) or lesson.get("required") is not True:
                        continue
                    try:
                        lesson_ids.append(UUID(str(lesson["id"])))
                    except (KeyError, TypeError, ValueError):
                        continue
        completed_ids = (
            set(
                (
                    await session.scalars(
                        select(LessonProgress.lesson_id).where(
                            LessonProgress.enrollment_id == enrollment.id,
                            LessonProgress.status == "completed",
                            LessonProgress.lesson_id.in_(lesson_ids),
                        )
                    )
                ).all()
            )
            if lesson_ids
            else set()
        )
        lesson_bps = int(len(completed_ids) * 10_000 / len(lesson_ids)) if lesson_ids else 10_000
        if policy.require_all_required_lessons and len(completed_ids) != len(lesson_ids):
            return None, None, None
        if lesson_bps < policy.required_lesson_completion_basis_points:
            return None, None, None
        required_exercises = (
            list(
                (
                    await session.scalars(
                        select(CourseExercise).where(
                            CourseExercise.lesson_id.in_(lesson_ids),
                            CourseExercise.status == "published",
                        )
                    )
                ).all()
            )
            if lesson_ids
            else []
        )
        passed_exercise_ids = (
            set(
                (
                    await session.scalars(
                        select(ExerciseAttempt.exercise_id).where(
                            ExerciseAttempt.enrollment_id == enrollment.id,
                            ExerciseAttempt.exercise_id.in_(
                                [item.id for item in required_exercises]
                            ),
                            ExerciseAttempt.passed.is_(True),
                        )
                    )
                ).all()
            )
            if required_exercises
            else set()
        )
        exercise_bps = (
            int(len(passed_exercise_ids) * 10_000 / len(required_exercises))
            if required_exercises
            else 10_000
        )
        if policy.require_all_required_exercises and len(passed_exercise_ids) != len(
            required_exercises
        ):
            return None, None, None
        if (
            policy.required_exercise_pass_basis_points is not None
            and exercise_bps < policy.required_exercise_pass_basis_points
        ):
            return None, None, None
        evidence = {
            "required_lessons": len(lesson_ids),
            "completed_required_lessons": len(completed_ids),
            "lesson_completion_basis_points": lesson_bps,
            "required_exercises": len(required_exercises),
            "passed_required_exercises": len(passed_exercise_ids),
            "exercise_pass_basis_points": exercise_bps,
        }
        completion = CourseCompletionRecord(
            enrollment_id=enrollment.id,
            course_id=course.id,
            course_version_id=enrollment.course_version_id,
            completion_policy_snapshot={
                "policy_code": policy.policy_code,
                "policy_version": policy.policy_version,
                "required_lesson_completion_basis_points": (
                    policy.required_lesson_completion_basis_points
                ),
                "certificate_enabled": policy.certificate_enabled,
            },
            completion_evidence=evidence,
            completed_at=now(),
            evaluated_by="course_completion_v1",
            evaluation_version="1",
        )
        session.add(completion)
        enrollment.status = "completed"
        enrollment.completed_at = completion.completed_at
        await session.flush()
        certificate = None
        raw_token = None
        if policy.certificate_enabled and get_settings().course_certificate_enabled:
            user = await session.get(User, enrollment.user_id)
            localization = await session.scalar(
                select(CourseLocalization)
                .where(
                    CourseLocalization.course_id == course.id,
                    CourseLocalization.locale == course.default_locale,
                )
                .limit(1)
            )
            raw_token = f"VAV-COURSE-{secrets.token_urlsafe(24)}"
            certificate = CourseCertificate(
                certificate_number=raw_token,
                completion_record_id=completion.id,
                user_id=enrollment.user_id,
                course_id=course.id,
                recipient_name_snapshot=(user.display_email if user else "VAV learner"),
                course_title_snapshot=(
                    localization.title if localization else course.internal_name
                ),
                issued_at=now(),
                status="valid",
                verification_token_hash=token_hash(raw_token),
            )
            session.add(certificate)
        session.add(
            OutboxEvent(
                topic="course.completed",
                aggregate_type="course_enrollment",
                aggregate_id=str(enrollment.id),
                payload={"course_id": str(course.id), "user_id": str(enrollment.user_id)},
            )
        )
        await session.commit()
        return completion, certificate, raw_token


publication_service = PublicationService()
enrollment_service = EnrollmentService()
progress_service = ProgressService()
assessment_service = AssessmentService()
completion_service = CompletionService()


def enrollment_payload(value: CourseEnrollment) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "course_id": str(value.course_id),
        "course_version_id": str(value.course_version_id),
        "status": value.status,
        "source_type": value.source_type,
        "access_starts_at": value.access_starts_at.isoformat() if value.access_starts_at else None,
        "access_expires_at": value.access_expires_at.isoformat()
        if value.access_expires_at
        else None,
        "enrolled_at": value.enrolled_at.isoformat(),
        "completed_at": value.completed_at.isoformat() if value.completed_at else None,
    }


def progress_payload(value: LessonProgress) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "lesson_id": str(value.lesson_id),
        "status": value.status,
        "progress_basis_points": value.progress_basis_points,
        "last_position_seconds": value.last_position_seconds,
        "maximum_position_seconds": value.maximum_position_seconds,
        "completed_at": value.completed_at.isoformat() if value.completed_at else None,
        "version": value.version,
    }


def certificate_payload(value: CourseCertificate, *, public: bool = False) -> dict[str, Any]:
    result = {
        "certificate_number": value.certificate_number,
        "recipient_name": (
            mask_public_name(value.recipient_name_snapshot)
            if public
            else value.recipient_name_snapshot
        ),
        "course_title": value.course_title_snapshot,
        "issued_at": value.issued_at.isoformat(),
        "status": value.status,
        "revoked_at": value.revoked_at.isoformat() if value.revoked_at else None,
        "credential_type": "VAV course completion record",
        "accreditation_claim": None,
    }
    if not public:
        result["verification_token"] = value.certificate_number
    return result
