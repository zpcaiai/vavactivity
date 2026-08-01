# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.privacy.crypto import encrypt_private
from vav.modules.privacy.service import erasure_blockers, request_number

from ..helpers import create_privacy_user


@pytest.mark.asyncio
async def test_active_hold_blocks_erasure_and_release_resumes() -> None:
    async with session_factory() as session:
        user = await create_privacy_user(session)
        user_id = user.id
        authorizer = await create_privacy_user(session)
        authorizer_id = authorizer.id
        hold_id = await session.scalar(
            text(
                "INSERT INTO privacy_legal_holds (hold_number,hold_type,status,scope_definition_encrypted,reason_encrypted,authorized_by,created_by,starts_at,ends_at) VALUES (:number,'legal','active',:scope,:reason,:authorized,:creator,now(),:ends) RETURNING id"
            ),
            {
                "number": request_number("HLD"),
                "scope": encrypt_private(
                    {"subject_user_id": str(user_id), "module_codes": ["identity"]}
                ),
                "reason": encrypt_private("Valid test legal hold"),
                "authorized": authorizer_id,
                "creator": user_id,
                "ends": datetime.now(UTC) + timedelta(days=1),
            },
        )
        await session.commit()
        blockers = await erasure_blockers(session, user_id)
        assert any(item["code"] == "active_hold" for item in blockers)
        await session.execute(
            text(
                "UPDATE privacy_legal_holds SET status='released',released_at=now(),released_by=:actor WHERE id=:id"
            ),
            {"actor": authorizer_id, "id": UUID(str(hold_id))},
        )
        await session.commit()
        blockers = await erasure_blockers(session, user_id)
        assert not any(item["code"] == "active_hold" for item in blockers)


@pytest.mark.asyncio
async def test_sensitive_assets_have_finite_retention_policies() -> None:
    async with session_factory() as session:
        missing = await session.scalar(
            text(
                "SELECT count(*) FROM privacy_data_assets a LEFT JOIN privacy_retention_policies p ON p.policy_code=a.retention_policy_code AND p.status='active' WHERE a.sensitivity IN ('restricted','highly_restricted') AND (p.id IS NULL OR p.retention_days IS NULL)"
            )
        )
        assert missing == 0
