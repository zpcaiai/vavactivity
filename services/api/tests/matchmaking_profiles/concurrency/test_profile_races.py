"""Races around profile creation, editing, photos, review and projections."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_profiles import photos as photo_processing
from vav.modules.matchmaking_profiles import review as review_service
from vav.modules.matchmaking_profiles import service

from ..helpers import (
    attach_photo,
    create_complete_profile,
    create_member,
    create_reviewer,
    ensure_schema_release,
    sample_image_bytes,
)


@pytest.mark.asyncio
async def test_concurrent_creation_yields_exactly_one_profile() -> None:
    async with session_factory() as setup:
        await ensure_schema_release(setup)
        user = await create_member(setup)

    async def attempt() -> str:
        async with session_factory() as session:
            try:
                await service.create_profile(session, user)
                return "created"
            except VavError as error:
                return error.code

    results = await asyncio.gather(attempt(), attempt(), attempt())
    assert results.count("created") == 1
    assert all(result in {"created", "DATING_PROFILE_ALREADY_EXISTS"} for result in results)

    async with session_factory() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM dating_profiles WHERE user_id=:id"), {"id": user.id}
        )
        assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_stale_edit_is_rejected_by_optimistic_concurrency() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        profile = await create_complete_profile(session, user)
        stale_version = profile["version"]

        await service.update_fields(session, user, {"lifestyle.travel_frequency_code": "frequent"})
        with pytest.raises(VavError) as error:
            await service.update_fields(
                session,
                user,
                {"lifestyle.travel_frequency_code": "rare"},
                expected_version=stale_version,
            )
        assert error.value.code == "DATING_PROFILE_VERSION_CONFLICT"


@pytest.mark.asyncio
async def test_concurrent_primary_photo_uploads_keep_a_single_primary() -> None:
    async with session_factory() as setup:
        await ensure_schema_release(setup)
        user = await create_member(setup)
        profile = await create_complete_profile(setup, user, with_photo=False)

    async def upload(seed: int) -> str:
        async with session_factory() as session:
            processed = photo_processing.process_image(sample_image_bytes(seed=seed), "image/jpeg")
            media_id = await session.scalar(
                text(
                    "INSERT INTO media_assets (storage_provider,bucket_name,object_key,original_filename,media_type,"
                    "mime_type,byte_size,width,height,checksum_sha256,visibility,processing_status,uploaded_by) "
                    "VALUES ('s3','vav-private',:key,'race.jpg','image','image/jpeg',:size,900,900,:checksum,'private','processed',:user_id) RETURNING id"
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
                    role="primary",
                    checksum=processed["checksum_sha256"],
                    report=processed["report"],
                )
                return "registered"
            except VavError as error:
                return error.code

    results = await asyncio.gather(*(upload(seed) for seed in range(1000, 1004)))
    assert "registered" in results

    async with session_factory() as session:
        primaries = await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_photos WHERE dating_profile_id=:id "
                "AND photo_role='primary' AND deleted_at IS NULL AND status <> 'deleted'"
            ),
            {"id": profile["id"]},
        )
        assert int(primaries or 0) == 1


@pytest.mark.asyncio
async def test_concurrent_set_primary_keeps_a_single_primary() -> None:
    async with session_factory() as setup:
        await ensure_schema_release(setup)
        user = await create_member(setup)
        profile = await create_complete_profile(setup, user)
        photo_ids = [
            await attach_photo(setup, user, role="gallery", approve=True) for _ in range(3)
        ]

    async def promote(photo_id: UUID) -> str:
        async with session_factory() as session:
            try:
                await service.set_primary_photo(session, user, photo_id)
                return "promoted"
            except VavError as error:
                return error.code

    await asyncio.gather(*(promote(photo_id) for photo_id in photo_ids))

    async with session_factory() as session:
        primaries = await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_photos WHERE dating_profile_id=:id "
                "AND photo_role='primary' AND deleted_at IS NULL AND status <> 'deleted'"
            ),
            {"id": profile["id"]},
        )
        assert int(primaries or 0) == 1


@pytest.mark.asyncio
async def test_two_reviewers_cannot_both_decide_the_same_case() -> None:
    async with session_factory() as setup:
        await ensure_schema_release(setup)
        user = await create_member(setup)
        reviewer_a = await create_reviewer(setup)
        reviewer_b = await create_reviewer(setup)
        profile = await create_complete_profile(setup, user)
        await service.submit_profile(setup, user, "First")
        case_id = UUID(
            str(
                await setup.scalar(
                    text(
                        "SELECT id FROM dating_profile_review_cases WHERE dating_profile_id=:id ORDER BY submitted_at DESC LIMIT 1"
                    ),
                    {"id": profile["id"]},
                )
            )
        )
        await review_service.start_case(setup, reviewer_a, case_id, None)
        current_version = await setup.scalar(
            text("SELECT version FROM dating_profile_review_cases WHERE id=:id"), {"id": case_id}
        )

    async def approve(reviewer: Any) -> str:
        async with session_factory() as session:
            try:
                await review_service.approve_case(
                    session,
                    reviewer,
                    case_id,
                    user_message="Approved.",
                    internal_summary=None,
                    expected_version=int(current_version or 1),
                )
                return "approved"
            except VavError as error:
                return error.code

    results = await asyncio.gather(approve(reviewer_a), approve(reviewer_b))
    assert results.count("approved") == 1
    assert "DATING_REVIEW_VERSION_CONFLICT" in results


@pytest.mark.asyncio
async def test_duplicate_projection_jobs_do_not_conflict() -> None:
    async with session_factory() as setup:
        await ensure_schema_release(setup)
        user = await create_member(setup)
        profile = await create_complete_profile(setup, user)

    async def enqueue() -> None:
        async with session_factory() as session:
            await service.queue_projection_rebuild(
                session, profile["id"], "dating_profile.privacy_updated"
            )
            await session.commit()

    await asyncio.gather(*(enqueue() for _ in range(5)))

    async with session_factory() as session:
        pending = await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_projection_jobs WHERE dating_profile_id=:id "
                "AND status='pending' AND trigger_event='dating_profile.privacy_updated'"
            ),
            {"id": profile["id"]},
        )
        assert int(pending or 0) == 1


@pytest.mark.asyncio
async def test_concurrent_projection_rebuilds_converge_on_one_row() -> None:
    async with session_factory() as setup:
        await ensure_schema_release(setup)
        user = await create_member(setup)
        reviewer = await create_reviewer(setup)
        await create_complete_profile(setup, user)
        from ..helpers import submit_and_approve

        profile = await submit_and_approve(setup, user, reviewer)

    async def rebuild() -> str:
        async with session_factory() as session:
            try:
                await service.rebuild_projection(session, profile["id"])
                return "ok"
            except Exception as error:  # noqa: BLE001
                return type(error).__name__

    await asyncio.gather(*(rebuild() for _ in range(4)))

    async with session_factory() as session:
        rows = await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_recommendation_projections WHERE dating_profile_id=:id"
            ),
            {"id": profile["id"]},
        )
        assert int(rows or 0) == 1
