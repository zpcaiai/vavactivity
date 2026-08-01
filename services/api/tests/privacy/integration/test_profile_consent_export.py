# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.privacy.schemas import ProfileUpdateRequest
from vav.modules.privacy.service import (
    consume_export_download,
    create_request,
    ensure_privacy_defaults,
    grant_consent,
    inventory_for_user,
    issue_export_download_token,
    process_export_request,
    profile_view,
    update_profile,
    withdraw_consent,
)

from ..helpers import TEST_PASSWORD, create_privacy_user


@pytest.mark.asyncio
async def test_profile_defaults_strict_and_optimistic_versioning() -> None:
    async with session_factory() as session:
        user = await create_privacy_user(session)
        await ensure_privacy_defaults(session, user)
        settings = (
            (
                await session.execute(
                    text("SELECT * FROM user_privacy_settings WHERE user_id=:id"), {"id": user.id}
                )
            )
            .mappings()
            .one()
        )
        assert settings["privacy_mode"] == "strict"
        assert not settings["searchable_by_platform_users"]
        profile = await update_profile(
            session,
            user,
            ProfileUpdateRequest(display_name="Privacy User", city="Shanghai", version=1),
        )
        assert profile["display_name"] == "Privacy User"
        assert profile["version"] == 2
        with pytest.raises(VavError) as error:
            await update_profile(
                session, user, ProfileUpdateRequest(display_name="Stale", version=1)
            )
        assert error.value.code == "PRIVACY_PROFILE_VERSION_CONFLICT"


@pytest.mark.asyncio
async def test_versioned_consent_grant_and_withdraw_propagates() -> None:
    async with session_factory() as session:
        user = await create_privacy_user(session)
        await ensure_privacy_defaults(session, user)
        release_id = await session.scalar(
            text(
                "SELECT r.id FROM consent_releases r JOIN consent_definitions d ON d.id=r.consent_definition_id WHERE d.consent_code='marketing_email' AND r.locale='zh-CN' AND r.status='active'"
            )
        )
        result = await grant_consent(
            session, user.id, "marketing_email", UUID(str(release_id)), {"source": "test"}
        )
        assert result["status"] == "granted"
        withdrawn = await withdraw_consent(session, user.id, "marketing_email")
        assert "notifications.marketing_stopped" in withdrawn["propagation"]


@pytest.mark.asyncio
async def test_all_modules_inventory_and_encrypted_one_use_export() -> None:
    async with session_factory() as session:
        user = await create_privacy_user(session)
        await ensure_privacy_defaults(session, user)
        inventory = await inventory_for_user(session, user.id)
        assert {item["module_code"] for item in inventory} == {
            "identity",
            "commerce",
            "activities",
            "courses",
            "counseling",
            "knowledge",
            "ai",
            "notifications",
        }
        request_id = await create_request(
            session,
            user=user,
            request_type="export",
            requested_scope={"modules": []},
            requested_format="json",
            password=TEST_PASSWORD,
        )
        result = await process_export_request(session, request_id)
        assert result["status"] == "completed"
        token = await issue_export_download_token(session, user.id, request_id)
        archive = await consume_export_download(session, user.id, token)
        assert b"Privacy User" not in archive
        assert len(archive) > 100
        with pytest.raises(VavError) as error:
            await consume_export_download(session, user.id, token)
        assert error.value.code == "PRIVACY_EXPORT_TOKEN_INVALID"


@pytest.mark.asyncio
async def test_profile_view_never_returns_ciphertext() -> None:
    async with session_factory() as session:
        user = await create_privacy_user(session)
        await ensure_privacy_defaults(session, user)
        value = await profile_view(session, user)
        assert "legal_name_encrypted" not in value
