"""Submission, immutable versions and the review workflow."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_profiles import review as review_service
from vav.modules.matchmaking_profiles import service
from vav.modules.matchmaking_profiles.domain import DatingProfileStatus
from vav.modules.privacy.crypto import decrypt_private

from ..helpers import (
    SELF_INTRODUCTION,
    create_complete_profile,
    create_member,
    create_reviewer,
    ensure_schema_release,
    submit_and_approve,
)


async def _open_case(session, profile_id) -> UUID:  # type: ignore[no-untyped-def]
    case_id = await session.scalar(
        text(
            "SELECT id FROM dating_profile_review_cases WHERE dating_profile_id=:id "
            "ORDER BY submitted_at DESC LIMIT 1"
        ),
        {"id": profile_id},
    )
    return UUID(str(case_id))


@pytest.mark.asyncio
async def test_incomplete_profile_cannot_be_submitted() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        await service.create_profile(session, user)
        with pytest.raises(VavError) as error:
            await service.submit_profile(session, user, "Too early")
        assert error.value.code == "DATING_PROFILE_NOT_SUBMITTABLE"
        assert error.value.details[0]["missing_required_fields"]


@pytest.mark.asyncio
async def test_submission_creates_an_immutable_version_and_a_review_case() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        profile = await create_complete_profile(session, user)
        result = await service.submit_profile(session, user, "First submission")
        assert result["status"] == DatingProfileStatus.SUBMITTED.value

        version = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM dating_profile_versions WHERE dating_profile_id=:id ORDER BY version_number DESC LIMIT 1"
                    ),
                    {"id": profile["id"]},
                )
            )
            .mappings()
            .one()
        )
        assert version["submitted_at"] is not None
        assert len(version["snapshot_checksum_sha256"]) == 64
        # The stored snapshot is encrypted at rest.
        assert SELF_INTRODUCTION not in str(version["snapshot_encrypted"])
        snapshot = decrypt_private(str(version["snapshot_encrypted"]))
        assert snapshot["fields"]["self_introduction.self_introduction"] == SELF_INTRODUCTION

        # A submitted version cannot be rewritten, even directly in SQL.
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "UPDATE dating_profile_versions SET snapshot_checksum_sha256='0' WHERE id=:id"
                ),
                {"id": version["id"]},
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_double_submission_of_the_same_version_is_rejected() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        await create_complete_profile(session, user)
        await service.submit_profile(session, user, "First")
        with pytest.raises(VavError) as error:
            await service.submit_profile(session, user, "Again")
        assert error.value.code in {
            "DATING_PROFILE_ALREADY_SUBMITTED",
            "DATING_PROFILE_NOT_SUBMITTABLE",
        }


@pytest.mark.asyncio
async def test_approval_activates_the_profile_atomically() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, user)
        profile = await submit_and_approve(session, user, reviewer)
        assert profile["status"] == DatingProfileStatus.ACTIVE.value
        assert profile["approved_version_number"] == 1
        assert profile["searchable"] is True
        assert profile["review_status"] == "approved"


@pytest.mark.asyncio
async def test_request_changes_returns_field_level_feedback_and_opens_a_draft() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        profile = await create_complete_profile(session, user)
        await service.submit_profile(session, user, "First")
        case_id = await _open_case(session, profile["id"])
        await review_service.start_case(session, reviewer, case_id, None)
        await review_service.record_item(
            session,
            reviewer,
            case_id,
            item_type="field",
            field_code="self_introduction.self_introduction",
            photo_id=None,
            decision="changes_required",
            reason_code="needs_more_detail",
            user_message_safe="Please describe your church involvement in more detail.",
            internal_note="Reviewer note that the member must never see.",
        )
        await review_service.request_changes(
            session,
            reviewer,
            case_id,
            user_message="A few sections need more detail.",
            internal_summary="Internal only.",
            expected_version=None,
        )
        feedback = await review_service.review_feedback(session, user)
        assert feedback["has_feedback"]
        assert feedback["overall_decision"] == "changes_required"
        assert feedback["items"][0]["field_code"] == "self_introduction.self_introduction"
        serialised = str(feedback)
        assert "Reviewer note that the member must never see." not in serialised
        assert "Internal only." not in serialised

        # A new draft version is opened so the previous version stays intact.
        refreshed = await service.require_profile(session, user.id)
        assert refreshed["current_version_number"] == 2


@pytest.mark.asyncio
async def test_rejection_and_suspension_require_reasons() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session, "profile_review_lead")
        profile = await create_complete_profile(session, user)
        await service.submit_profile(session, user, "First")
        case_id = await _open_case(session, profile["id"])
        await review_service.start_case(session, reviewer, case_id, None)
        with pytest.raises(VavError) as error:
            await review_service.reject_case(
                session,
                reviewer,
                case_id,
                reason_code="   ",
                user_message="Rejected.",
                internal_summary=None,
                expected_version=None,
            )
        assert error.value.code == "DATING_REVIEW_REASON_REQUIRED"


@pytest.mark.asyncio
async def test_blocking_items_prevent_approval() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        profile = await create_complete_profile(session, user)
        await service.submit_profile(session, user, "First")
        case_id = await _open_case(session, profile["id"])
        await review_service.start_case(session, reviewer, case_id, None)
        await review_service.record_item(
            session,
            reviewer,
            case_id,
            item_type="field",
            field_code="faith.faith_status_code",
            photo_id=None,
            decision="reject",
            reason_code="unclear_value",
            user_message_safe="Please review this answer.",
            internal_note=None,
        )
        with pytest.raises(VavError) as error:
            await review_service.approve_case(
                session,
                reviewer,
                case_id,
                user_message=None,
                internal_summary=None,
                expected_version=None,
            )
        assert error.value.code == "DATING_REVIEW_HAS_BLOCKING_ITEMS"


@pytest.mark.asyncio
async def test_decisions_cannot_be_recorded_before_the_case_starts() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        profile = await create_complete_profile(session, user)
        await service.submit_profile(session, user, "First")
        case_id = await _open_case(session, profile["id"])
        with pytest.raises(VavError) as error:
            await review_service.record_item(
                session,
                reviewer,
                case_id,
                item_type="field",
                field_code="faith.faith_status_code",
                photo_id=None,
                decision="approve",
                reason_code=None,
                user_message_safe=None,
                internal_note=None,
            )
        assert error.value.code == "DATING_REVIEW_NOT_STARTED"


@pytest.mark.asyncio
async def test_pause_and_reactivate_round_trip() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, user)
        await submit_and_approve(session, user, reviewer)
        paused = await review_service.pause_profile(session, user)
        assert paused["status"] == DatingProfileStatus.PAUSED_BY_USER.value
        resumed = await review_service.reactivate_profile(session, user)
        assert resumed["status"] == DatingProfileStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_suspend_and_restore_are_audited() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session, "profile_review_lead")
        await create_complete_profile(session, user)
        profile = await submit_and_approve(session, user, reviewer)
        await review_service.suspend_profile(
            session, reviewer, profile["id"], reason_code="safety_review"
        )
        suspended = await service.require_profile(session, user.id)
        assert suspended["status"] == DatingProfileStatus.SUSPENDED.value
        assert suspended["searchable"] is False

        await review_service.restore_profile(session, reviewer, profile["id"], reason="Cleared")
        restored = await service.require_profile(session, user.id)
        assert restored["status"] == DatingProfileStatus.ACTIVE.value

        events = (
            (
                await session.execute(
                    text(
                        "SELECT event_type FROM matchmaking_audit_events WHERE subject_id=:id ORDER BY created_at"
                    ),
                    {"id": profile["id"]},
                )
            )
            .scalars()
            .all()
        )
        assert "matchmaking.profile.suspended" in events
        assert "matchmaking.profile.restored" in events


@pytest.mark.asyncio
async def test_version_diff_reports_changed_fields() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        profile = await create_complete_profile(session, user)
        await submit_and_approve(session, user, reviewer)
        await service.start_draft_revision(session, await service.require_profile(session, user.id))
        await session.commit()
        await service.update_fields(session, user, {"lifestyle.travel_frequency_code": "frequent"})
        await service.submit_profile(session, user, "Updated travel preference")
        diff = await service.version_diff(session, profile["id"], 1, 2)
        assert "lifestyle.travel_frequency_code" in diff["changed_fields"]
        assert diff["added_fields"] == []
        assert diff["removed_fields"] == []
        # A single field change does not force a full re-review.
        assert diff["requires_full_review"] is False


@pytest.mark.asyncio
async def test_audit_trail_never_stores_narrative_text() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        reviewer = await create_reviewer(session)
        await create_complete_profile(session, user)
        await submit_and_approve(session, user, reviewer)
        rows = (
            (await session.execute(text("SELECT safe_context::text FROM matchmaking_audit_events")))
            .scalars()
            .all()
        )
        for row in rows:
            assert SELF_INTRODUCTION not in row
