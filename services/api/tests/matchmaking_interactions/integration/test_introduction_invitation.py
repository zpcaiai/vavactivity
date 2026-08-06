"""Sending, accepting, declining, cancelling and expiring introductions."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import invitations as invitation_service
from vav.modules.matchmaking_interactions.domain import InvitationStatus, MutualMatchStatus

from ..helpers import key, paired_members, reach_mutual_match


async def _sent(session, viewer, candidate, message="I am glad we chose each other."):
    match = await reach_mutual_match(session, viewer, candidate)
    invitation = await invitation_service.send_invitation(
        session,
        sender_user_id=viewer.id,
        match_id=match["id"],
        message=message,
        idempotency_key=key(),
    )
    await session.commit()
    return match, UUID(invitation["invitation_id"])


@pytest.mark.asyncio
async def test_a_match_member_can_send_an_introduction() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match, invitation_id = await _sent(session, viewer, candidate)

        status = await session.scalar(
            text("SELECT status FROM matchmaking_mutual_matches WHERE id=:id"),
            {"id": match["id"]},
        )
        assert status == MutualMatchStatus.INVITATION_PENDING.value


@pytest.mark.asyncio
async def test_a_match_has_at_most_one_pending_introduction() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match, _ = await _sent(session, viewer, candidate)

        with pytest.raises(VavError) as excinfo:
            await invitation_service.send_invitation(
                session,
                sender_user_id=candidate.id,
                match_id=match["id"],
                message="me too",
                idempotency_key=key(),
            )
        assert excinfo.value.code == "INVITATION_ALREADY_PENDING"


@pytest.mark.asyncio
async def test_a_stranger_cannot_send_an_introduction() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        outsider, _ = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)

        with pytest.raises(VavError) as excinfo:
            await invitation_service.send_invitation(
                session,
                sender_user_id=outsider.id,
                match_id=match["id"],
                message="hello",
                idempotency_key=key(),
            )
        assert excinfo.value.code == "MUTUAL_MATCH_NOT_FOUND"


@pytest.mark.asyncio
async def test_a_message_carrying_a_phone_number_is_rejected() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)

        with pytest.raises(VavError) as excinfo:
            await invitation_service.send_invitation(
                session,
                sender_user_id=viewer.id,
                match_id=match["id"],
                message="call me on 138-0013-8000",
                idempotency_key=key(),
            )
        assert excinfo.value.code == "INVITATION_MESSAGE_REJECTED"
        assert excinfo.value.details == [{"violations": ["phone_number"]}]


@pytest.mark.asyncio
async def test_the_recipient_can_accept() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match, invitation_id = await _sent(session, viewer, candidate)

        result = await invitation_service.accept_invitation(
            session, user_id=candidate.id, invitation_id=invitation_id
        )
        await session.commit()
        assert result["status"] == InvitationStatus.ACCEPTED.value
        assert result["relationship_handoff_id"]

        status = await session.scalar(
            text("SELECT status FROM matchmaking_mutual_matches WHERE id=:id"),
            {"id": match["id"]},
        )
        assert status == MutualMatchStatus.INTRODUCTION_ACCEPTED.value


@pytest.mark.asyncio
async def test_acceptance_creates_exactly_one_relationship_handoff() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        _match, invitation_id = await _sent(session, viewer, candidate)
        await invitation_service.accept_invitation(
            session, user_id=candidate.id, invitation_id=invitation_id
        )
        await session.commit()

        count = await session.scalar(
            text(
                "SELECT count(*) FROM outbox_events "
                "WHERE topic='matchmaking.relationship_handoff.created' "
                "AND payload->>'invitation_id' = :id"
            ),
            {"id": str(invitation_id)},
        )
        assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_the_sender_cannot_accept_their_own_introduction() -> None:
    """Otherwise one person could manufacture a relationship alone."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        _match, invitation_id = await _sent(session, viewer, candidate)

        with pytest.raises(VavError) as excinfo:
            await invitation_service.accept_invitation(
                session, user_id=viewer.id, invitation_id=invitation_id
            )
        assert excinfo.value.code == "INVITATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_the_recipient_can_decline_and_the_match_closes() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match, invitation_id = await _sent(session, viewer, candidate)

        result = await invitation_service.decline_invitation(
            session,
            user_id=candidate.id,
            invitation_id=invitation_id,
            reason_code="not_ready",
        )
        await session.commit()
        assert result["status"] == InvitationStatus.DECLINED.value

        status = await session.scalar(
            text("SELECT status FROM matchmaking_mutual_matches WHERE id=:id"),
            {"id": match["id"]},
        )
        assert status == MutualMatchStatus.CLOSED.value


@pytest.mark.asyncio
async def test_a_decline_starts_a_pair_cooldown() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match, invitation_id = await _sent(session, viewer, candidate)
        await invitation_service.decline_invitation(
            session, user_id=candidate.id, invitation_id=invitation_id
        )
        await session.commit()

        cooldown = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_pair_cooldowns WHERE pair_id=:pair "
                "AND cooldown_type='invitation_declined' AND released_at IS NULL"
            ),
            {"pair": match["pair_id"]},
        )
        assert int(cooldown or 0) == 1


@pytest.mark.asyncio
async def test_the_sender_can_cancel_before_a_reply() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match, invitation_id = await _sent(session, viewer, candidate)

        result = await invitation_service.cancel_invitation(
            session, user_id=viewer.id, invitation_id=invitation_id
        )
        await session.commit()
        assert result["status"] == InvitationStatus.CANCELLED.value

        status = await session.scalar(
            text("SELECT status FROM matchmaking_mutual_matches WHERE id=:id"),
            {"id": match["id"]},
        )
        assert status == MutualMatchStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_the_recipient_cannot_cancel() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        _match, invitation_id = await _sent(session, viewer, candidate)
        with pytest.raises(VavError) as excinfo:
            await invitation_service.cancel_invitation(
                session, user_id=candidate.id, invitation_id=invitation_id
            )
        assert excinfo.value.code == "INVITATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_a_stale_version_cannot_accept() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        _match, invitation_id = await _sent(session, viewer, candidate)
        await invitation_service.cancel_invitation(
            session, user_id=viewer.id, invitation_id=invitation_id
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await invitation_service.accept_invitation(
                session,
                user_id=candidate.id,
                invitation_id=invitation_id,
                expected_invitation_version=1,
            )
        assert excinfo.value.code == "INVITATION_STATE_CHANGED"


@pytest.mark.asyncio
async def test_the_expiry_worker_moves_a_due_invitation_once() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        _match, invitation_id = await _sent(session, viewer, candidate)
        await session.execute(
            text(
                "UPDATE matchmaking_introduction_invitations "
                "SET expires_at=now() - interval '1 hour' WHERE id=:id"
            ),
            {"id": invitation_id},
        )
        await session.commit()

        first = await invitation_service.expire_due_invitations(session)
        await session.commit()
        second = await invitation_service.expire_due_invitations(session)
        await session.commit()
        assert first >= 1
        # A second sweep finds nothing left to expire.
        status = await session.scalar(
            text("SELECT status FROM matchmaking_introduction_invitations WHERE id=:id"),
            {"id": invitation_id},
        )
        assert status == InvitationStatus.EXPIRED.value
        assert second == 0


@pytest.mark.asyncio
async def test_an_expired_introduction_reopens_the_match_by_default() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match, invitation_id = await _sent(session, viewer, candidate)
        await session.execute(
            text(
                "UPDATE matchmaking_introduction_invitations "
                "SET expires_at=now() - interval '1 hour' WHERE id=:id"
            ),
            {"id": invitation_id},
        )
        await session.commit()
        await invitation_service.expire_due_invitations(session)
        await session.commit()

        status = await session.scalar(
            text("SELECT status FROM matchmaking_mutual_matches WHERE id=:id"),
            {"id": match["id"]},
        )
        assert status == MutualMatchStatus.ACTIVE.value
