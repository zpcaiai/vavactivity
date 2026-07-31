from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from vav.core.database import session_factory
from vav.models.courses import (
    Course,
    CourseEnrollment,
    CourseLesson,
    CourseModule,
    CourseVersion,
    LessonProgress,
)
from vav.models.identity import User
from vav.modules.courses.crypto import token_hash
from vav.modules.courses.service import certificate_payload, completion_service
from vav.modules.identity.domain import UserStatus


@pytest.mark.asyncio
async def test_completion_and_certificate_issuance_are_idempotent() -> None:
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
        )
        assert version is not None
        user = User(
            email=f"certificate-{suffix}@example.com",
            display_email=f"certificate-{suffix}@example.com",
            password_hash=None,
            status=UserStatus.ACTIVE,
            email_verified_at=datetime.now(UTC),
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
        await session.flush()
        module_ids = list(
            (
                await session.scalars(
                    select(CourseModule.id).where(CourseModule.course_id == course.id)
                )
            ).all()
        )
        lesson_ids = list(
            (
                await session.scalars(
                    select(CourseLesson.id).where(
                        CourseLesson.module_id.in_(module_ids),
                        CourseLesson.required.is_(True),
                    )
                )
            ).all()
        )
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
        await session.flush()
        completion, certificate, verification_token = await completion_service.evaluate(
            session, enrollment
        )
        assert completion is not None
        assert certificate is not None
        assert verification_token == certificate.certificate_number
        assert certificate.verification_token_hash == token_hash(verification_token)
        assert certificate_payload(certificate)["verification_token"] == verification_token
        repeated, repeated_certificate, repeated_token = await completion_service.evaluate(
            session, enrollment
        )
        assert repeated is not None and repeated.id == completion.id
        assert repeated_certificate is not None
        assert repeated_certificate.id == certificate.id
        assert repeated_token is None
