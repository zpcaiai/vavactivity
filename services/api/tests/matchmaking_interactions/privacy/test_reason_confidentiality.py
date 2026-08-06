"""Skip reasons and decline reasons stay with the person who gave them."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import invitations as invitation_service
from vav.modules.matchmaking_interactions import likes as like_service

from ..helpers import key, mutual_items, paired_members, reach_mutual_match


@pytest.mark.asyncio
async def test_the_decline_reason_is_never_returned_to_the_sender() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)
        invitation = await invitation_service.send_invitation(
            session,
            sender_user_id=viewer.id,
            match_id=match["id"],
            message="I would like to know you.",
            idempotency_key=key(),
        )
        await session.commit()
        invitation_id = UUID(invitation["invitation_id"])

        await invitation_service.decline_invitation(
            session,
            user_id=candidate.id,
            invitation_id=invitation_id,
            reason_code="felt_uncomfortable",
        )
        await session.commit()

        sender_view = await invitation_service.get_invitation(
            session, user_id=viewer.id, invitation_id=invitation_id
        )
        rendered = str(sender_view)
        assert "felt_uncomfortable" not in rendered
        assert sender_view["outcome_note"] == (
            "The other member did not continue with this introduction."
        )


@pytest.mark.asyncio
async def test_the_decline_reason_is_still_recorded_for_safety_review() -> None:
    """Private to the sender does not mean lost to an investigation."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)
        invitation = await invitation_service.send_invitation(
            session,
            sender_user_id=viewer.id,
            match_id=match["id"],
            message="hello",
            idempotency_key=key(),
        )
        await session.commit()
        invitation_id = UUID(invitation["invitation_id"])
        await invitation_service.decline_invitation(
            session,
            user_id=candidate.id,
            invitation_id=invitation_id,
            reason_code="felt_uncomfortable",
        )
        await session.commit()

        stored = await session.scalar(
            text(
                "SELECT decline_reason_code FROM matchmaking_introduction_invitations WHERE id=:id"
            ),
            {"id": invitation_id},
        )
        assert stored == "felt_uncomfortable"


@pytest.mark.asyncio
async def test_the_sender_never_reads_their_own_message_back_from_storage() -> None:
    """The recipient reads the message; the sender already knows what they wrote."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)
        invitation = await invitation_service.send_invitation(
            session,
            sender_user_id=viewer.id,
            match_id=match["id"],
            message="I appreciated what you wrote about your family.",
            idempotency_key=key(),
        )
        await session.commit()
        invitation_id = UUID(invitation["invitation_id"])

        sender_view = await invitation_service.get_invitation(
            session, user_id=viewer.id, invitation_id=invitation_id
        )
        recipient_view = await invitation_service.get_invitation(
            session, user_id=candidate.id, invitation_id=invitation_id
        )
        assert sender_view["message"] is None
        assert recipient_view["message"] == ("I appreciated what you wrote about your family.")


@pytest.mark.asyncio
async def test_the_invitation_message_is_encrypted_at_rest() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)
        secret = "I hope we can meet after church on Sunday."
        invitation = await invitation_service.send_invitation(
            session,
            sender_user_id=viewer.id,
            match_id=match["id"],
            message=secret,
            idempotency_key=key(),
        )
        await session.commit()

        stored = await session.scalar(
            text("SELECT message_encrypted FROM matchmaking_introduction_invitations WHERE id=:id"),
            {"id": UUID(invitation["invitation_id"])},
        )
        assert stored is not None
        assert secret not in stored


@pytest.mark.asyncio
async def test_the_skip_reason_is_invisible_to_the_skipped_member() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        forward, _ = await mutual_items(session, viewer, candidate)
        await like_service.create_skip(
            session,
            viewer_user_id=viewer.id,
            recommendation_item_id=forward,
            skip_type="not_interested",
            reason_code="lifestyle",
            reason_details="they smoke and I cannot live with that",
            idempotency_key=key(),
        )
        await session.commit()

        # The skipped member has no skip of their own and cannot read anyone
        # else's.
        assert await like_service.own_skips(session, candidate.id) == []
        mine = await like_service.own_skips(session, viewer.id)
        assert len(mine) == 1
        # Even the author's own list returns the code, not the free text.
        assert "reason_details" not in mine[0]
