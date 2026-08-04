"""Cross-user, privacy and exposure guarantees for dating profiles."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_profiles import photos as photo_processing
from vav.modules.matchmaking_profiles import review as review_service
from vav.modules.matchmaking_profiles import service
from vav.modules.matchmaking_profiles.domain import (
    PROHIBITED_PROJECTION_FIELDS,
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
async def test_a_member_cannot_edit_another_members_profile() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        intruder = await create_member(session)
        await create_complete_profile(session, owner)

        # The intruder has no profile of their own, so the write has no target.
        with pytest.raises(VavError) as error:
            await service.update_fields(session, intruder, {"faith.faith_status_code": "seeker"})
        assert error.value.code == "DATING_PROFILE_NOT_FOUND"

        # Even with their own profile, edits only ever touch their own row.
        await create_complete_profile(session, intruder)
        await service.update_fields(session, intruder, {"faith.faith_status_code": "seeker"})
        owner_profile = await service.require_profile(session, owner.id)
        owner_payload = await service.load_payload(session, owner_profile["id"])
        assert owner_payload["faith.faith_status_code"] == "believer_baptized"


@pytest.mark.asyncio
async def test_draft_profiles_are_invisible_to_other_members() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        viewer = await create_member(session)
        profile = await create_complete_profile(session, owner)
        with pytest.raises(VavError) as error:
            await service.viewer_projection(
                session,
                profile_id=profile["id"],
                viewer=viewer,
                context=DatingProfileViewContext.PROFILE_DETAIL,
            )
        assert error.value.code == "DATING_PROFILE_NOT_AVAILABLE"


@pytest.mark.asyncio
async def test_only_the_approved_version_reaches_other_members() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        viewer = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, owner)
        profile = await submit_and_approve(session, owner, reviewer)

        # An unapproved draft edit must not leak into the public view.
        await service.start_draft_revision(
            session, await service.require_profile(session, owner.id)
        )
        await session.commit()
        await service.update_narratives(
            session,
            owner,
            "zh-CN",
            {"self_introduction": SELF_INTRODUCTION + " 这是尚未审核的新内容标记 DRAFTONLY。"},
        )
        projection = await service.viewer_projection(
            session,
            profile_id=profile["id"],
            viewer=viewer,
            context=DatingProfileViewContext.PROFILE_DETAIL,
        )
        assert "DRAFTONLY" not in str(projection)


@pytest.mark.asyncio
async def test_suspended_profile_is_not_visible_and_leaves_the_pool() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        viewer = await create_member(session)
        reviewer = await create_reviewer(session, "profile_review_lead")
        await create_complete_profile(session, owner)
        profile = await submit_and_approve(session, owner, reviewer)
        await service.rebuild_projection(session, profile["id"])
        await review_service.suspend_profile(
            session, reviewer, profile["id"], reason_code="safety_review"
        )
        with pytest.raises(VavError):
            await service.viewer_projection(
                session,
                profile_id=profile["id"],
                viewer=viewer,
                context=DatingProfileViewContext.PROFILE_DETAIL,
            )
        result = await service.rebuild_projection(session, profile["id"])
        assert result["eligible"] is False


@pytest.mark.asyncio
async def test_partner_preferences_are_never_exposed_to_other_members() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        viewer = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, owner)
        profile = await submit_and_approve(session, owner, reviewer)
        for context in (
            DatingProfileViewContext.RECOMMENDATION_CARD,
            DatingProfileViewContext.PROFILE_DETAIL,
            DatingProfileViewContext.MUTUAL_MATCH,
            DatingProfileViewContext.ACTIVITY_DIRECTORY,
        ):
            projection = await service.viewer_projection(
                session, profile_id=profile["id"], viewer=viewer, context=context
            )
            serialised = str(projection)
            assert "criterion_code" not in serialised
            assert "hard_constraint" not in serialised
            assert "preference" not in serialised.casefold()


@pytest.mark.asyncio
async def test_contact_details_never_appear_in_any_member_view() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        viewer = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, owner)
        profile = await submit_and_approve(session, owner, reviewer)
        await session.execute(
            text(
                "INSERT INTO user_contact_points (user_id,contact_type,value_encrypted,value_hmac,status) "
                "VALUES (:id,'phone','encrypted','hmacvalue','verified')"
            ),
            {"id": owner.id},
        )
        await session.commit()
        for context in (
            DatingProfileViewContext.RECOMMENDATION_CARD,
            DatingProfileViewContext.PROFILE_DETAIL,
            DatingProfileViewContext.MUTUAL_MATCH,
            DatingProfileViewContext.INTRODUCTION_ACCEPTED,
        ):
            projection = await service.viewer_projection(
                session, profile_id=profile["id"], viewer=viewer, context=context
            )
            assert projection["contact_details_available"] is False
            assert owner.email not in str(projection)


@pytest.mark.asyncio
async def test_encrypted_private_summaries_never_reach_another_member() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        viewer = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, owner)
        secret = "SECRETHISTORYMARKER"
        await service.update_fields(
            session, owner, {"relationship_history.history_summary": secret}
        )
        profile = await submit_and_approve(session, owner, reviewer)
        projection = await service.viewer_projection(
            session,
            profile_id=profile["id"],
            viewer=viewer,
            context=DatingProfileViewContext.MUTUAL_MATCH,
        )
        assert secret not in str(projection)


@pytest.mark.asyncio
async def test_ai_context_is_refused_without_consent() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        viewer = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, owner)
        profile = await submit_and_approve(session, owner, reviewer)

        assert await service.ai_consent_granted(session, owner.id) is False
        with pytest.raises(VavError) as error:
            await service.viewer_projection(
                session,
                profile_id=profile["id"],
                viewer=viewer,
                context=DatingProfileViewContext.AI_CONTEXT,
            )
        assert error.value.code == "DATING_PROFILE_NOT_AVAILABLE"

        await session.execute(
            text(
                "UPDATE user_privacy_settings SET allow_profile_use_by_ai=true,"
                "settings_version=settings_version+1 WHERE user_id=:id"
            ),
            {"id": owner.id},
        )
        await session.commit()
        projection = await service.viewer_projection(
            session,
            profile_id=profile["id"],
            viewer=viewer,
            context=DatingProfileViewContext.AI_CONTEXT,
        )
        assert projection["view_context"] == "ai_context"


@pytest.mark.asyncio
async def test_rejected_photo_is_not_served_to_other_members() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        viewer = await create_member(session)
        await create_complete_profile(session, owner, with_photo=False)
        photo_id = await attach_photo(session, owner, role="primary", approve=False)
        await session.execute(
            text(
                "UPDATE dating_profile_photos SET status='rejected',rejection_reason_code='photo_not_clear' WHERE id=:id"
            ),
            {"id": photo_id},
        )
        await session.commit()
        with pytest.raises(VavError) as error:
            await service.issue_photo_view_token(
                session, viewer, photo_id, context=DatingProfileViewContext.PROFILE_DETAIL
            )
        assert error.value.code in {"DATING_PHOTO_NOT_AVAILABLE", "DATING_PHOTO_NOT_FOUND"}
        # The owner can still see their own rejected photo and the reason.
        own = await service.issue_photo_view_token(
            session, owner, photo_id, context=DatingProfileViewContext.SELF
        )
        assert own["photo_id"] == str(photo_id)


@pytest.mark.asyncio
async def test_photo_storage_keys_never_leave_the_backend() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        await create_complete_profile(session, owner)
        profile = await service.require_profile(session, owner.id)
        rows = await service.photo_rows(session, profile["id"])
        assert rows
        for row in rows:
            assert "object_key" not in row
            assert "private/dating-photos" not in str(row)


@pytest.mark.asyncio
async def test_exif_gps_data_does_not_survive_upload() -> None:
    processed = photo_processing.process_image(sample_image_bytes(with_exif=True), "image/jpeg")
    assert not photo_processing.has_exif(processed["content"])
    assert b"TestCamera" not in processed["content"]


@pytest.mark.asyncio
async def test_recommendation_projection_contains_no_prohibited_field() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, owner)
        profile = await submit_and_approve(session, owner, reviewer)
        await service.rebuild_projection(session, profile["id"])
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
        columns = set(dict(row))
        assert not columns & PROHIBITED_PROJECTION_FIELDS
        serialised = str(dict(row))
        assert owner.email not in serialised
        assert SELF_INTRODUCTION not in serialised


@pytest.mark.asyncio
async def test_review_internal_notes_are_encrypted_and_never_returned() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        reviewer = await create_reviewer(session)
        profile = await create_complete_profile(session, owner)
        await service.submit_profile(session, owner, "First")
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
        secret_note = "INTERNALONLYMARKER"
        await review_service.record_item(
            session,
            reviewer,
            case_id,
            item_type="field",
            field_code="faith.faith_status_code",
            photo_id=None,
            decision="approve",
            reason_code=None,
            user_message_safe="Looks good.",
            internal_note=secret_note,
        )
        stored = await session.scalar(
            text(
                "SELECT internal_note_encrypted FROM dating_profile_review_items WHERE review_case_id=:id LIMIT 1"
            ),
            {"id": case_id},
        )
        assert secret_note not in str(stored)

        detail = await review_service.case_detail(session, case_id, include_sensitive=False)
        assert "internal_summary_encrypted" not in detail
        feedback = await review_service.review_feedback(session, owner)
        assert secret_note not in str(feedback)


@pytest.mark.asyncio
async def test_field_visibility_override_is_enforced_by_the_backend() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        viewer = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, owner)
        profile = await submit_and_approve(session, owner, reviewer)
        await session.execute(
            text(
                "UPDATE user_field_visibility_rules SET visibility='private' "
                "WHERE user_id=:id AND field_code='basic.gender_code'"
            ),
            {"id": owner.id},
        )
        await session.commit()
        projection = await service.viewer_projection(
            session,
            profile_id=profile["id"],
            viewer=viewer,
            context=DatingProfileViewContext.PROFILE_DETAIL,
        )
        assert "basic.gender_code" not in projection["visible_fields"]


@pytest.mark.asyncio
async def test_admin_and_member_views_are_generated_separately() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        viewer = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, owner)
        profile = await submit_and_approve(session, owner, reviewer)
        admin_view = await service.viewer_projection(
            session,
            profile_id=profile["id"],
            viewer=reviewer,
            context=DatingProfileViewContext.ADMIN_REVIEW,
        )
        member_view = await service.viewer_projection(
            session,
            profile_id=profile["id"],
            viewer=viewer,
            context=DatingProfileViewContext.PROFILE_DETAIL,
        )
        # The admin view is strictly wider and is never reused for members.
        assert len(admin_view["visible_fields"]) > len(member_view["visible_fields"])
        assert admin_view["view_context"] == "admin_review"
        assert member_view["view_context"] == "profile_detail"
        assert "relationship_history.marital_status_code" in admin_view["visible_fields"]
        assert "relationship_history.marital_status_code" not in member_view["visible_fields"]


@pytest.mark.asyncio
async def test_view_token_belongs_to_the_requesting_viewer_only() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        owner = await create_member(session)
        other = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, owner)
        await submit_and_approve(session, owner, reviewer)
        photo_id = UUID(
            str(
                await session.scalar(
                    text(
                        "SELECT p.id FROM dating_profile_photos p JOIN dating_profiles d ON d.id=p.dating_profile_id "
                        "WHERE d.user_id=:id AND p.deleted_at IS NULL LIMIT 1"
                    ),
                    {"id": owner.id},
                )
            )
        )
        token = await service.issue_photo_view_token(
            session, other, photo_id, context=DatingProfileViewContext.PROFILE_DETAIL
        )
        bound_viewer = await session.scalar(
            text(
                "SELECT viewer_user_id FROM dating_profile_photo_view_tokens WHERE photo_id=:id "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"id": photo_id},
        )
        assert bound_viewer == other.id
        assert "expires_in_seconds" in token
