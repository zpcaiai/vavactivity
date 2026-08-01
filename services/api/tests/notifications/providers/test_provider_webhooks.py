# ruff: noqa: E501
from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.cli.seed_notification_templates import seed_notification_templates
from vav.cli.seed_notifications import seed_notifications
from vav.cli.seed_test_user import TEST_USER_EMAIL, seed_test_user
from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.modules.notifications import service as service_module
from vav.modules.notifications.crypto import stable_hash
from vav.modules.notifications.providers import FakeEmailProvider
from vav.modules.notifications.schemas import IngestNotificationEventRequest
from vav.modules.notifications.service import (
    ingest_event,
    process_due_deliveries,
    receive_provider_webhook,
)


@pytest.mark.asyncio
async def test_signed_hard_bounce_webhook_is_idempotent_and_suppresses(
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
        await ingest_event(
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
        values = await process_due_deliveries(session, limit=1)
        assert values and values[0]["status"] == "sent"
        delivery = (
            (
                await session.execute(
                    text(
                        "SELECT id,provider_message_id,destination_hash FROM notification_deliveries "
                        "WHERE id=:id"
                    ),
                    {"id": UUID(values[0]["delivery_id"])},
                )
            )
            .mappings()
            .one()
        )
        raw = json.dumps(
            {
                "event_id": f"bounce-{uuid4()}",
                "event_type": "hard_bounce",
                "provider_message_id": delivery["provider_message_id"],
            }
        ).encode()
        secret = get_settings().notification_email_provider_webhook_secret.get_secret_value()
        headers = {"x-vav-notification-secret": secret}
        first = await receive_provider_webhook(
            session, provider_name="fake", headers=headers, raw_body=raw
        )
        second = await receive_provider_webhook(
            session, provider_name="fake", headers=headers, raw_body=raw
        )
        assert first["status"] == "processed"
        assert second["status"] == "duplicate"
        count = await session.scalar(
            text(
                "SELECT count(*) FROM notification_suppressions WHERE destination_hash=:hash "
                "AND suppression_reason='hard_bounce' AND status='active'"
            ),
            {"hash": delivery["destination_hash"]},
        )
        assert count == 1


@pytest.mark.asyncio
async def test_invalid_webhook_signature_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEmailProvider()
    monkeypatch.setattr(service_module, "configured_email_provider", lambda: fake)
    async with session_factory() as session:
        with pytest.raises(VavError) as error:
            await receive_provider_webhook(
                session,
                provider_name="fake",
                headers={"x-vav-notification-secret": "wrong"},
                raw_body=b'{"event_id":"x-123","event_type":"delivered"}',
            )
        assert error.value.code == "NOTIFICATION_WEBHOOK_SIGNATURE_INVALID"
