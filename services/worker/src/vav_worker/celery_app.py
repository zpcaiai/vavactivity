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
    },
)


@celery_app.task(name="vav.system.ping")  # type: ignore[misc]
def ping() -> dict[str, Any]:
    return {"status": "ok", "service": "vav-worker"}
