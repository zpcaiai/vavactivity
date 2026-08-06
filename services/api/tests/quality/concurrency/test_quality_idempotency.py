from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.quality import service
from vav.modules.quality.schemas import CapabilityCreate


async def _operator() -> UUID:
    async with session_factory() as session:
        email = f"quality-concurrency-{uuid4().hex}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("QualityConcurrency!2026"),
            status="active",
            email_verified_at=datetime.now(UTC),
            preferred_locale="en",
            timezone="UTC",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest.mark.asyncio
async def test_concurrent_capability_sync_is_idempotent() -> None:
    actor = await _operator()
    code = f"CAP-QUALITY-CONCURRENT-{uuid4().hex[:8].upper()}"
    payload = CapabilityCreate(
        capability_code=code,
        name="Concurrent inventory synchronization",
        description="Two scanners converge on exactly one capability record.",
        capability_type="system_process",
        module_code="quality",
        criticality="critical",
        lifecycle_status="available",
        owning_service="quality_sync",
        owner_team="quality_engineering",
    )

    async def upsert() -> dict[str, object]:
        async with session_factory() as session:
            return await service.upsert_capability(session, actor, payload)

    first, second = await asyncio.gather(upsert(), upsert())
    assert first["id"] == second["id"]
    async with session_factory() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM quality_capabilities WHERE capability_code=:code"),
            {"code": code},
        )
    assert count == 1
