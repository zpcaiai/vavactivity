from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.models.catalog import Price, PriceBook, Product, ProductLocalization, ProductSku
from vav.models.courses import (
    Course,
    CourseCompletionPolicy,
    CourseExercise,
    CourseInstructor,
    CourseInstructorAssignment,
    CourseLesson,
    CourseLessonLocalization,
    CourseLocalization,
    CourseModule,
    CourseModuleLocalization,
    CourseSkuMapping,
    CourseVersion,
    CourseVideoAsset,
    ExerciseQuestion,
    ExerciseQuestionLocalization,
    LessonVideoResource,
)
from vav.modules.courses.crypto import encrypt_sensitive


async def _ensure_companion_courses(
    session: AsyncSession,
    *,
    book: PriceBook,
    instructor: CourseInstructor,
) -> None:
    specs = (
        (
            "course-showcase-communication",
            "COURSE_SHOWCASE_COMMUNICATION",
            "COURSE_SHOWCASE_COMMUNICATION_ACCESS",
            "relationship-communication-practice",
            "关系沟通练习课",
            "用三个短练习建立清晰、尊重且可持续的沟通习惯。",
            35,
        ),
        (
            "course-showcase-growth-plan",
            "COURSE_SHOWCASE_GROWTH_PLAN",
            "COURSE_SHOWCASE_GROWTH_PLAN_ACCESS",
            "shared-growth-plan",
            "共同成长计划课",
            "从价值澄清到每周行动，形成可回顾的共同成长计划。",
            40,
        ),
    )
    for course_code, product_code, sku_code, slug, title, summary, duration in specs:
        existing = await session.scalar(select(Course).where(Course.course_code == course_code))
        if existing is not None:
            continue
        product = Product(
            product_code=product_code,
            product_type="course",
            fulfillment_type="digital_access",
            internal_name=f"Test showcase: {title}",
            status="active",
            visibility="public",
            default_locale="zh-CN",
            created_by=SYSTEM_USER_ID,
            updated_by=SYSTEM_USER_ID,
        )
        session.add(product)
        await session.flush()
        session.add(
            ProductLocalization(
                product_id=product.id,
                locale="zh-CN",
                slug=slug,
                name=title,
                short_description=summary,
                description_blocks=[],
                translation_status="ready",
            )
        )
        sku = ProductSku(
            product_id=product.id,
            sku_code=sku_code,
            internal_name=f"{title} 访问权",
            billing_type="free",
            status="active",
            entitlement_definition={"type": "course_access"},
            fulfillment_configuration={"duration_days": 365},
            inventory_policy="unlimited",
            purchase_limit_per_user=1,
        )
        session.add(sku)
        await session.flush()
        session.add(
            Price(
                sku_id=sku.id,
                price_book_id=book.id,
                currency_code="USD",
                unit_amount_minor=0,
                billing_type="free",
                valid_from=datetime.now(UTC),
                status="active",
                created_by=SYSTEM_USER_ID,
            )
        )
        policy = CourseCompletionPolicy(
            policy_code=f"{course_code}-v1",
            policy_version=1,
            required_lesson_completion_basis_points=10000,
            require_all_required_lessons=True,
            certificate_enabled=True,
        )
        session.add(policy)
        await session.flush()
        course = Course(
            course_code=course_code,
            internal_name=f"Test showcase: {title}",
            course_type="self_paced",
            status="published",
            visibility="public",
            default_locale="zh-CN",
            difficulty_level="beginner",
            estimated_duration_minutes=duration,
            content_release_policy="all_at_once",
            free_access_policy="free_enrollment",
            catalog_product_id=product.id,
            primary_catalog_sku_id=sku.id,
            completion_policy_id=policy.id,
            featured=True,
            created_by=SYSTEM_USER_ID,
            updated_by=SYSTEM_USER_ID,
        )
        session.add(course)
        await session.flush()
        session.add_all(
            (
                CourseLocalization(
                    course_id=course.id,
                    locale="zh-CN",
                    slug=slug,
                    title=title,
                    subtitle=summary,
                    summary=summary,
                    description_blocks=[
                        {"type": "paragraph", "text": "本课程为 test 账户展示数据。"}
                    ],
                    learning_outcomes=[{"text": "形成一项可以持续练习的关系技能"}],
                    translation_status="ready",
                ),
                CourseSkuMapping(
                    catalog_sku_id=sku.id,
                    course_id=course.id,
                    access_duration_days=365,
                    access_start_policy="entitlement_activation",
                    course_version_policy="pin_at_enrollment",
                ),
                CourseInstructorAssignment(
                    course_id=course.id,
                    instructor_id=instructor.id,
                    role="lead",
                    sort_order=0,
                ),
            )
        )
        module = CourseModule(
            course_id=course.id,
            module_code="practice",
            internal_name="Practice",
            status="published",
            sort_order=10,
            required=True,
        )
        session.add(module)
        await session.flush()
        session.add(
            CourseModuleLocalization(
                module_id=module.id,
                locale="zh-CN",
                title="第一章：开始练习",
            )
        )
        lesson = CourseLesson(
            module_id=module.id,
            lesson_code="first-practice",
            internal_name="First practice",
            lesson_type="rich_text",
            status="published",
            sort_order=10,
            required=True,
            preview_policy="public",
            estimated_duration_minutes=duration,
            completion_mode="manual",
            completion_threshold={},
        )
        session.add(lesson)
        await session.flush()
        session.add(
            CourseLessonLocalization(
                lesson_id=lesson.id,
                locale="zh-CN",
                title="从一个小行动开始",
                content_blocks=[
                    {"type": "paragraph", "text": "选择一个本周可以完成的小练习并记录感受。"}
                ],
            )
        )
        session.add(
            CourseVersion(
                course_id=course.id,
                version_number=1,
                curriculum_snapshot={
                    "schema_version": 1,
                    "course_id": str(course.id),
                    "completion_policy_id": str(policy.id),
                    "modules": [
                        {
                            "id": str(module.id),
                            "title": "第一章：开始练习",
                            "lessons": [
                                {
                                    "id": str(lesson.id),
                                    "title": "从一个小行动开始",
                                    "lesson_type": "rich_text",
                                }
                            ],
                        }
                    ],
                },
                change_summary="Test showcase fixture",
                created_by=SYSTEM_USER_ID,
                published_at=datetime.now(UTC),
            )
        )


async def seed_courses() -> None:
    if get_settings().environment not in {"development", "test", "staging"}:
        print("Course fixtures skipped outside development/test/staging.")
        return
    await ensure_system_user()
    async with session_factory() as session:
        book = await session.scalar(
            select(PriceBook).where(PriceBook.price_book_code == "GLOBAL_STANDARD")
        )
        if book is None:
            raise RuntimeError("Run catalog seed before course seed.")
        existing = await session.scalar(
            select(Course).where(Course.course_code == "course-e2e-foundations")
        )
        if existing is not None:
            from vav.modules.courses.service import curriculum_payload

            version = await session.scalar(
                select(CourseVersion)
                .where(CourseVersion.course_id == existing.id)
                .order_by(CourseVersion.version_number.desc())
                .limit(1)
            )
            if version is not None:
                version.curriculum_snapshot = {
                    "schema_version": 1,
                    "course_id": str(existing.id),
                    "completion_policy_id": str(existing.completion_policy_id),
                    "modules": await curriculum_payload(
                        session,
                        existing.id,
                        locale=existing.default_locale,
                        public_only=True,
                    ),
                }
            instructor = await session.scalar(
                select(CourseInstructor).where(
                    CourseInstructor.instructor_code == "course-e2e-mentor"
                )
            )
            if instructor is None:
                instructor = CourseInstructor(
                    instructor_code="course-e2e-mentor",
                    display_name="VAV 课程导师",
                    status="active",
                )
                session.add(instructor)
                await session.flush()
            assignment = await session.get(
                CourseInstructorAssignment,
                {
                    "course_id": existing.id,
                    "instructor_id": instructor.id,
                    "role": "lead",
                },
            )
            if assignment is None:
                session.add(
                    CourseInstructorAssignment(
                        course_id=existing.id,
                        instructor_id=instructor.id,
                        role="lead",
                        sort_order=0,
                    )
                )
            await _ensure_companion_courses(session, book=book, instructor=instructor)
            await session.commit()
            print("Course seed already present; 3-course showcase refreshed.")
            return

        product = Product(
            product_code="COURSE_E2E_FOUNDATIONS",
            product_type="course",
            fulfillment_type="digital_access",
            internal_name="Local course acceptance fixture",
            status="active",
            visibility="public",
            default_locale="zh-CN",
            created_by=SYSTEM_USER_ID,
            updated_by=SYSTEM_USER_ID,
        )
        session.add(product)
        await session.flush()
        session.add(
            ProductLocalization(
                product_id=product.id,
                locale="zh-CN",
                slug="course-e2e-foundations",
                name="健康关系基础课",
                short_description="开发与测试环境课程。",
                description_blocks=[],
                translation_status="ready",
            )
        )
        sku = ProductSku(
            product_id=product.id,
            sku_code="COURSE_E2E_FOUNDATIONS_ACCESS",
            internal_name="健康关系基础课访问权",
            billing_type="one_time",
            status="active",
            entitlement_definition={"type": "course_access"},
            fulfillment_configuration={"duration_days": 365},
            inventory_policy="unlimited",
            purchase_limit_per_user=1,
        )
        session.add(sku)
        await session.flush()
        session.add(
            Price(
                sku_id=sku.id,
                price_book_id=book.id,
                currency_code="USD",
                unit_amount_minor=2900,
                billing_type="one_time",
                valid_from=datetime.now(UTC),
                status="active",
                created_by=SYSTEM_USER_ID,
            )
        )
        policy = CourseCompletionPolicy(
            policy_code="course-e2e-foundations-v1",
            policy_version=1,
            required_lesson_completion_basis_points=10000,
            require_all_required_lessons=True,
            certificate_enabled=True,
        )
        session.add(policy)
        await session.flush()
        course = Course(
            course_code="course-e2e-foundations",
            internal_name="Local course acceptance fixture",
            course_type="self_paced",
            status="published",
            visibility="public",
            default_locale="zh-CN",
            difficulty_level="beginner",
            estimated_duration_minutes=25,
            content_release_policy="all_at_once",
            free_access_policy="free_enrollment",
            catalog_product_id=product.id,
            primary_catalog_sku_id=sku.id,
            completion_policy_id=policy.id,
            featured=True,
            created_by=SYSTEM_USER_ID,
            updated_by=SYSTEM_USER_ID,
        )
        session.add(course)
        await session.flush()
        instructor = CourseInstructor(
            instructor_code="course-e2e-mentor",
            display_name="VAV 课程导师",
            status="active",
        )
        session.add(instructor)
        await session.flush()
        session.add(
            CourseInstructorAssignment(
                course_id=course.id,
                instructor_id=instructor.id,
                role="lead",
                sort_order=0,
            )
        )
        session.add(
            CourseLocalization(
                course_id=course.id,
                locale="zh-CN",
                slug="healthy-relationship-foundations",
                title="健康关系基础课",
                subtitle="建立边界、沟通与共同成长的基础",
                summary="一门用于本地验收的示例课程；购买、权益和学习进度均由服务端确认。",
                description_blocks=[
                    {"type": "paragraph", "text": "内容仅用于产品功能演示，不构成专业诊断。"}
                ],
                learning_outcomes=[
                    {"text": "识别尊重与边界"},
                    {"text": "练习清晰沟通"},
                ],
                translation_status="ready",
            )
        )
        session.add(
            CourseSkuMapping(
                catalog_sku_id=sku.id,
                course_id=course.id,
                access_duration_days=365,
                access_start_policy="entitlement_activation",
                course_version_policy="pin_at_enrollment",
            )
        )
        module = CourseModule(
            course_id=course.id,
            module_code="foundations",
            internal_name="Foundations",
            status="published",
            sort_order=10,
            required=True,
        )
        session.add(module)
        await session.flush()
        session.add(
            CourseModuleLocalization(
                module_id=module.id,
                locale="zh-CN",
                title="第一章：尊重与边界",
            )
        )
        rich_lesson = CourseLesson(
            module_id=module.id,
            lesson_code="respect-boundaries",
            internal_name="Respect and boundaries",
            lesson_type="rich_text",
            status="published",
            sort_order=10,
            required=True,
            preview_policy="public",
            estimated_duration_minutes=10,
            completion_mode="manual",
            completion_threshold={},
        )
        video_lesson = CourseLesson(
            module_id=module.id,
            lesson_code="communication-practice",
            internal_name="Communication practice",
            lesson_type="video",
            status="published",
            sort_order=20,
            required=True,
            preview_policy="none",
            estimated_duration_minutes=15,
            completion_mode="video_watch",
            completion_threshold={"required_watch_basis_points": 9000},
        )
        session.add_all((rich_lesson, video_lesson))
        await session.flush()
        session.add_all(
            (
                CourseLessonLocalization(
                    lesson_id=rich_lesson.id,
                    locale="zh-CN",
                    title="识别尊重与边界",
                    content_blocks=[
                        {
                            "type": "paragraph",
                            "text": "健康边界以自愿、尊重和清晰沟通为基础。",
                        }
                    ],
                ),
                CourseLessonLocalization(
                    lesson_id=video_lesson.id,
                    locale="zh-CN",
                    title="沟通练习",
                    content_blocks=[],
                ),
            )
        )
        video = CourseVideoAsset(
            provider="fake_private",
            provider_environment="development",
            provider_video_id="course-e2e-private-video",
            private_reference_encrypted=encrypt_sensitive(
                {"value": "s3://private-course-fixtures/communication.m3u8"}
            ),
            processing_status="ready",
            duration_seconds=120,
            playback_format="hls",
            created_by=SYSTEM_USER_ID,
        )
        session.add(video)
        await session.flush()
        session.add(
            LessonVideoResource(
                lesson_id=video_lesson.id,
                video_asset_id=video.id,
                required_watch_basis_points=9000,
            )
        )
        exercise = CourseExercise(
            lesson_id=rich_lesson.id,
            exercise_code="boundaries-check",
            exercise_type="quiz",
            status="published",
            grading_mode="automatic",
            passing_score_basis_points=7000,
            maximum_attempts=3,
            reveal_answers_policy="after_pass",
        )
        session.add(exercise)
        await session.flush()
        question = ExerciseQuestion(
            exercise_id=exercise.id,
            question_type="true_false",
            sort_order=10,
            points=1,
            required=True,
            question_schema={},
            answer_key_encrypted=encrypt_sensitive(True),
            grading_schema={},
        )
        session.add(question)
        await session.flush()
        session.add(
            ExerciseQuestionLocalization(
                question_id=question.id,
                locale="zh-CN",
                prompt_blocks=[{"type": "paragraph", "text": "健康边界应以自愿和尊重为基础。"}],
                options=[
                    {"value": True, "label": "正确"},
                    {"value": False, "label": "错误"},
                ],
            )
        )
        await session.flush()
        from vav.modules.courses.service import curriculum_payload

        session.add(
            CourseVersion(
                course_id=course.id,
                version_number=1,
                curriculum_snapshot={
                    "schema_version": 1,
                    "course_id": str(course.id),
                    "completion_policy_id": str(course.completion_policy_id),
                    "modules": await curriculum_payload(
                        session,
                        course.id,
                        locale=course.default_locale,
                        public_only=True,
                    ),
                },
                change_summary="Development acceptance fixture",
                created_by=SYSTEM_USER_ID,
                published_at=datetime.now(UTC),
            )
        )
        await _ensure_companion_courses(session, book=book, instructor=instructor)
        await session.commit()
    print("Course seed complete: 3 public courses with curriculum and versions")


if __name__ == "__main__":
    asyncio.run(seed_courses())
