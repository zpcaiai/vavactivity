"""Invitation races: duplicate send, accept vs cancel, accept vs expiry."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import invitations as invitation_service
from vav.modules.matchmaking_interactions.domain import InvitationStatus

from ..helpers import key, paired_members, reach_mutual_match

FINAL = {
    InvitationStatus.ACCEPTED.value,
    InvitationStatus.DECLINED.value,
    InvitationStatus.CANCELLED.value,
    InvitationStatus.EXPIRED.value,
}


@pytest.mark.asyncio
async def test_both_members_sending_at_once_create_one_pending_invitation() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        match = await reach_mutual_match(session, viewer, candidate)

    async def send(sender_id) -> None:
        async with session_factory() as session:
            try:
                await invitation_service.send_invitation(
                    session,
                    sender_user_id=sender_id,
                    match_id=match["id"],
                    message="I would like to know you.",
                    idempotency_key=key(),
                )
                await session.commit()
            except Exception:
                await session.rollback()

    await asyncio.gather(send(viewer.id), send(candidate.id))

    async with session_factory() as session:
        pending = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_introduction_invitations "
                "WHERE mutual_match_id=:id AND status='pending'"
            ),
            {"id": match["id"]},
        )
        assert int(pending or 0) == 1


async def _pending_invitation(session, viewer, candidate) -> UUID:
    match = await reach_mutual_match(session, viewer, candidate)
    invitation = await invitation_service.send_invitation(
        session,
        sender_user_id=viewer.id,
        match_id=match["id"],
        message="I would like to know you.",
        idempotency_key=key(),
    )
    await session.commit()
    return UUID(invitation["invitation_id"])


@pytest.mark.asyncio
async def test_accept_and_cancel_at_once_leave_one_outcome() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        invitation_id = await _pending_invitation(session, viewer, candidate)

    async def accept() -> None:
        async with session_factory() as session:
            try:
                await invitation_service.accept_invitation(
                    session, user_id=candidate.id, invitation_id=invitation_id
                )
                await session.commit()
            except Exception:
                await session.rollback()

    async def cancel() -> None:
        async with session_factory() as session:
            try:
                await invitation_service.cancel_invitation(
                    session, user_id=viewer.id, invitation_id=invitation_id
                )
                await session.commit()
            except Exception:
                await session.rollback()

    await asyncio.gather(accept(), cancel())

    async with session_factory() as session:
        status = await session.scalar(
            text("SELECT status FROM matchmaking_introduction_invitations WHERE id=:id"),
            {"id": invitation_id},
        )
        assert status in FINAL
        # Whatever won, the relationship handoff matches it exactly.
        handoffs = await session.scalar(
            text(
                "SELECT count(*) FROM outbox_events "
                "WHERE topic='matchmaking.relationship_handoff.created' "
                "AND payload->>'invitation_id' = :id"
            ),
            {"id": str(invitation_id)},
        )
        expected = 1 if status == InvitationStatus.ACCEPTED.value else 0
        assert int(handoffs or 0) == expected


@pytest.mark.asyncio
async def test_accept_and_expiry_at_once_leave_one_outcome() -> None:
    """The expiry sweep uses SKIP LOCKED so it never fights a live accept."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        invitation_id = await _pending_invitation(session, viewer, candidate)
        await session.execute(
            text(
                "UPDATE matchmaking_introduction_invitations "
                "SET expires_at=now() + interval '2 seconds' WHERE id=:id"
            ),
            {"id": invitation_id},
        )
        await session.commit()

    await asyncio.sleep(2.2)

    async def accept() -> None:
        async with session_factory() as session:
            try:
                await invitation_service.accept_invitation(
                    session, user_id=candidate.id, invitation_id=invitation_id
                )
                await session.commit()
            except Exception:
                await session.rollback()

    async def expire() -> None:
        async with session_factory() as session:
            try:
                await invitation_service.expire_due_invitations(session)
                await session.commit()
            except Exception:
                await session.rollback()

    await asyncio.gather(accept(), expire())

    async with session_factory() as session:
        status = await session.scalar(
            text("SELECT status FROM matchmaking_introduction_invitations WHERE id=:id"),
            {"id": invitation_id},
        )
        # Whichever transaction took the row lock, an accept after the deadline
        # is refused. The invitation is either already expired, or still
        # pending because the worker skipped a locked row — never accepted.
        assert status in {InvitationStatus.EXPIRED.value, InvitationStatus.PENDING.value}

    async with session_factory() as session:
        # A following sweep always settles it, so pending is never terminal.
        await invitation_service.expire_due_invitations(session)
        await session.commit()
        accepted_at, expired_at = (
            await session.execute(
                text(
                    "SELECT accepted_at, expired_at FROM matchmaking_introduction_invitations "
                    "WHERE id=:id"
                ),
                {"id": invitation_id},
            )
        ).one()
        assert accepted_at is None
        assert expired_at is not None


@pytest.mark.asyncio
async def test_two_accepts_at_once_create_one_handoff() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        invitation_id = await _pending_invitation(session, viewer, candidate)

    async def accept() -> None:
        async with session_factory() as session:
            try:
                await invitation_service.accept_invitation(
                    session, user_id=candidate.id, invitation_id=invitation_id
                )
                await session.commit()
            except Exception:
                await session.rollback()

    await asyncio.gather(accept(), accept())

    async with session_factory() as session:
        handoffs = await session.scalar(
            text(
                "SELECT count(*) FROM outbox_events "
                "WHERE topic='matchmaking.relationship_handoff.created' "
                "AND payload->>'invitation_id' = :id"
            ),
            {"id": str(invitation_id)},
        )
        assert int(handoffs or 0) == 1
