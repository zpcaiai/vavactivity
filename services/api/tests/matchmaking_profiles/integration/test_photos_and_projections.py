"""Photo processing, review, preferences and recommendation projections."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_profiles import photos as photo_processing
from vav.modules.matchmaking_profiles import review as review_service
from vav.modules.matchmaking_profiles import service
from vav.modules.matchmaking_profiles.domain import (
    DatingPhotoRole,
    DatingPhotoStatus,
    DatingProfileViewContext,
)

from ..helpers import (
    SELF_INTRODUCTION,
    attach_photo,
    create_complete_profile,
    create_member,
    create_reviewer,
    ensure_schema_release,
    sample_image_bytes,
    submit_and_approve,
)


@pytest.mark.asyncio
async def test_exif_metadata_is_removed_during_processing() -> None:
    original = sample_image_bytes(with_exif=True)
    assert photo_processing.has_exif(original)
    processed = photo_processing.process_image(original, "image/jpeg")
    assert processed["report"]["exif_present_before_processing"] is True
    assert processed["report"]["metadata_stripped"] is True
    assert not photo_processing.has_exif(processed["content"])
    assert processed["report"]["biometric_template_created"] is False


def test_spoofed_mime_type_is_rejected() -> None:
    png_bytes = sample_image_bytes(fmt="PNG")
    with pytest.raises(VavError) as error:
        photo_processing.process_image(png_bytes, "image/jpeg")
    assert error.value.code == "DATING_PHOTO_TYPE_MISMATCH"


def test_non_image_content_is_rejected() -> None:
    with pytest.raises(VavError) as error:
        photo_processing.process_image(b"#!/bin/sh\necho not-an-image\n", "image/jpeg")
    assert error.value.code == "DATING_PHOTO_NOT_DECODABLE"


def test_oversized_upload_is_rejected() -> None:
    with pytest.raises(VavError) as error:
        photo_processing.validate_upload_request("image/jpeg", 50 * 1024 * 1024)
    assert error.value.code == "DATING_PHOTO_TOO_LARGE"


def test_unsupported_type_is_rejected() -> None:
    with pytest.raises(VavError) as error:
        photo_processing.validate_upload_request("image/gif", 1024)
    assert error.value.code == "DATING_PHOTO_TYPE_NOT_ALLOWED"


def test_tiny_image_is_rejected() -> None:
    with pytest.raises(VavError) as error:
        photo_processing.process_image(sample_image_bytes(size=(64, 64)), "image/jpeg")
    assert error.value.code == "DATING_PHOTO_RESOLUTION_TOO_LOW"


@pytest.mark.asyncio
async def test_uploaded_photo_waits_for_review_and_only_one_stays_primary() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        await create_complete_profile(session, user, with_photo=False)
        first = await attach_photo(session, user, role="primary", approve=False)
        status = await session.scalar(
            text("SELECT status FROM dating_profile_photos WHERE id=:id"), {"id": first}
        )
        assert status == DatingPhotoStatus.REVIEW_REQUIRED.value

        second = await attach_photo(session, user, role="primary", approve=False)
        profile = await service.require_profile(session, user.id)
        primaries = await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_photos WHERE dating_profile_id=:id "
                "AND photo_role='primary' AND deleted_at IS NULL"
            ),
            {"id": profile["id"]},
        )
        assert int(primaries or 0) == 1
        current = await session.scalar(
            text("SELECT photo_role FROM dating_profile_photos WHERE id=:id"), {"id": second}
        )
        assert current == DatingPhotoRole.PRIMARY.value


@pytest.mark.asyncio
async def test_duplicate_photo_upload_is_rejected() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        await create_complete_profile(session, user, with_photo=False)
        processed = photo_processing.process_image(sample_image_bytes(seed=99), "image/jpeg")
        profile = await service.require_profile(session, user.id)
        for _ in range(2):
            media_id = await session.scalar(
                text(
                    "INSERT INTO media_assets (storage_provider,bucket_name,object_key,original_filename,media_type,"
                    "mime_type,byte_size,width,height,checksum_sha256,visibility,processing_status,uploaded_by) "
                    "VALUES ('s3','vav-private',:key,'d.jpg','image','image/jpeg',:size,900,900,:checksum,'private','processed',:user_id) RETURNING id"
                ),
                {
                    "key": f"private/dating-photos/{profile['id']}/{uuid4()}.jpg",
                    "size": processed["byte_size"],
                    "checksum": processed["checksum_sha256"],
                    "user_id": user.id,
                },
            )
            await session.commit()
            try:
                await service.register_photo(
                    session,
                    user,
                    media_asset_id=UUID(str(media_id)),
                    role="gallery",
                    checksum=processed["checksum_sha256"],
                    report=processed["report"],
                )
            except VavError as error:
                assert error.code == "DATING_PHOTO_DUPLICATE"
                return
        pytest.fail("the second identical upload should have been rejected")


@pytest.mark.asyncio
async def test_photo_review_approves_and_rejects_with_reason_codes() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        profile = await create_complete_profile(session, user, with_photo=False)
        photo_id = await attach_photo(session, user, role="primary", approve=False)
        await service.submit_profile(session, user, "First")
        case_id = UUID(
            str(
                await session.scalar(
                    text(
                        "SELECT id FROM dating_profile_review_cases WHERE dating_profile_id=:id ORDER BY submitted_at DESC LIMIT 1"
                    ),
                    {"id": profile["id"]},
                )
            )
        )
        await review_service.start_case(session, reviewer, case_id, None)

        with pytest.raises(VavError) as error:
            await review_service.record_item(
                session,
                reviewer,
                case_id,
                item_type="photo",
                field_code=None,
                photo_id=photo_id,
                decision="reject",
                reason_code="not_a_real_reason",
                user_message_safe="Please upload a different photo.",
                internal_note=None,
            )
        assert error.value.code == "DATING_REVIEW_REASON_INVALID"

        await review_service.record_item(
            session,
            reviewer,
            case_id,
            item_type="photo",
            field_code=None,
            photo_id=photo_id,
            decision="approve",
            reason_code=None,
            user_message_safe=None,
            internal_note=None,
        )
        status = await session.scalar(
            text("SELECT status FROM dating_profile_photos WHERE id=:id"), {"id": photo_id}
        )
        assert status == DatingPhotoStatus.APPROVED.value


@pytest.mark.asyncio
async def test_deleting_a_photo_revokes_outstanding_view_tokens() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        await create_complete_profile(session, user)
        photo_id = await session.scalar(
            text(
                "SELECT p.id FROM dating_profile_photos p JOIN dating_profiles d ON d.id=p.dating_profile_id "
                "WHERE d.user_id=:id AND p.deleted_at IS NULL LIMIT 1"
            ),
            {"id": user.id},
        )
        token = await service.issue_photo_view_token(
            session, user, UUID(str(photo_id)), context=DatingProfileViewContext.SELF
        )
        assert "token=" in token["view_url"]
        # The storage object key never appears in the response.
        assert "private/dating-photos" not in token["view_url"]

        await service.delete_photo(session, user, UUID(str(photo_id)))
        revoked = await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_photo_view_tokens WHERE photo_id=:id AND revoked_at IS NOT NULL"
            ),
            {"id": photo_id},
        )
        assert int(revoked or 0) >= 1


@pytest.mark.asyncio
async def test_preferences_are_stored_privately_with_hard_constraint_summary() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        await create_complete_profile(session, user)
        result = await service.replace_preferences(
            session,
            user,
            [
                {
                    "criterion_code": "age_range",
                    "operator": "range",
                    "desired_value": {"minimum": 30, "maximum": 42},
                    "importance": "required",
                    "hard_constraint": True,
                    "allow_unknown": False,
                },
                {
                    "criterion_code": "faith_status_code",
                    "operator": "in",
                    "desired_value": ["believer_baptized"],
                    "importance": "very_important",
                    "hard_constraint": False,
                },
            ],
            allow_relaxation=False,
        )
        assert result["visibility"] == "private_to_owner_and_recommendation_engine"
        assert [item["criterion_code"] for item in result["hard_constraints"]] == ["age_range"]
        assert result["allow_recommendation_relaxation"] is False
        # The system never quietly relaxes a hard criterion.
        assert all(not item["may_be_relaxed_by_system"] for item in result["hard_constraints"])


@pytest.mark.asyncio
async def test_projection_is_built_for_an_active_profile_and_excludes_narratives() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, user)
        profile = await submit_and_approve(session, user, reviewer)
        result = await service.rebuild_projection(session, profile["id"])
        assert result["eligible"], result

        row = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM dating_profile_recommendation_projections WHERE dating_profile_id=:id"
                    ),
                    {"id": profile["id"]},
                )
            )
            .mappings()
            .one()
        )
        assert row["eligible"] is True
        assert row["approved_profile_version"] == 1
        assert row["age_bucket"] is not None
        serialised = str(dict(row))
        assert SELF_INTRODUCTION not in serialised
        assert user.email not in serialised


@pytest.mark.asyncio
async def test_pausing_removes_the_profile_from_the_recommendation_pool() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, user)
        profile = await submit_and_approve(session, user, reviewer)
        await service.rebuild_projection(session, profile["id"])

        await review_service.pause_profile(session, user)
        result = await service.rebuild_projection(session, profile["id"])
        assert result["eligible"] is False
        assert "profile_not_active" in result["reason_codes"]
        remaining = await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_recommendation_projections WHERE dating_profile_id=:id"
            ),
            {"id": profile["id"]},
        )
        assert int(remaining or 0) == 0


@pytest.mark.asyncio
async def test_withdrawing_matchmaking_visibility_removes_the_projection() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, user)
        profile = await submit_and_approve(session, user, reviewer)
        await service.rebuild_projection(session, profile["id"])

        await session.execute(
            text(
                "UPDATE user_privacy_settings SET visible_in_matchmaking=false,settings_version=settings_version+1 WHERE user_id=:id"
            ),
            {"id": user.id},
        )
        await session.commit()
        result = await service.rebuild_projection(session, profile["id"])
        assert result["eligible"] is False
        assert "matchmaking_visibility_not_granted" in result["reason_codes"]


@pytest.mark.asyncio
async def test_repeated_rebuilds_are_idempotent() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, user)
        profile = await submit_and_approve(session, user, reviewer)
        first = await service.rebuild_projection(session, profile["id"])
        second = await service.rebuild_projection(session, profile["id"])
        assert first["checksum"] == second["checksum"]
        version = await session.scalar(
            text(
                "SELECT projection_version FROM dating_profile_recommendation_projections WHERE dating_profile_id=:id"
            ),
            {"id": profile["id"]},
        )
        assert int(version or 0) == 1


@pytest.mark.asyncio
async def test_queued_projection_jobs_collapse_and_drain() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, user)
        profile = await submit_and_approve(session, user, reviewer)
        for _ in range(3):
            await service.queue_projection_rebuild(
                session, profile["id"], "dating_profile.privacy_updated"
            )
        await session.commit()
        pending = await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_projection_jobs WHERE dating_profile_id=:id "
                "AND status='pending' AND trigger_event='dating_profile.privacy_updated'"
            ),
            {"id": profile["id"]},
        )
        assert int(pending or 0) == 1
        result = await service.process_projection_jobs(session)
        assert result["processed"] >= 1
