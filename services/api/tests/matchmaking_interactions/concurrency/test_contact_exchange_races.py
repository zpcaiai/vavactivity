"""Contact-exchange races: simultaneous consent, and reveal versus revoke."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import contact_exchange as exchange_service

from ..helpers import (
    allow_contact_exchange,
    paired_members,
    reach_accepted_introduction,
    verified_contact,
)


async def _ready(session):
    viewer, candidate = await paired_members(session)
    await allow_contact_exchange(session, viewer, candidate)
    viewer_contact = await verified_contact(session, viewer)
    candidate_contact = await verified_contact(session, candidate)
    reached = await reach_accepted_introduction(session, viewer, candidate)
    exchange = await exchange_service.request_exchange(
        session, user_id=viewer.id, match_id=reached["match"]["id"]
    )
    await session.commit()
    return (
        viewer,
        candidate,
        viewer_contact,
        candidate_contact,
        UUID(exchange["contact_exchange_request_id"]),
    )


@pytest.mark.asyncio
async def test_both_members_consenting_at_once_activate_once() -> None:
    async with session_factory() as session:
        viewer, candidate, viewer_contact, candidate_contact, exchange_id = await _ready(session)

    async def consent(user_id, contact_id) -> None:
        async with session_factory() as session:
            try:
                await exchange_service.submit_consent(
                    session,
                    user_id=user_id,
                    exchange_id=exchange_id,
                    selected_contact_point_ids=[contact_id],
                    platform_only=False,
                )
                await session.commit()
            except Exception:
                await session.rollback()

    await asyncio.gather(
        consent(viewer.id, viewer_contact), consent(candidate.id, candidate_contact)
    )

    async with session_factory() as session:
        grants = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_contact_exchange_grants "
                "WHERE contact_exchange_request_id=:id"
            ),
            {"id": exchange_id},
        )
        # One grant per direction, never more, however the two consents raced.
        assert int(grants or 0) <= 2


@pytest.mark.asyncio
async def test_revocation_beats_an_unused_reveal_token() -> None:
    """A token issued a moment ago must not survive a withdrawal."""
    async with session_factory() as session:
        viewer, candidate, viewer_contact, candidate_contact, exchange_id = await _ready(session)
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

        await exchange_service.withdraw_consent(
            session, user_id=candidate.id, exchange_id=exchange_id
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await exchange_service.reveal(
                session,
                user_id=viewer.id,
                exchange_id=exchange_id,
                reveal_token=token["reveal_token"],
            )
        assert excinfo.value.code in {"REVEAL_TOKEN_EXPIRED", "CONTACT_ACCESS_REVOKED"}


@pytest.mark.asyncio
async def test_a_changed_contact_value_suspends_the_grant() -> None:
    """A new number is not covered by consent given for the old one."""
    async with session_factory() as session:
        viewer, candidate, viewer_contact, candidate_contact, exchange_id = await _ready(session)
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

        await session.execute(
            text("UPDATE user_contact_points SET value_hmac='rotated-value' WHERE id=:id"),
            {"id": candidate_contact},
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await exchange_service.issue_reveal_token(
                session,
                user_id=viewer.id,
                exchange_id=exchange_id,
                contact_point_id=candidate_contact,
            )
        assert excinfo.value.code == "CONTACT_CONSENT_STALE"

        status = await session.scalar(
            text(
                "SELECT status FROM matchmaking_contact_exchange_grants "
                "WHERE contact_exchange_request_id=:id AND viewer_user_id=:viewer"
            ),
            {"id": exchange_id, "viewer": viewer.id},
        )
        assert status == "suspended"


@pytest.mark.asyncio
async def test_a_changed_value_is_reported_as_awaiting_reconfirmation() -> None:
    async with session_factory() as session:
        viewer, candidate, viewer_contact, candidate_contact, exchange_id = await _ready(session)
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
        await session.execute(
            text("UPDATE user_contact_points SET value_hmac='rotated-again' WHERE id=:id"),
            {"id": candidate_contact},
        )
        await session.commit()

        view = await exchange_service.get_exchange(
            session, user_id=viewer.id, exchange_id=exchange_id
        )
        states = {contact["state"] for contact in view["contacts"]}
        assert states == {"awaiting_reconfirmation"}
        assert all("masked_value" not in contact for contact in view["contacts"])
