# ruff: noqa: E501
from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.privacy.crypto import encrypt_private
from vav.modules.privacy.providers import provider_registry
from vav.modules.privacy.schemas import ProfileUpdateRequest
from vav.modules.privacy.service import (
    consume_export_download,
    create_request,
    ensure_privacy_defaults,
    execute_erasure_plan,
    grant_consent,
    inventory_for_user,
    issue_export_download_token,
    process_export_request,
    profile_view,
    update_profile,
    withdraw_consent,
)
from vav.modules.profile_media.domain import derive_asset_token

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
            "profile_media",
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


@pytest.mark.asyncio
async def test_profile_media_export_and_erasure_queue_physical_bytes() -> None:
    async with session_factory() as session:
        user = await create_privacy_user(session)
        asset_id = uuid4()
        token = derive_asset_token(asset_id, secret="privacy-provider-test")
        storage_key = f"profile-media/assets/{token}"
        await session.execute(
            text(
                "INSERT INTO profile_media_assets "
                "(id,owner_id,kind,state,moderation_state,position,mime_type,byte_size,"
                "access_token,storage_key,checksum_sha256) VALUES "
                "(:id,:owner_id,'photo','active','approved',1,'image/jpeg',4,:token,:key,:checksum)"
            ),
            {
                "id": asset_id,
                "owner_id": user.id,
                "token": token,
                "key": storage_key,
                "checksum": "a" * 64,
            },
        )
        await session.execute(
            text(
                "INSERT INTO profile_media_profiles "
                "(user_id,mbti,intro_encrypted,city_code) VALUES "
                "(:user_id,'INTJ',:intro,'shanghai')"
            ),
            {"user_id": user.id, "intro": encrypt_private("private introduction")},
        )
        await session.execute(
            text(
                "INSERT INTO profile_share_consents (user_id,share_enabled,share_intro) "
                "VALUES (:user_id,true,true)"
            ),
            {"user_id": user.id},
        )
        await session.commit()

        provider = provider_registry()["profile_media"]
        exported = await provider.export(session, user.id)
        assert exported["status"] == "manual_review"
        assert exported["error_code"] == "PRIVACY_EXPORT_BINARY_ATTACHMENTS_UNAVAILABLE"
        assert exported["data"]["profile"]["intro"] == "private introduction"
        assert "access_token" not in exported["data"]["assets"][0]
        assert "storage_key" not in exported["data"]["assets"][0]
        assert "checksum_sha256" not in exported["data"]["assets"][0]
        assert exported["attachment_manifest"] == {
            "binary_attachments_included": False,
            "attachment_count": 1,
            "items": [
                {
                    "asset_id": str(asset_id),
                    "mime_type": "image/jpeg",
                    "byte_size": 4,
                    "checksum_sha256": "a" * 64,
                    "checksum_status": "verified",
                    "included": False,
                }
            ],
        }

        request_id = await create_request(
            session,
            user=user,
            request_type="export",
            requested_scope={"modules": ["profile_media"]},
            requested_format="json",
            password=TEST_PASSWORD,
        )
        export_result = await process_export_request(session, request_id)
        assert export_result["status"] == "partially_completed"
        assert export_result["completed_modules"] == []
        assert export_result["failed_modules"] == [
            {
                "module_code": "profile_media",
                "status": "manual_review",
                "error_code": "PRIVACY_EXPORT_BINARY_ATTACHMENTS_UNAVAILABLE",
            }
        ]
        request_state = (
            (
                await session.execute(
                    text(
                        "SELECT r.status,r.completed_at,e.status AS export_status,"
                        "e.completed_at AS export_completed_at,m.status AS module_status,"
                        "m.result_manifest FROM data_subject_requests r "
                        "JOIN privacy_export_jobs e ON e.data_subject_request_id=r.id "
                        "JOIN privacy_module_request_results m "
                        "ON m.data_subject_request_id=r.id AND m.module_code='profile_media' "
                        "WHERE r.id=:id"
                    ),
                    {"id": request_id},
                )
            )
            .mappings()
            .one()
        )
        assert request_state["status"] == "partially_completed"
        assert request_state["completed_at"] is None
        assert request_state["export_status"] == "partially_completed"
        assert request_state["export_completed_at"] is None
        assert request_state["module_status"] == "manual_review"
        assert not request_state["result_manifest"]["complete"]
        assert (
            request_state["result_manifest"]["attachment_manifest"]["binary_attachments_included"]
            is False
        )
        with pytest.raises(VavError) as not_ready:
            await issue_export_download_token(session, user.id, request_id)
        assert not_ready.value.code == "PRIVACY_EXPORT_NOT_READY"

        erasure_request_id = await create_request(
            session,
            user=user,
            request_type="erasure",
            requested_scope={"modules": ["profile_media"]},
            password=TEST_PASSWORD,
        )
        plan_id = await session.scalar(
            text(
                "INSERT INTO privacy_erasure_plans "
                "(data_subject_request_id,user_id,status,module_plans,blocking_conditions,"
                "retention_exceptions,user_confirmation_required,planned_at,approved_by,approved_at) "
                "VALUES (:request_id,:user_id,'ready',CAST(:modules AS jsonb),'[]'::jsonb,"
                "'[]'::jsonb,false,now(),:user_id,now()) RETURNING id"
            ),
            {
                "request_id": erasure_request_id,
                "user_id": user.id,
                "modules": json.dumps([{"module_code": "profile_media", "operation": "delete"}]),
            },
        )
        await session.commit()
        assert plan_id is not None

        first_erasure = await execute_erasure_plan(session, UUID(str(plan_id)), actor_id=user.id)
        assert first_erasure["status"] == "partially_completed"
        assert first_erasure["modules"] == [
            {
                "module_code": "profile_media",
                "status": "processing",
                "affected_records": 3,
                "retained_assets": [],
                "physical_deletion": "pending",
                # The durable queue covers both the finalized object and the
                # temporary upload key, which may still contain bytes.
                "pending_physical_deletions": 2,
            }
        ]
        assert (
            await session.scalar(
                text("SELECT count(*) FROM profile_media_assets WHERE owner_id=:user_id"),
                {"user_id": user.id},
            )
            == 0
        )
        deletion = (
            (
                await session.execute(
                    text(
                        "SELECT asset_id,owner_id,storage_key,state FROM profile_media_storage_deletions "
                        "WHERE storage_key=:key"
                    ),
                    {"key": storage_key},
                )
            )
            .mappings()
            .one()
        )
        assert deletion["asset_id"] == asset_id
        assert deletion["owner_id"] == user.id
        assert deletion["state"] == "pending"

        incomplete_state = (
            (
                await session.execute(
                    text(
                        "SELECT r.status AS request_status,r.completed_at AS request_completed_at,"
                        "p.status AS plan_status,p.completed_at AS plan_completed_at,"
                        "j.status AS job_status,j.completed_at AS job_completed_at "
                        "FROM data_subject_requests r "
                        "JOIN privacy_erasure_plans p ON p.data_subject_request_id=r.id "
                        "JOIN privacy_erasure_jobs j ON j.erasure_plan_id=p.id "
                        "WHERE p.id=:id"
                    ),
                    {"id": plan_id},
                )
            )
            .mappings()
            .one()
        )
        assert incomplete_state["request_status"] == "partially_completed"
        assert incomplete_state["request_completed_at"] is None
        assert incomplete_state["plan_status"] == "partially_completed"
        assert incomplete_state["plan_completed_at"] is None
        assert incomplete_state["job_status"] == "processing"
        assert incomplete_state["job_completed_at"] is None

        await session.execute(
            text(
                "UPDATE profile_media_storage_deletions SET state='completed',completed_at=now() "
                "WHERE owner_id=:user_id"
            ),
            {"user_id": user.id},
        )
        await session.commit()
        second_erasure = await execute_erasure_plan(session, UUID(str(plan_id)), actor_id=user.id)
        assert second_erasure["status"] == "completed"
        assert second_erasure["modules"][0]["status"] == "completed"
        completed_state = (
            (
                await session.execute(
                    text(
                        "SELECT r.status AS request_status,r.completed_at AS request_completed_at,"
                        "p.status AS plan_status,p.completed_at AS plan_completed_at,"
                        "j.status AS job_status,j.completed_at AS job_completed_at "
                        "FROM data_subject_requests r "
                        "JOIN privacy_erasure_plans p ON p.data_subject_request_id=r.id "
                        "JOIN privacy_erasure_jobs j ON j.erasure_plan_id=p.id "
                        "WHERE p.id=:id"
                    ),
                    {"id": plan_id},
                )
            )
            .mappings()
            .one()
        )
        assert completed_state["request_status"] == "completed"
        assert completed_state["request_completed_at"] is not None
        assert completed_state["plan_status"] == "completed"
        assert completed_state["plan_completed_at"] is not None
        assert completed_state["job_status"] == "completed"
        assert completed_state["job_completed_at"] is not None
