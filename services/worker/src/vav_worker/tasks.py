from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from vav.core.database import get_engine, session_factory
from vav.models.content import ContentEntry
from vav.models.courses import Course, CourseEnrollment
from vav.modules.activities.service import (
    activity_lifecycle_service,
    registration_service,
)
from vav.modules.catalog.inventory import inventory_service
from vav.modules.catalog.promotions import coupon_redemption_service
from vav.modules.content.domain import ContentStatus
from vav.modules.content.service import content_service
from vav.modules.commerce.service import reconciliation_service
from vav.modules.courses.service import completion_service, publication_service
from vav.modules.counseling.service import availability_service
from vav_worker.celery_app import celery_app


async def _publish_scheduled() -> int:
    published = 0
    async with session_factory() as session:
        entries = list(
            (
                await session.scalars(
                    select(ContentEntry)
                    .where(
                        ContentEntry.status == ContentStatus.SCHEDULED,
                        ContentEntry.scheduled_publish_at <= datetime.now(UTC),
                    )
                    .order_by(ContentEntry.scheduled_publish_at)
                    .limit(100)
                )
            ).all()
        )
        for entry in entries:
            await content_service.transition(
                session,
                entry=entry,
                action="publish",
                actor_id=entry.published_by or entry.author_id,
                reason="Scheduled publication time reached.",
            )
            published += 1
    await get_engine().dispose()
    return published


async def _expire_reservations() -> dict[str, int]:
    async with session_factory() as session:
        inventory_count = await inventory_service.expire_due(session)
    async with session_factory() as session:
        coupon_count = await coupon_redemption_service.expire_due(session)
    await get_engine().dispose()
    return {"inventory": inventory_count, "coupon": coupon_count}


@celery_app.task(name="vav.content.publish_scheduled")  # type: ignore[misc]
def publish_scheduled_content() -> dict[str, int]:
    return {"published": asyncio.run(_publish_scheduled())}


@celery_app.task(name="vav.inventory.expire_reservations")  # type: ignore[misc]
def expire_inventory_reservations() -> dict[str, int]:
    return asyncio.run(_expire_reservations())


async def _reconcile_commerce() -> int:
    async with session_factory() as session:
        count = await reconciliation_service.scan(session)
    await get_engine().dispose()
    return count


@celery_app.task(name="vav.commerce.reconcile")  # type: ignore[misc]
def reconcile_commerce() -> dict[str, int]:
    return {"discrepancies": asyncio.run(_reconcile_commerce())}


async def _advance_activities() -> dict[str, int]:
    async with session_factory() as session:
        lifecycle = await activity_lifecycle_service.advance_due(session)
    async with session_factory() as session:
        waitlist = await registration_service.offer_waitlist_places(session)
    await get_engine().dispose()
    return {"lifecycle": lifecycle, "waitlist_offers": waitlist}


@celery_app.task(name="vav.activities.advance")  # type: ignore[misc]
def advance_activities() -> dict[str, int]:
    return asyncio.run(_advance_activities())


async def _advance_courses() -> dict[str, int]:
    published = 0
    evaluated = 0
    async with session_factory() as session:
        scheduled = list(
            (
                await session.scalars(
                    select(Course).where(
                        Course.status == "scheduled",
                        Course.enrollment_opens_at <= datetime.now(UTC),
                    )
                )
            ).all()
        )
        for course in scheduled:
            await publication_service.transition(
                session,
                course,
                target="published",
                actor_id=course.updated_by,
                reason="Scheduled course publication time reached.",
            )
            published += 1
    async with session_factory() as session:
        enrollments = list(
            (
                await session.scalars(
                    select(CourseEnrollment)
                    .where(CourseEnrollment.status == "active")
                    .order_by(CourseEnrollment.updated_at)
                    .limit(200)
                )
            ).all()
        )
        for enrollment in enrollments:
            completion, _, _ = await completion_service.evaluate(session, enrollment)
            if completion is not None:
                evaluated += 1
    await get_engine().dispose()
    return {"published": published, "completed": evaluated}


@celery_app.task(name="vav.courses.advance")  # type: ignore[misc]
def advance_courses() -> dict[str, int]:
    return asyncio.run(_advance_courses())


async def _advance_counseling() -> int:
    async with session_factory() as session:
        expired = await availability_service.expire(session)
    await get_engine().dispose()
    return expired


@celery_app.task(name="vav.counseling.advance")  # type: ignore[misc]
def advance_counseling() -> dict[str, int]:
    return {"expired_holds": asyncio.run(_advance_counseling())}
