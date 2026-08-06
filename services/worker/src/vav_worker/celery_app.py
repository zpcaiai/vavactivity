from __future__ import annotations

import os
from typing import Any

from celery import Celery

celery_app = Celery(
    "vav",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
    include=["vav_worker.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "publish-scheduled-content-every-minute": {
            "task": "vav.content.publish_scheduled",
            "schedule": 60.0,
        },
        "expire-inventory-reservations-every-minute": {
            "task": "vav.inventory.expire_reservations",
            "schedule": 60.0,
        },
        "reconcile-commerce-every-thirty-minutes": {
            "task": "vav.commerce.reconcile",
            "schedule": 1800.0,
        },
        "advance-activity-lifecycle-and-waitlist": {
            "task": "vav.activities.advance",
            "schedule": 60.0,
        },
        "advance-course-publication-and-completion": {
            "task": "vav.courses.advance",
            "schedule": float(
                os.getenv("COURSE_COMPLETION_JOB_INTERVAL_SECONDS", "60")
            ),
        },
        "expire-counseling-slot-holds": {
            "task": "vav.counseling.advance",
            "schedule": 60.0,
        },
        "consume-notification-outbox": {
            "task": "vav.notifications.consume_outbox",
            "schedule": 10.0,
        },
        "deliver-notifications": {
            "task": "vav.notifications.deliver",
            "schedule": 10.0,
        },
        "dispatch-notification-reminders": {
            "task": "vav.notifications.reminders",
            "schedule": float(
                os.getenv("NOTIFICATION_REMINDER_JOB_INTERVAL_SECONDS", "60")
            ),
        },
        "dispatch-notification-campaigns": {
            "task": "vav.notifications.campaigns",
            "schedule": 10.0,
        },
        "dispatch-notification-digests": {
            "task": "vav.notifications.digests",
            "schedule": 3600.0,
        },
        "process-privacy-exports": {
            "task": "vav.privacy.exports",
            "schedule": 30.0,
        },
        "process-approved-privacy-erasures": {
            "task": "vav.privacy.erasures",
            "schedule": 60.0,
        },
        "evaluate-privacy-retention": {
            "task": "vav.privacy.retention",
            "schedule": float(os.getenv("PRIVACY_RETENTION_JOB_INTERVAL_HOURS", "24"))
            * 3600.0,
        },
        "expire-privacy-archives-and-ai-memory": {
            "task": "vav.privacy.expiry",
            "schedule": 3600.0,
        },
        "sync-recommendation-pool": {
            "task": "vav.recommendations.sync_pool",
            "schedule": 300.0,
        },
        "generate-recommendation-candidates": {
            "task": "vav.recommendations.generate_candidates",
            "schedule": 900.0,
        },
        "generate-recommendation-batches": {
            "task": "vav.recommendations.generate_batches",
            "schedule": float(
                os.getenv("RECOMMENDATION_BATCH_JOB_INTERVAL_HOURS", "24")
            )
            * 3600.0,
        },
        "cleanup-recommendation-exposure": {
            "task": "vav.recommendations.cleanup_exposure",
            "schedule": 3600.0,
        },
        "aggregate-recommendation-feedback": {
            "task": "vav.recommendations.aggregate_feedback",
            "schedule": 600.0,
        },
        "maintain-matchmaking-interactions": {
            "task": "vav.matchmaking_interactions.maintain",
            "schedule": float(
                os.getenv("MATCHMAKING_INTERACTION_MAINTENANCE_INTERVAL_SECONDS", "60")
            ),
        },
        "dispatch-relationship-reminders": {
            "task": "vav.relationships.reminders",
            "schedule": float(
                os.getenv("RELATIONSHIP_REMINDER_JOB_INTERVAL_SECONDS", "60")
            ),
        },
        "release-expired-membership-quotas": {
            "task": "vav.memberships.release_expired_quotas",
            "schedule": 60.0,
        },
        "reset-membership-periodic-quotas": {
            "task": "vav.memberships.reset_periodic_quotas",
            "schedule": 300.0,
        },
        "expire-memberships": {
            "task": "vav.memberships.expire",
            "schedule": 300.0,
        },
        "reconcile-memberships": {
            "task": "vav.memberships.reconcile",
            "schedule": float(
                os.getenv("MEMBERSHIP_RECONCILIATION_INTERVAL_MINUTES", "30")
            )
            * 60.0,
        },
        "expire-safety-restrictions": {
            "task": "vav.safety.expire_restrictions",
            "schedule": float(
                os.getenv("SAFETY_RESTRICTION_EXPIRY_JOB_INTERVAL_MINUTES", "10")
            )
            * 60.0,
        },
        "escalate-overdue-safety-cases": {
            "task": "vav.safety.escalate_cases",
            "schedule": 60.0,
        },
        "execute-queued-skills": {
            "task": "vav.skills.execute",
            "schedule": 1.0,
        },
    },
)


@celery_app.task(name="vav.system.ping")  # type: ignore[misc]
def ping() -> dict[str, Any]:
    return {"status": "ok", "service": "vav-worker"}
