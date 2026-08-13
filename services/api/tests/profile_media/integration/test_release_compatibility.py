"""Database compatibility between migration 0112 and a pre-0112 API."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.privacy.helpers import create_privacy_user
from vav.core.database import session_factory


@pytest.mark.asyncio
async def test_old_binary_writes_receive_a_legacy_storage_binding() -> None:
    """Replay the old register/finalize SQL against the expanded schema.

    The old binary creates the row with an empty token, assigns the token in a
    second statement, and never mentions storage_key. The migration trigger
    must bind that row before the active-storage CHECK is evaluated.
    """

    token = "A" * 26
    async with session_factory() as session:
        user = await create_privacy_user(session)
        asset_id = await session.scalar(
            text(
                "INSERT INTO profile_media_assets "
                "(owner_id,kind,state,moderation_state,position,mime_type,"
                "byte_size,duration_seconds,access_token) "
                "VALUES (:owner_id,'photo','uploading','pending',1,'image/jpeg',"
                "1024,NULL,'') RETURNING id"
            ),
            {"owner_id": str(user.id)},
        )
        await session.execute(
            text("UPDATE profile_media_assets SET access_token=:token WHERE id=:id"),
            {"token": token, "id": str(asset_id)},
        )
        binding = (
            (
                await session.execute(
                    text(
                        "SELECT storage_key,upload_expires_at "
                        "FROM profile_media_assets WHERE id=:id"
                    ),
                    {"id": str(asset_id)},
                )
            )
            .mappings()
            .one()
        )
        assert binding["storage_key"] == f"profile-media/{token}"
        assert binding["upload_expires_at"] is not None

        # This is the exact transition that failed before the compatibility
        # trigger: old SQL does not assign storage_key while making it active.
        await session.execute(
            text("UPDATE profile_media_assets SET state='active',updated_at=now() WHERE id=:id"),
            {"id": str(asset_id)},
        )
        await session.commit()
        assert (
            await session.scalar(
                text("SELECT state FROM profile_media_assets WHERE id=:id"),
                {"id": str(asset_id)},
            )
            == "active"
        )


@pytest.mark.asyncio
async def test_new_binary_explicit_storage_binding_is_not_rewritten() -> None:
    token = "B" * 26
    explicit_key = f"profile-media/uploads/{token}"
    async with session_factory() as session:
        user = await create_privacy_user(session)
        stored_key = await session.scalar(
            text(
                "INSERT INTO profile_media_assets "
                "(owner_id,kind,state,moderation_state,position,mime_type,"
                "byte_size,duration_seconds,access_token,storage_key) "
                "VALUES (:owner_id,'photo','uploading','pending',1,'image/jpeg',"
                "1024,NULL,:token,:storage_key) RETURNING storage_key"
            ),
            {
                "owner_id": str(user.id),
                "token": token,
                "storage_key": explicit_key,
            },
        )
        await session.rollback()
        assert stored_key == explicit_key
