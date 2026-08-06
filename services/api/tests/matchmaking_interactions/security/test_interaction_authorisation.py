"""Cross-user access, eligibility and fail-closed behaviour."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import contact_exchange as exchange_service
from vav.modules.matchmaking_interactions import invitations as invitation_service
from vav.modules.matchmaking_interactions import likes as like_service
from vav.modules.matchmaking_interactions import matches as match_service

from ..helpers import (
    allow_contact_exchange,
    block_pair,
    key,
    mutual_items,
    paired_members,
    reach_accepted_introduction,
    reach_mutual_match,
    verified_contact,
)


@pytest.mark.asyncio
async def test_a_blocked_pair_cannot_like() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        await block_pair(session, viewer.id, candidate.id)

        with pytest.raises(VavError) as excinfo:
            await like_service.create_like(
                session,
                viewer_user_id=viewer.id,
                recommendation_item_id=forward,
                idempotency_key=key(),
            )
        assert excinfo.value.code == "INTERACTION_NOT_AVAILABLE"


@pytest.mark.asyncio
async def test_a_block_between_the_two_likes_prevents_the_match() -> None:
    """The recheck happens at match time, not only at like time."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        # Hold the identifiers as plain values: after the rollback below the
        # ORM instances would need a refresh, and that is database IO in a
        # place the async session cannot perform it.
        viewer_id, candidate_id = viewer.id, candidate.id
        forward, backward = await mutual_items(session, viewer, candidate)
        await like_service.create_like(
            session,
            viewer_user_id=viewer_id,
            recommendation_item_id=forward,
            idempotency_key=key(),
        )
        await session.commit()
        await block_pair(session, viewer_id, candidate_id)

        with pytest.raises(VavError):
            await like_service.create_like(
                session,
                viewer_user_id=candidate_id,
                recommendation_item_id=backward,
                idempotency_key=key(),
            )
        await session.rollback()

    async with session_factory() as session:
        matches = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_mutual_matches WHERE "
                "(user_low_id=:a AND user_high_id=:b) OR (user_low_id=:b AND user_high_id=:a)"
            ),
            {"a": viewer_id, "b": candidate_id},
        )
        assert int(matches or 0) == 0


@pytest.mark.asyncio
async def test_a_suspended_profile_cannot_be_liked() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        await session.execute(
            text("UPDATE dating_profiles SET status='suspended' WHERE user_id=:id"),
            {"id": candidate.id},
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await like_service.create_like(
                session,
                viewer_user_id=viewer.id,
                recommendation_item_id=forward,
                idempotency_key=key(),
            )
        assert excinfo.value.code == "INTERACTION_NOT_AVAILABLE"


@pytest.mark.asyncio
async def test_a_paused_profile_cannot_like() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        await session.execute(
            text("UPDATE dating_profiles SET status='paused_by_user' WHERE user_id=:id"),
            {"id": viewer.id},
        )
        await session.commit()

        with pytest.raises(VavError):
            await like_service.create_like(
                session,
                viewer_user_id=viewer.id,
                recommendation_item_id=forward,
                idempotency_key=key(),
            )


@pytest.mark.asyncio
async def test_a_member_cannot_read_someone_elses_match() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        outsider, _ = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)

        with pytest.raises(VavError) as excinfo:
            await match_service.member_match(session, user_id=outsider.id, match_id=match["id"])
        assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_a_member_cannot_read_someone_elses_invitation() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        outsider, _ = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)
        invitation = await invitation_service.send_invitation(
            session,
            sender_user_id=viewer.id,
            match_id=match["id"],
            message="hello",
            idempotency_key=key(),
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await invitation_service.get_invitation(
                session,
                user_id=outsider.id,
                invitation_id=UUID(invitation["invitation_id"]),
            )
        assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_a_member_cannot_read_someone_elses_contact_exchange() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        outsider, _ = await paired_members(session)
        await allow_contact_exchange(session, viewer, candidate)
        await verified_contact(session, viewer)
        await verified_contact(session, candidate)
        reached = await reach_accepted_introduction(session, viewer, candidate)
        exchange = await exchange_service.request_exchange(
            session, user_id=viewer.id, match_id=reached["match"]["id"]
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await exchange_service.get_exchange(
                session,
                user_id=outsider.id,
                exchange_id=UUID(exchange["contact_exchange_request_id"]),
            )
        assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_a_reveal_token_is_bound_to_its_viewer() -> None:
    """A token leaked to the other member is simply not valid for them."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        await allow_contact_exchange(session, viewer, candidate)
        viewer_contact = await verified_contact(session, viewer)
        candidate_contact = await verified_contact(session, candidate)
        reached = await reach_accepted_introduction(session, viewer, candidate)
        exchange = await exchange_service.request_exchange(
            session, user_id=viewer.id, match_id=reached["match"]["id"]
        )
        await session.commit()
        exchange_id = UUID(exchange["contact_exchange_request_id"])
        for user_id, contact_id in (
            (viewer.id, viewer_contact),
            (candidate.id, candidate_contact),
        ):
            await exchange_service.submit_consent(
                session,
                user_id=user_id,
                exchange_id=exchange_id,
                selected_contact_point_ids=[contact_id],
                platform_only=False,
            )
            await session.commit()

        token = await exchange_service.issue_reveal_token(
            session,
            user_id=viewer.id,
            exchange_id=exchange_id,
            contact_point_id=candidate_contact,
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await exchange_service.reveal(
                session,
                user_id=candidate.id,
                exchange_id=exchange_id,
                reveal_token=token["reveal_token"],
            )
        assert excinfo.value.code == "REVEAL_TOKEN_INVALID"

        denied = await session.scalar(
            text(
                "SELECT count(*) FROM privacy_sensitive_access_events "
                "WHERE actor_user_id=:actor AND result='denied'"
            ),
            {"actor": candidate.id},
        )
        assert int(denied or 0) >= 1


@pytest.mark.asyncio
async def test_a_forged_reveal_token_is_rejected() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        await allow_contact_exchange(session, viewer, candidate)
        await verified_contact(session, viewer)
        await verified_contact(session, candidate)
        reached = await reach_accepted_introduction(session, viewer, candidate)
        exchange = await exchange_service.request_exchange(
            session, user_id=viewer.id, match_id=reached["match"]["id"]
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await exchange_service.reveal(
                session,
                user_id=viewer.id,
                exchange_id=UUID(exchange["contact_exchange_request_id"]),
                reveal_token=uuid4().hex,
            )
        assert excinfo.value.code == "REVEAL_TOKEN_INVALID"


@pytest.mark.asyncio
async def test_the_refusal_message_names_no_cause() -> None:
    """Whatever fired, the member sees the same neutral answer."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        await block_pair(session, viewer.id, candidate.id)

        with pytest.raises(VavError) as excinfo:
            await like_service.create_like(
                session,
                viewer_user_id=viewer.id,
                recommendation_item_id=forward,
                idempotency_key=key(),
            )
        rendered = f"{excinfo.value.message} {excinfo.value.details}".lower()
        for leak in ("block", "report", "suspend", "restrict", "erasure", "moderation"):
            assert leak not in rendered
