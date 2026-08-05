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
from vav.common.exceptions import VavError
from vav.modules.matchmaking_interactions import invitations as interaction_invitations
from vav.modules.matchmaking_interactions import (
    invalidation as interaction_invalidation,
)
from vav.modules.privacy.service import execute_erasure_plan, process_export_request
from vav.modules.recommendations import batches as recommendation_batches
from vav.modules.recommendations import service as recommendation_service
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


async def _process_privacy_exports() -> int:
    async with session_factory() as session:
        request_ids = list(
            (
                await session.scalars(
                    text(
                        "SELECT id FROM data_subject_requests WHERE request_type='export' "
                        "AND status IN ('verified','approved') ORDER BY submitted_at "
                        "FOR UPDATE SKIP LOCKED LIMIT 20"
                    )
                )
            ).all()
        )
    processed = 0
    for request_id in request_ids:
        async with session_factory() as session:
            await process_export_request(session, request_id)
            processed += 1
    await get_engine().dispose()
    return processed


@celery_app.task(name="vav.privacy.exports")  # type: ignore[misc]
def process_privacy_exports() -> dict[str, int]:
    return {"processed": asyncio.run(_process_privacy_exports())}


async def _process_privacy_erasures() -> int:
    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    text(
                        "SELECT id,approved_by FROM privacy_erasure_plans WHERE status='ready' "
                        "AND approved_by IS NOT NULL ORDER BY approved_at FOR UPDATE SKIP LOCKED LIMIT 10"
                    )
                )
            )
            .mappings()
            .all()
        )
    processed = 0
    for row in rows:
        async with session_factory() as session:
            await execute_erasure_plan(session, row["id"], actor_id=row["approved_by"])
            processed += 1
    await get_engine().dispose()
    return processed


@celery_app.task(name="vav.privacy.erasures")  # type: ignore[misc]
def process_privacy_erasures() -> dict[str, int]:
    return {"processed": asyncio.run(_process_privacy_erasures())}


async def _evaluate_privacy_retention() -> dict[str, int]:
    async with session_factory() as session:
        sources = (
            (
                "privacy.identity.profile",
                "user_profile",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM user_profiles",
            ),
            (
                "privacy.identity.contacts",
                "contact_point",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM user_contact_points",
            ),
            (
                "privacy.commerce.orders",
                "order",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM orders",
            ),
            (
                "privacy.commerce.payments",
                "payment_attempt",
                "SELECT p.id AS subject_id,o.user_id,p.created_at AS trigger_at FROM payment_attempts p JOIN orders o ON o.id=p.order_id",
            ),
            (
                "privacy.activities.registrations",
                "activity_registration",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM activity_registrations",
            ),
            (
                "privacy.courses.enrollments",
                "course_enrollment",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM course_enrollments",
            ),
            (
                "privacy.courses.certificates",
                "course_certificate",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM course_certificates",
            ),
            (
                "privacy.counseling.appointments",
                "counseling_appointment",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM counseling_appointments",
            ),
            (
                "privacy.knowledge.queries",
                "knowledge_query",
                "SELECT id AS subject_id,actor_id AS user_id,created_at AS trigger_at FROM knowledge_retrieval_queries WHERE actor_id IS NOT NULL",
            ),
            (
                "privacy.ai.conversations",
                "ai_conversation",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM ai_conversations",
            ),
            (
                "privacy.ai.memories",
                "ai_memory_item",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM ai_memory_items",
            ),
            (
                "privacy.notifications.in_app",
                "user_notification",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM user_notifications",
            ),
            (
                "privacy.notifications.deliveries",
                "notification_delivery",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM notification_deliveries",
            ),
            (
                "privacy.notifications.preferences",
                "notification_preference",
                "SELECT id AS subject_id,user_id,created_at AS trigger_at FROM notification_preferences",
            ),
        )
        materialized = 0
        for policy_code, subject_type, source_query in sources:
            values = list(
                (
                    await session.scalars(
                        text(
                            "INSERT INTO privacy_retention_instances "
                            "(policy_id,subject_type,subject_id,user_id,trigger_at,expires_at,status) "
                            f"SELECT p.id,:subject_type,s.subject_id,s.user_id,s.trigger_at,"
                            f"s.trigger_at+make_interval(days=>p.retention_days),'active' FROM ({source_query}) s "
                            "JOIN privacy_retention_policies p ON p.policy_code=:policy AND p.status='active' "
                            "WHERE p.retention_days IS NOT NULL ON CONFLICT (policy_id,subject_type,subject_id) "
                            "DO NOTHING RETURNING id"
                        ),
                        {"policy": policy_code, "subject_type": subject_type},
                    )
                ).all()
            )
            materialized += len(values)
        held = len(
            list(
                (
                    await session.scalars(
                        text(
                            "UPDATE privacy_retention_instances SET status='blocked_by_hold',evaluated_at=now(),"
                            "updated_at=now() WHERE status='active' AND expires_at<=now() AND active_hold_count>0 "
                            "RETURNING id"
                        )
                    )
                ).all()
            )
        )
        due = list(
            (
                await session.execute(
                    text(
                        "SELECT i.id,p.expiration_action FROM privacy_retention_instances i "
                        "JOIN privacy_retention_policies p ON p.id=i.policy_id "
                        "WHERE i.status='active' AND i.expires_at<=now() AND i.active_hold_count=0 "
                        "ORDER BY i.expires_at FOR UPDATE OF i SKIP LOCKED LIMIT 500"
                    )
                )
            )
            .mappings()
            .all()
        )
        for row in due:
            await session.execute(
                text(
                    "UPDATE privacy_retention_instances SET status=:status,evaluated_at=now(),"
                    "updated_at=now() WHERE id=:id"
                ),
                {
                    "id": row["id"],
                    "status": (
                        "manual_review"
                        if row["expiration_action"]
                        in {"manual_review", "retain_restricted"}
                        else "action_queued"
                    ),
                },
            )
        await session.commit()
    await get_engine().dispose()
    return {
        "materialized": materialized,
        "evaluated": len(due),
        "blocked_by_hold": held,
    }


@celery_app.task(name="vav.privacy.retention")  # type: ignore[misc]
def evaluate_privacy_retention() -> dict[str, int]:
    return asyncio.run(_evaluate_privacy_retention())


async def _expire_privacy_data() -> dict[str, int]:
    async with session_factory() as session:
        archives = len(
            list(
                (
                    await session.scalars(
                        text(
                            "UPDATE privacy_export_jobs SET archive_encrypted=NULL,download_token_hash=NULL,"
                            "status='expired',updated_at=now() WHERE archive_expires_at<=now() "
                            "AND archive_encrypted IS NOT NULL RETURNING id"
                        )
                    )
                ).all()
            )
        )
        memories = len(
            list(
                (
                    await session.scalars(
                        text(
                            "UPDATE ai_memory_items SET content_encrypted='deleted',status='deleted',"
                            "deleted_at=now(),updated_at=now() WHERE status<>'deleted' AND expires_at<=now() RETURNING id"
                        )
                    )
                ).all()
            )
        )
        await session.commit()
    await get_engine().dispose()
    return {"expired_archives": archives, "expired_memories": memories}


@celery_app.task(name="vav.privacy.expiry")  # type: ignore[misc]
def expire_privacy_data() -> dict[str, int]:
    return asyncio.run(_expire_privacy_data())


async def _sync_recommendation_pool() -> dict[str, int]:
    """Keep the recommendation pool in step with approved profile projections."""
    async with session_factory() as session:
        rebuilt = await recommendation_service.rebuild_pool(session)
        await session.commit()
    await get_engine().dispose()
    return {"rebuilt_pool_entries": rebuilt}


@celery_app.task(name="vav.recommendations.sync_pool")  # type: ignore[misc]
def sync_recommendation_pool() -> dict[str, int]:
    return asyncio.run(_sync_recommendation_pool())


async def _generate_recommendation_candidates() -> dict[str, int]:
    """Refresh candidate pairs for members whose current pairs have expired."""
    generated = 0
    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    text(
                        "SELECT p.user_id FROM recommendation_pool_entries p "
                        "WHERE p.eligible = true AND NOT EXISTS ("
                        "  SELECT 1 FROM recommendation_candidate_pairs c "
                        "  WHERE (c.user_low_id = p.user_id OR c.user_high_id = p.user_id) "
                        "  AND c.status = 'eligible' AND (c.valid_until IS NULL OR c.valid_until > now())"
                        ") LIMIT 100"
                    )
                )
            ).all()
        )
    for (user_id,) in rows:
        async with session_factory() as session:
            try:
                await recommendation_service.generate_candidates(session, user_id)
                await session.commit()
                generated += 1
            except VavError:
                await session.rollback()
    await get_engine().dispose()
    return {"members_refreshed": generated}


@celery_app.task(name="vav.recommendations.generate_candidates")  # type: ignore[misc]
def generate_recommendation_candidates() -> dict[str, int]:
    return asyncio.run(_generate_recommendation_candidates())


async def _generate_recommendation_batches() -> dict[str, int]:
    """Generate today's batch for members who do not have an active one."""
    created = 0
    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    text(
                        "SELECT p.user_id FROM recommendation_pool_entries p "
                        "LEFT JOIN recommendation_user_settings s ON s.user_id = p.user_id "
                        "WHERE p.eligible = true AND COALESCE(s.recommendations_paused, false) = false "
                        "AND NOT EXISTS ("
                        "  SELECT 1 FROM recommendation_batches b WHERE b.user_id = p.user_id "
                        "  AND b.status = 'active' AND b.batch_type = 'daily' "
                        "  AND b.period_key = to_char(now(), 'YYYY-MM-DD')"
                        ") LIMIT 200"
                    )
                )
            ).all()
        )
    for (user_id,) in rows:
        async with session_factory() as session:
            try:
                await recommendation_batches.generate_batch(session, user_id)
                await session.commit()
                created += 1
            except VavError:
                await session.rollback()
    await get_engine().dispose()
    return {"batches_created": created}


@celery_app.task(name="vav.recommendations.generate_batches")  # type: ignore[misc]
def generate_recommendation_batches() -> dict[str, int]:
    return asyncio.run(_generate_recommendation_batches())


async def _cleanup_recommendation_exposure() -> dict[str, int]:
    """Expire stale batches and drop budget rows the retention window passed."""
    async with session_factory() as session:
        expired = await recommendation_batches.expire_batches(session)
        removed = len(
            list(
                (
                    await session.scalars(
                        text(
                            "DELETE FROM recommendation_exposure_budgets "
                            "WHERE budget_date < (now() - interval '90 days')::date RETURNING user_id"
                        )
                    )
                ).all()
            )
        )
        await session.execute(
            text(
                "UPDATE recommendation_pair_exclusions SET released_at=now() "
                "WHERE released_at IS NULL AND expires_at IS NOT NULL AND expires_at <= now()"
            )
        )
        await session.commit()
    await get_engine().dispose()
    return {"expired_batches": expired, "removed_budget_rows": removed}


@celery_app.task(name="vav.recommendations.cleanup_exposure")  # type: ignore[misc]
def cleanup_recommendation_exposure() -> dict[str, int]:
    return asyncio.run(_cleanup_recommendation_exposure())


async def _aggregate_recommendation_feedback() -> dict[str, int]:
    """Mark feedback processed and invalidate candidates negative feedback removed."""
    async with session_factory() as session:
        processed = len(
            list(
                (
                    await session.scalars(
                        text(
                            "UPDATE recommendation_feedback_events SET processed_at=now() "
                            "WHERE processed_at IS NULL RETURNING id"
                        )
                    )
                ).all()
            )
        )
        await session.commit()
    await get_engine().dispose()
    return {"processed_feedback_events": processed}


@celery_app.task(name="vav.recommendations.aggregate_feedback")  # type: ignore[misc]
def aggregate_recommendation_feedback() -> dict[str, int]:
    return asyncio.run(_aggregate_recommendation_feedback())


async def _maintain_matchmaking_interactions() -> dict[str, int]:
    """Expire time-bound interaction state and fail closed on changed contacts."""
    async with session_factory() as session:
        expired_invitations = await interaction_invitations.expire_due_invitations(
            session
        )
        expired_likes = len(
            list(
                (
                    await session.scalars(
                        text(
                            "UPDATE matchmaking_likes SET status='expired' "
                            "WHERE status='active' AND expires_at<=now() RETURNING id"
                        )
                    )
                ).all()
            )
        )
        expired_skips = len(
            list(
                (
                    await session.scalars(
                        text(
                            "UPDATE matchmaking_skips SET status='expired',expired_at=now() "
                            "WHERE status='active' AND cooldown_until<=now() RETURNING id"
                        )
                    )
                ).all()
            )
        )
        invalidated_tokens = len(
            list(
                (
                    await session.scalars(
                        text(
                            "UPDATE matchmaking_contact_reveal_tokens SET status='invalidated',"
                            "invalidated_at=now() WHERE status='issued' AND expires_at<=now() RETURNING id"
                        )
                    )
                ).all()
            )
        )
        stale_owners = list(
            (
                await session.scalars(
                    text(
                        "SELECT DISTINCT g.owner_user_id FROM matchmaking_contact_exchange_grants g "
                        "JOIN LATERAL jsonb_array_elements_text(g.contact_point_ids) selected(id) ON true "
                        "LEFT JOIN user_contact_points c ON c.id=selected.id::uuid "
                        "AND c.user_id=g.owner_user_id WHERE g.status='active' AND "
                        "(c.id IS NULL OR c.status<>'verified' OR "
                        "COALESCE(g.contact_hash_snapshot->>selected.id,'')<>COALESCE(c.value_hmac,''))"
                    )
                )
            ).all()
        )
        suspended_grants = 0
        for owner_id in stale_owners:
            suspended_grants += (
                await interaction_invalidation.suspend_stale_contact_grants(
                    session, user_id=owner_id
                )
            )
        purged_idempotency = len(
            list(
                (
                    await session.scalars(
                        text(
                            "DELETE FROM matchmaking_idempotency_records "
                            "WHERE expires_at<=now() RETURNING id"
                        )
                    )
                ).all()
            )
        )
        await session.commit()
    await get_engine().dispose()
    return {
        "expired_invitations": expired_invitations,
        "expired_likes": expired_likes,
        "expired_skips": expired_skips,
        "invalidated_reveal_tokens": invalidated_tokens,
        "suspended_contact_grants": suspended_grants,
        "purged_idempotency_records": purged_idempotency,
    }


@celery_app.task(name="vav.matchmaking_interactions.maintain")  # type: ignore[misc]
def maintain_matchmaking_interactions() -> dict[str, int]:
    return asyncio.run(_maintain_matchmaking_interactions())
