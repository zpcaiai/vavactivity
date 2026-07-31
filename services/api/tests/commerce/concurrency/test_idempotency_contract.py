import asyncio
import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from sqlalchemy import UniqueConstraint, func, select

from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.models.commerce import PaymentAttempt, PaymentWebhookEvent, Refund
from vav.modules.commerce.service import webhook_service


def _unique_columns(model: type[object]) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints  # type: ignore[attr-defined]
        if isinstance(constraint, UniqueConstraint)
    }


def test_provider_operations_have_database_idempotency_guards() -> None:
    assert (
        "provider",
        "provider_environment",
        "idempotency_key",
    ) in _unique_columns(PaymentAttempt)
    assert (
        "provider",
        "provider_environment",
        "provider_event_id",
    ) in _unique_columns(PaymentWebhookEvent)
    assert (
        "provider",
        "provider_environment",
        "idempotency_key",
    ) in _unique_columns(Refund)


@pytest.mark.asyncio
async def test_concurrent_duplicate_webhooks_create_one_inbox_record() -> None:
    event_id = f"evt_test_concurrent_{uuid4().hex}"
    body = json.dumps(
        {"id": event_id, "type": "provider.test.ignored", "data": {}},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        get_settings().payment_test_webhook_secret.get_secret_value().encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    async def ingest() -> PaymentWebhookEvent:
        async with session_factory() as session:
            return await webhook_service.ingest(
                session,
                provider_name="stripe",
                headers={"x-vav-test-signature": signature},
                raw_body=body,
            )

    first, second = await asyncio.gather(ingest(), ingest())
    assert first.id == second.id
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count(PaymentWebhookEvent.id)).where(
                PaymentWebhookEvent.provider_event_id == event_id
            )
        )
    assert count == 1
