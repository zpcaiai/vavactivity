from __future__ import annotations

import os
from typing import Any

from celery import Celery

celery_app = Celery(
    "vav",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="vav.system.ping")  # type: ignore[misc]
def ping() -> dict[str, Any]:
    return {"status": "ok", "service": "vav-worker"}
