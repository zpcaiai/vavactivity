import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from vav.core.database import session_factory
from vav.models.courses import (
    Course,
    CourseCertificate,
    CourseCompletionRecord,
    CourseEnrollment,
    CourseLesson,
    CourseModule,
    CoursePlaybackSession,
    CourseVersion,
    LearningEvent,
    LessonProgress,
    LessonVideoResource,
)
from vav.models.identity import User
from vav.modules.courses.service import completion_service, progress_service


async def _create_enrollment() -> dict[str, UUID]:
    suffix = uuid4().hex
    async with session_factory() as session:
        course = await session.scalar(
            select(Course).where(Course.course_code == "course-e2e-foundations")
        )
        assert course is not None
        version = await session.scalar(
            select(CourseVersion)
            .where(CourseVersion.course_id == course.id)
            .order_by(CourseVersion.version_number.desc())
            .limit(1)
        )
        assert version is not None
        module_ids = list(
            (
                await session.scalars(
                    select(CourseModule.id).where(CourseModule.course_id == course.id)
                )
            ).all()
        )
        lessons = list(
            (
                await session.scalars(
                    select(CourseLesson)
                    .where(CourseLesson.module_id.in_(module_ids))
                    .order_by(CourseLesson.sort_order, CourseLesson.id)
                )
            ).all()
        )
        user = User(
            email=f"course-race-{suffix}@example.com",
            display_email=f"course-race-{suffix}@example.com",
            password_hash=None,
            status="active",
        )
        session.add(user)
        await session.flush()
        enrollment = CourseEnrollment(
            user_id=user.id,
            course_id=course.id,
            course_version_id=version.id,
            source_type="free_enrollment",
            status="active",
            access_starts_at=datetime.now(UTC),
            enrolled_at=datetime.now(UTC),
        )
        session.add(enrollment)
        await session.commit()
        return {
            "course_id": course.id,
            "enrollment_id": enrollment.id,
            "lesson_id": lessons[0].id,
            "user_id": user.id,
        }


@pytest.mark.asyncio
async def test_concurrent_progress_events_preserve_the_highest_value() -> None:
    graph = await _create_enrollment()

    async def record(sequence: int, basis_points: int) -> None:
        async with session_factory() as session:
            enrollment = await session.get(CourseEnrollment, graph["enrollment_id"])
            lesson = await session.get(CourseLesson, graph["lesson_id"])
            assert enrollment is not None and lesson is not None
            await progress_service.record(
                session,
                enrollment=enrollment,
                lesson=lesson,
                event_type="lesson_opened",
                event_sequence=sequence,
                idempotency_key=f"progress-{uuid4().hex}",
                occurred_at=datetime.now(UTC),
                payload={"progress_basis_points": basis_points},
            )

    await asyncio.gather(record(1, 9_000), record(2, 2_500))
    async with session_factory() as session:
        progress = await session.scalar(
            select(LessonProgress).where(
                LessonProgress.enrollment_id == graph["enrollment_id"],
                LessonProgress.lesson_id == graph["lesson_id"],
            )
        )
        event_count = await session.scalar(
            select(func.count(LearningEvent.id)).where(
                LearningEvent.enrollment_id == graph["enrollment_id"]
            )
        )
    assert progress is not None and progress.progress_basis_points == 9_000
    assert event_count == 2


@pytest.mark.asyncio
async def test_duplicate_concurrent_heartbeat_counts_played_time_once() -> None:
    graph = await _create_enrollment()
    async with session_factory() as session:
        resource = await session.scalar(select(LessonVideoResource).limit(1))
        assert resource is not None
        playback = CoursePlaybackSession(
            user_id=graph["user_id"],
            enrollment_id=graph["enrollment_id"],
            lesson_id=resource.lesson_id,
            video_asset_id=resource.video_asset_id,
            access_token_hash="test-only-hash",
            status="active",
            started_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add(playback)
        await session.commit()
        playback_id = playback.id

    occurred_at = datetime.now(UTC)

    async def heartbeat() -> None:
        async with session_factory() as session:
            playback = await session.get(CoursePlaybackSession, playback_id)
            assert playback is not None
            await progress_service.heartbeat(
                session,
                playback=playback,
                position_seconds=10,
                played_seconds=10,
                sequence=1,
                occurred_at=occurred_at,
            )

    await asyncio.gather(heartbeat(), heartbeat())
    async with session_factory() as session:
        playback = await session.get(CoursePlaybackSession, playback_id)
        assert playback is not None
        progress_count = await session.scalar(
            select(func.count(LessonProgress.id)).where(
                LessonProgress.enrollment_id == graph["enrollment_id"],
                LessonProgress.lesson_id == playback.lesson_id,
            )
        )
    assert playback.valid_played_seconds == 10
    assert playback.last_sequence == 1
    assert progress_count == 1


@pytest.mark.asyncio
async def test_concurrent_completion_issues_one_record_and_certificate() -> None:
    graph = await _create_enrollment()
    async with session_factory() as session:
        enrollment = await session.get(CourseEnrollment, graph["enrollment_id"])
        assert enrollment is not None
        version = await session.get(CourseVersion, enrollment.course_version_id)
        assert version is not None
        lesson_ids: list[UUID] = []
        modules = version.curriculum_snapshot.get("modules", [])
        assert isinstance(modules, list)
        for module in modules:
            assert isinstance(module, dict)
            lessons = module.get("lessons", [])
            assert isinstance(lessons, list)
            for lesson in lessons:
                assert isinstance(lesson, dict)
                if lesson.get("required") is True:
                    lesson_ids.append(UUID(str(lesson["id"])))
        for lesson_id in lesson_ids:
            session.add(
                LessonProgress(
                    enrollment_id=enrollment.id,
                    lesson_id=lesson_id,
                    status="completed",
                    progress_basis_points=10_000,
                    completed_at=datetime.now(UTC),
                )
            )
        await session.commit()

    async def evaluate() -> None:
        async with session_factory() as session:
            enrollment = await session.get(CourseEnrollment, graph["enrollment_id"])
            assert enrollment is not None
            await completion_service.evaluate(session, enrollment)

    await asyncio.gather(evaluate(), evaluate())
    async with session_factory() as session:
        completion_count = await session.scalar(
            select(func.count(CourseCompletionRecord.id)).where(
                CourseCompletionRecord.enrollment_id == graph["enrollment_id"]
            )
        )
        certificate_count = await session.scalar(
            select(func.count(CourseCertificate.id)).where(
                CourseCertificate.user_id == graph["user_id"]
            )
        )
    assert completion_count == 1
    assert certificate_count == 1
