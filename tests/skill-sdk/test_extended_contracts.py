from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from vav_skill_sdk.events import SkillEvent
from vav_skill_sdk.idempotency import IdempotencyScope, input_digest
from vav_skill_sdk.testing import (
    FakeClock,
    FakeEventBus,
    FakeSecretProvider,
    SkillHarness,
)
from vav_skill_sdk.tracing import safe_trace_attributes


def test_idempotency_scope_binds_actor_version_and_input() -> None:
    installation_id = uuid4()
    first = IdempotencyScope(
        installation_id=installation_id,
        semantic_version="1.0.0",
        actor_reference="user:1",
        key="create-123",
        input_hash=input_digest({"a": 1, "b": 2}),
    )
    reordered = IdempotencyScope(
        installation_id=installation_id,
        semantic_version="1.0.0",
        actor_reference="user:1",
        key="create-123",
        input_hash=input_digest({"b": 2, "a": 1}),
    )
    assert first.cache_key() == reordered.cache_key()
    assert (
        first.cache_key()
        != IdempotencyScope(
            installation_id=installation_id,
            semantic_version="1.0.1",
            actor_reference="user:1",
            key="create-123",
            input_hash=first.input_hash,
        ).cache_key()
    )


@pytest.mark.asyncio
async def test_testkit_clock_events_and_secret_authority() -> None:
    clock = FakeClock(datetime(2026, 8, 6, tzinfo=UTC))
    context = SkillHarness.context(
        permissions=frozenset({"secrets.provider_key.read"}), clock=clock
    )
    clock.advance(timedelta(seconds=5))
    assert clock.now() == datetime(2026, 8, 6, 0, 0, 5, tzinfo=UTC)

    bus = FakeEventBus()
    event = SkillEvent(
        event_id=uuid4(),
        event_type="skill.completed.v1",
        occurred_at=clock.now(),
        payload={"execution_id": str(context.execution_id)},
    )
    await bus.publish(event)
    assert bus.events == [event]

    handle = await FakeSecretProvider(frozenset({"provider_key"})).issue(
        "provider_key", context
    )
    assert handle.reference == "provider_key"
    with pytest.raises(PermissionError):
        await FakeSecretProvider().issue("provider_key", context)


def test_trace_attributes_redact_sensitive_values() -> None:
    assert safe_trace_attributes(
        {"skill": "vav.example.echo", "token": "secret", "nested": {"unsafe": True}}
    ) == {"skill": "vav.example.echo", "token": "[REDACTED]"}
