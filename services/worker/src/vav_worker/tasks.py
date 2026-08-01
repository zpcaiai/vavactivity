from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select, text

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
from vav.modules.notifications.service import (
    consume_outbox_events,
    dispatch_campaign_batch,
    dispatch_digest_window,
    dispatch_due_reminders,
    process_due_deliveries,
)
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


async def _consume_notification_outbox() -> int:
    async with session_factory() as session:
        values = await consume_outbox_events(session)
    await get_engine().dispose()
    return len(values)


@celery_app.task(name="vav.notifications.consume_outbox")  # type: ignore[misc]
def consume_notification_outbox() -> dict[str, int]:
    return {"processed": asyncio.run(_consume_notification_outbox())}


async def _deliver_notifications() -> int:
    async with session_factory() as session:
        values = await process_due_deliveries(session)
    await get_engine().dispose()
    return len(values)


@celery_app.task(name="vav.notifications.deliver")  # type: ignore[misc]
def deliver_notifications() -> dict[str, int]:
    return {"processed": asyncio.run(_deliver_notifications())}


async def _dispatch_notification_reminders() -> int:
    async with session_factory() as session:
        values = await dispatch_due_reminders(session)
    await get_engine().dispose()
    return len(values)


@celery_app.task(name="vav.notifications.reminders")  # type: ignore[misc]
def dispatch_notification_reminders() -> dict[str, int]:
    return {"processed": asyncio.run(_dispatch_notification_reminders())}


async def _dispatch_notification_campaigns() -> int:
    async with session_factory() as session:
        campaign_ids = list(
            (
                await session.scalars(
                    text(
                        "SELECT id FROM notification_campaigns WHERE status='sending' "
                        "ORDER BY started_at NULLS LAST LIMIT 20"
                    )
                )
            ).all()
        )
    processed = 0
    for campaign_id in campaign_ids:
        async with session_factory() as session:
            result = await dispatch_campaign_batch(session, campaign_id)
            processed += int(result["queued"])
    await get_engine().dispose()
    return processed


@celery_app.task(name="vav.notifications.campaigns")  # type: ignore[misc]
def dispatch_notification_campaigns() -> dict[str, int]:
    return {"queued": asyncio.run(_dispatch_notification_campaigns())}


async def _dispatch_notification_digests() -> int:
    now = datetime.now(UTC)
    total = 0
    async with session_factory() as session:
        daily = await dispatch_digest_window(
            session, frequency="daily_digest", window_key=now.strftime("%Y-%m-%d")
        )
        total += int(daily["dispatched"])
    if now.weekday() == 0:
        async with session_factory() as session:
            weekly = await dispatch_digest_window(
                session, frequency="weekly_digest", window_key=now.strftime("%G-W%V")
            )
            total += int(weekly["dispatched"])
    await get_engine().dispose()
    return total


@celery_app.task(name="vav.notifications.digests")  # type: ignore[misc]
def dispatch_notification_digests() -> dict[str, int]:
    return {"dispatched": asyncio.run(_dispatch_notification_digests())}
