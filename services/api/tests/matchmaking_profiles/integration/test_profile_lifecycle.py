"""Profile creation, editing, eligibility and completeness against the database."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_profiles import service
from vav.modules.matchmaking_profiles.domain import DatingProfileStatus

from ..helpers import (
    COMPLETE_FIELDS,
    SELF_INTRODUCTION,
    create_complete_profile,
    create_member,
    ensure_schema_release,
)


@pytest.mark.asyncio
async def test_member_creates_exactly_one_profile_with_strict_privacy() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        profile = await service.create_profile(session, user)
        assert profile["status"] == DatingProfileStatus.DRAFT.value
        assert profile["profile_number"].startswith("VAV-")

        with pytest.raises(VavError) as error:
            await service.create_profile(session, user)
        assert error.value.code == "DATING_PROFILE_ALREADY_EXISTS"

        # Every dating field is registered with the privacy control plane.
        rules = await session.scalar(
            text(
                "SELECT count(*) FROM user_field_visibility_rules WHERE user_id=:id "
                "AND data_domain LIKE 'dating_profile.%'"
            ),
            {"id": user.id},
        )
        assert int(rules or 0) > 0
        wide_open = await session.scalar(
            text(
                "SELECT count(*) FROM user_field_visibility_rules WHERE user_id=:id "
                "AND data_domain LIKE 'dating_profile.%' AND visibility NOT IN "
                "('private','mutual_only','verified_members')"
            ),
            {"id": user.id},
        )
        assert int(wide_open or 0) == 0


@pytest.mark.asyncio
async def test_date_of_birth_comes_from_the_protected_profile() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session, birth_year=1990)
        await service.create_profile(session, user)
        birth_date = await service.protected_date_of_birth(session, user.id)
        assert birth_date is not None
        assert birth_date.year == 1990
        # The matchmaking domain records where the birth date came from and how
        # to display it, but never stores a second copy of the value itself.
        columns = (
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name LIKE 'dating_profile%' AND column_name LIKE '%birth%'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(columns) == {"date_of_birth_source"}
        source = await session.scalar(
            text(
                "SELECT date_of_birth_source FROM dating_profile_core_details "
                "WHERE dating_profile_id=(SELECT id FROM dating_profiles WHERE user_id=:id)"
            ),
            {"id": user.id},
        )
        assert source == "privacy_protected_profile"


@pytest.mark.asyncio
async def test_minor_cannot_create_a_profile() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session, birth_year=2015)
        with pytest.raises(VavError) as error:
            await service.create_profile(session, user)
        assert error.value.code == "DATING_MINIMUM_AGE_NOT_MET"


@pytest.mark.asyncio
async def test_member_without_a_birth_date_is_asked_for_it_first() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        await session.execute(
            text("UPDATE user_profiles SET date_of_birth_encrypted=NULL WHERE user_id=:id"),
            {"id": user.id},
        )
        await session.commit()
        with pytest.raises(VavError) as error:
            await service.create_profile(session, user)
        assert error.value.code == "DATING_DATE_OF_BIRTH_REQUIRED"


@pytest.mark.asyncio
async def test_fields_are_saved_and_validated_against_the_active_schema() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        await service.create_profile(session, user)
        await service.update_fields(session, user, dict(COMPLETE_FIELDS))
        profile = await service.require_profile(session, user.id)
        payload = await service.load_payload(session, profile["id"])
        assert payload["faith.faith_status_code"] == "believer_baptized"
        assert payload["basic.relationship_intent"] == "marriage_oriented"
        assert payload["relationship_history.has_children"] is False

        with pytest.raises(VavError) as error:
            await service.update_fields(
                session, user, {"faith.faith_status_code": "not_a_taxonomy_value"}
            )
        assert error.value.code == "DATING_FIELD_INVALID"

        with pytest.raises(VavError) as unknown:
            await service.update_fields(session, user, {"basic.favourite_colour": "blue"})
        assert unknown.value.code in {"DATING_FIELD_UNKNOWN", "DATING_FIELD_NOT_WRITABLE"}


@pytest.mark.asyncio
async def test_completeness_is_recalculated_and_snapshotted() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        profile = await service.create_profile(session, user)
        empty = await service.completeness_view(session, profile["id"])
        # A fresh profile only carries a couple of database defaults.
        assert empty["total_basis_points"] < 2000
        assert not empty["submission_eligible"]
        assert empty["missing_required_fields"]

        await service.update_fields(session, user, dict(COMPLETE_FIELDS))
        await service.update_narratives(
            session, user, "zh-CN", {"self_introduction": SELF_INTRODUCTION}
        )
        scored = await service.completeness_view(session, profile["id"])
        assert scored["total_basis_points"] > empty["total_basis_points"]
        assert scored["measures"] == "form_completion_only"

        snapshots = await session.scalar(
            text(
                "SELECT count(*) FROM dating_profile_completeness_snapshots WHERE dating_profile_id=:id"
            ),
            {"id": profile["id"]},
        )
        assert int(snapshots or 0) >= 1


@pytest.mark.asyncio
async def test_encrypted_summaries_are_not_stored_in_clear_text() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        await service.create_profile(session, user)
        secret = "A private note about my past relationships."
        await service.update_fields(session, user, {"relationship_history.history_summary": secret})
        profile = await service.require_profile(session, user.id)
        stored = await session.scalar(
            text(
                "SELECT history_summary_encrypted FROM dating_profile_relationship_history WHERE dating_profile_id=:id"
            ),
            {"id": profile["id"]},
        )
        assert stored is not None
        assert secret not in str(stored)
        payload = await service.load_payload(session, profile["id"])
        assert payload["relationship_history.history_summary"] == secret


@pytest.mark.asyncio
async def test_narratives_reject_contact_details_and_enter_review() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        profile = await service.create_profile(session, user)
        with pytest.raises(VavError) as error:
            await service.update_narratives(
                session,
                user,
                "zh-CN",
                {"self_introduction": SELF_INTRODUCTION + " 联系我 member@example.com"},
            )
        assert error.value.code == "DATING_NARRATIVE_CONTACT_INFORMATION"

        await service.update_narratives(
            session, user, "zh-CN", {"self_introduction": SELF_INTRODUCTION}
        )
        status = await session.scalar(
            text(
                "SELECT moderation_status FROM dating_profile_narratives WHERE dating_profile_id=:id"
            ),
            {"id": profile["id"]},
        )
        assert status == "review_required"


@pytest.mark.asyncio
async def test_short_self_introduction_is_rejected() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        await service.create_profile(session, user)
        with pytest.raises(VavError) as error:
            await service.update_narratives(session, user, "zh-CN", {"self_introduction": "太短了"})
        assert error.value.code == "DATING_FIELD_INVALID"


@pytest.mark.asyncio
async def test_a_fully_filled_profile_becomes_submittable() -> None:
    async with session_factory() as session:
        await ensure_schema_release(session)
        user = await create_member(session)
        profile = await create_complete_profile(session, user)
        scores = await service.completeness_view(session, profile["id"])
        assert scores["missing_required_fields"] == []
        assert scores["submission_eligible"]
        assert profile["status"] == DatingProfileStatus.READY_TO_SUBMIT.value
