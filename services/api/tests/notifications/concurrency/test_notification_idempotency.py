from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from vav.cli.seed_notification_templates import seed_notification_templates
from vav.cli.seed_notifications import seed_notifications
from vav.cli.seed_test_user import TEST_USER_EMAIL, seed_test_user
from vav.core.database import session_factory
from vav.modules.notifications import service as service_module
from vav.modules.notifications.crypto import stable_hash
from vav.modules.notifications.providers import FakeEmailProvider
from vav.modules.notifications.schemas import IngestNotificationEventRequest
from vav.modules.notifications.service import ingest_event, process_due_deliveries


@pytest.mark.asyncio
async def test_concurrent_duplicate_source_event_creates_one_intent() -> None:
    await seed_notification_templates()
    await seed_notifications()
    await seed_test_user()
    async with session_factory() as session:
        value = await session.scalar(
            text("SELECT id FROM users WHERE email=:email"), {"email": TEST_USER_EMAIL}
        )
        assert value is not None
        user_id = value
    source_id = uuid4()
    event = IngestNotificationEventRequest(
        source_event_id=source_id,
        source_module="auth",
        event_type="auth.password.changed",
        event_version=1,
        subject_type="user",
        subject_id=user_id,
        payload={"user_id": str(user_id)},
        occurred_at=datetime.now(UTC),
    )

    async def consume() -> dict[str, object]:
        async with session_factory() as session:
            return await ingest_event(session, event)

    results = await asyncio.gather(consume(), consume())
    assert sorted(str(result["status"]) for result in results) == ["duplicate", "processed"]
    async with session_factory() as session:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM notification_intents i JOIN notification_events e "
                "ON e.id=i.notification_event_id WHERE e.source_event_id=:source_id"
            ),
            {"source_id": source_id},
        )
        assert count == 1


@pytest.mark.asyncio
async def test_two_delivery_workers_send_one_provider_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_notification_templates()
    await seed_notifications()
    await seed_test_user()
    fake = FakeEmailProvider()
    monkeypatch.setattr(service_module, "configured_email_provider", lambda: fake)
    async with session_factory() as session:
        user_id = await session.scalar(
            text("SELECT id FROM users WHERE email=:email"), {"email": TEST_USER_EMAIL}
        )
        assert user_id is not None
        await session.execute(
            text(
                "UPDATE notification_deliveries SET status='cancelled' "
                "WHERE status IN ('pending','scheduled','failed_retryable')"
            )
        )
        await session.execute(
            text(
                "UPDATE notification_suppressions SET status='lifted',lifted_at=now() "
                "WHERE destination_hash=:hash AND status='active'"
            ),
            {"hash": stable_hash(TEST_USER_EMAIL)},
        )
        await session.commit()
        result = await ingest_event(
            session,
            IngestNotificationEventRequest(
                source_event_id=uuid4(),
                source_module="auth",
                event_type="auth.password.changed",
                event_version=1,
                subject_type="user",
                subject_id=user_id,
                payload={"user_id": str(user_id)},
                occurred_at=datetime.now(UTC),
            ),
        )
        assert result["intent_ids"]

    async def work() -> list[dict[str, object]]:
        async with session_factory() as session:
            return await process_due_deliveries(session, limit=1)

    await asyncio.gather(work(), work())
    assert len(fake.requests) == 1
