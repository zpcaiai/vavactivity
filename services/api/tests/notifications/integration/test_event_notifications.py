# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.cli.seed_notification_templates import seed_notification_templates
from vav.cli.seed_notifications import seed_notifications
from vav.cli.seed_test_user import TEST_USER_EMAIL, seed_test_user
from vav.core.database import session_factory
from vav.modules.notifications.crypto import stable_hash
from vav.modules.notifications.schemas import IngestNotificationEventRequest
from vav.modules.notifications.service import ingest_event


async def seeded() -> None:
    await seed_notification_templates()
    await seed_notifications()
    await seed_test_user()


async def active_user_id() -> UUID:
    async with session_factory() as session:
        value = await session.scalar(
            text("SELECT id FROM users WHERE email=:email"), {"email": TEST_USER_EMAIL}
        )
        assert value is not None
        return UUID(str(value))


@pytest.mark.asyncio
async def test_versioned_event_creates_intent_in_app_and_email_delivery_once() -> None:
    await seeded()
    user_id = await active_user_id()
    source_event_id = uuid4()
    event = IngestNotificationEventRequest(
        source_event_id=source_event_id,
        source_module="auth",
        event_type="auth.password.changed",
        event_version=1,
        subject_type="user",
        subject_id=user_id,
        payload={
            "user_id": str(user_id),
            "action_reference": {"route_name": "account-security", "params": {}},
        },
        occurred_at=datetime.now(UTC),
    )
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE notification_suppressions SET status='lifted',lifted_at=now() "
                "WHERE destination_hash=:hash AND status='active'"
            ),
            {"hash": stable_hash(TEST_USER_EMAIL)},
        )
        await session.commit()
        result = await ingest_event(session, event)
        assert result["status"] == "processed"
        assert len(result["intent_ids"]) == 1
        intent_id = UUID(result["intent_ids"][0])
        counts = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM user_notifications WHERE notification_intent_id=:id),"
                    "(SELECT count(*) FROM notification_deliveries WHERE notification_intent_id=:id)"
                ),
                {"id": intent_id},
            )
        ).one()
        assert counts == (1, 1)
        duplicate = await ingest_event(session, event)
        assert duplicate["status"] == "duplicate"
        assert duplicate["intent_ids"] == []


@pytest.mark.asyncio
async def test_unknown_event_version_is_preserved_in_dead_letter() -> None:
    await seeded()
    user_id = await active_user_id()
    async with session_factory() as session:
        result = await ingest_event(
            session,
            IngestNotificationEventRequest(
                source_event_id=uuid4(),
                source_module="auth",
                event_type="auth.password.changed",
                event_version=99,
                subject_type="user",
                subject_id=user_id,
                payload={"user_id": str(user_id)},
                occurred_at=datetime.now(UTC),
            ),
        )
        assert result["status"] == "dead_letter"
        row = (
            await session.execute(
                text(
                    "SELECT e.processing_status,d.error_code FROM notification_events e "
                    "JOIN notification_dead_letters d ON d.source_id=e.id WHERE e.id=:id"
                ),
                {"id": UUID(result["event_id"])},
            )
        ).one()
        assert row == ("dead_letter", "UNKNOWN_EVENT_VERSION")


@pytest.mark.asyncio
async def test_active_template_release_is_immutable() -> None:
    await seeded()
    async with session_factory() as session:
        release_id = await session.scalar(
            text("SELECT id FROM notification_template_releases WHERE status='active' LIMIT 1")
        )
        assert release_id is not None
        with pytest.raises(Exception, match="immutable"):
            await session.execute(
                text(
                    "UPDATE notification_template_releases SET body_text_template='changed' WHERE id=:id"
                ),
                {"id": release_id},
            )
            await session.flush()
        await session.rollback()
