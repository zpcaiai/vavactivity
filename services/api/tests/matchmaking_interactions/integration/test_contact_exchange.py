"""Mutually confirmed contact exchange, end to end."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import contact_exchange as exchange_service
from vav.modules.matchmaking_interactions.domain import ContactExchangeStatus

from ..helpers import (
    allow_contact_exchange,
    paired_members,
    reach_accepted_introduction,
    reach_mutual_match,
    verified_contact,
)


async def _ready_pair(session):
    viewer, candidate = await paired_members(session)
    await allow_contact_exchange(session, viewer, candidate)
    viewer_contact = await verified_contact(session, viewer)
    candidate_contact = await verified_contact(session, candidate)
    reached = await reach_accepted_introduction(session, viewer, candidate)
    exchange = await exchange_service.request_exchange(
        session, user_id=viewer.id, match_id=reached["match"]["id"]
    )
    await session.commit()
    return {
        "viewer": viewer,
        "candidate": candidate,
        "viewer_contact": viewer_contact,
        "candidate_contact": candidate_contact,
        "exchange_id": UUID(exchange["contact_exchange_request_id"]),
    }


@pytest.mark.asyncio
async def test_exchange_is_unavailable_before_acceptance() -> None:
    """This is the gate the whole flow rests on."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        await allow_contact_exchange(session, viewer, candidate)
        match = await reach_mutual_match(session, viewer, candidate)

        with pytest.raises(VavError) as excinfo:
            await exchange_service.request_exchange(
                session, user_id=viewer.id, match_id=match["id"]
            )
        assert excinfo.value.code == "INTRODUCTION_NOT_ACCEPTED"


@pytest.mark.asyncio
async def test_one_sided_consent_reveals_nothing() -> None:
    async with session_factory() as session:
        ready = await _ready_pair(session)
        view = await exchange_service.submit_consent(
            session,
            user_id=ready["viewer"].id,
            exchange_id=ready["exchange_id"],
            selected_contact_point_ids=[ready["viewer_contact"]],
            platform_only=False,
        )
        await session.commit()

        assert view["status"] == ContactExchangeStatus.ONE_SIDE_CONSENTED.value
        assert view["contacts"] == []

        # And the other member sees nothing either.
        other = await exchange_service.get_exchange(
            session, user_id=ready["candidate"].id, exchange_id=ready["exchange_id"]
        )
        assert other["contacts"] == []


@pytest.mark.asyncio
async def test_mutual_consent_activates_scoped_grants() -> None:
    async with session_factory() as session:
        ready = await _ready_pair(session)
        await exchange_service.submit_consent(
            session,
            user_id=ready["viewer"].id,
            exchange_id=ready["exchange_id"],
            selected_contact_point_ids=[ready["viewer_contact"]],
            platform_only=False,
        )
        await session.commit()
        view = await exchange_service.submit_consent(
            session,
            user_id=ready["candidate"].id,
            exchange_id=ready["exchange_id"],
            selected_contact_point_ids=[ready["candidate_contact"]],
            platform_only=False,
        )
        await session.commit()

        assert view["status"] == ContactExchangeStatus.ACTIVE.value
        assert len(view["contacts"]) == 1
        assert view["contacts"][0]["state"] == "available"
        assert "masked_value" in view["contacts"][0]
        assert "***" in view["contacts"][0]["masked_value"]


@pytest.mark.asyncio
async def test_the_list_response_never_carries_plaintext() -> None:
    async with session_factory() as session:
        ready = await _ready_pair(session)
        for user, contact in (
            (ready["viewer"], ready["viewer_contact"]),
            (ready["candidate"], ready["candidate_contact"]),
        ):
            await exchange_service.submit_consent(
                session,
                user_id=user.id,
                exchange_id=ready["exchange_id"],
                selected_contact_point_ids=[contact],
                platform_only=False,
            )
            await session.commit()

        view = await exchange_service.get_exchange(
            session, user_id=ready["viewer"].id, exchange_id=ready["exchange_id"]
        )
        rendered = str(view)
        # The domain survives masking, as the specification's own example
        # shows; the local part — the part that identifies the person — does
        # not, so the list response cannot be harvested for addresses.
        local_part = ready["candidate"].id.hex[:10]
        assert local_part not in rendered
        assert "***@contact.test" in rendered


@pytest.mark.asyncio
async def test_reveal_returns_the_value_once_and_is_audited() -> None:
    async with session_factory() as session:
        ready = await _ready_pair(session)
        for user, contact in (
            (ready["viewer"], ready["viewer_contact"]),
            (ready["candidate"], ready["candidate_contact"]),
        ):
            await exchange_service.submit_consent(
                session,
                user_id=user.id,
                exchange_id=ready["exchange_id"],
                selected_contact_point_ids=[contact],
                platform_only=False,
            )
            await session.commit()

        token = await exchange_service.issue_reveal_token(
            session,
            user_id=ready["viewer"].id,
            exchange_id=ready["exchange_id"],
            contact_point_id=ready["candidate_contact"],
        )
        await session.commit()
        revealed = await exchange_service.reveal(
            session,
            user_id=ready["viewer"].id,
            exchange_id=ready["exchange_id"],
            reveal_token=token["reveal_token"],
        )
        await session.commit()
        assert revealed["value"].endswith("@contact.test")

        audited = await session.scalar(
            text(
                "SELECT count(*) FROM privacy_sensitive_access_events "
                "WHERE actor_user_id=:actor AND module_code='matchmaking_interactions' "
                "AND asset_code='contact_point' AND result='allowed'"
            ),
            {"actor": ready["viewer"].id},
        )
        assert int(audited or 0) >= 1

        # The token is consumed and cannot be replayed.
        with pytest.raises(VavError) as excinfo:
            await exchange_service.reveal(
                session,
                user_id=ready["viewer"].id,
                exchange_id=ready["exchange_id"],
                reveal_token=token["reveal_token"],
            )
        assert excinfo.value.code == "REVEAL_TOKEN_EXPIRED"


@pytest.mark.asyncio
async def test_choosing_platform_only_opens_nothing() -> None:
    async with session_factory() as session:
        ready = await _ready_pair(session)
        await exchange_service.submit_consent(
            session,
            user_id=ready["viewer"].id,
            exchange_id=ready["exchange_id"],
            selected_contact_point_ids=[ready["viewer_contact"]],
            platform_only=False,
        )
        await session.commit()
        view = await exchange_service.submit_consent(
            session,
            user_id=ready["candidate"].id,
            exchange_id=ready["exchange_id"],
            selected_contact_point_ids=[],
            platform_only=True,
        )
        await session.commit()

        assert view["status"] != ContactExchangeStatus.ACTIVE.value
        assert view["contacts"] == []


@pytest.mark.asyncio
async def test_only_a_verified_contact_point_can_be_selected() -> None:
    async with session_factory() as session:
        ready = await _ready_pair(session)
        unverified = await session.scalar(
            text(
                "INSERT INTO user_contact_points "
                "(user_id,contact_type,value_encrypted,value_hmac,status) VALUES "
                "(:user,'phone','x','hmac-unverified','pending_verification') RETURNING id"
            ),
            {"user": ready["viewer"].id},
        )
        await session.commit()

        with pytest.raises(VavError) as excinfo:
            await exchange_service.submit_consent(
                session,
                user_id=ready["viewer"].id,
                exchange_id=ready["exchange_id"],
                selected_contact_point_ids=[UUID(str(unverified))],
                platform_only=False,
            )
        assert excinfo.value.code == "CONTACT_POINT_NOT_VERIFIED"


@pytest.mark.asyncio
async def test_a_member_cannot_offer_someone_elses_contact_point() -> None:
    async with session_factory() as session:
        ready = await _ready_pair(session)
        with pytest.raises(VavError) as excinfo:
            await exchange_service.submit_consent(
                session,
                user_id=ready["viewer"].id,
                exchange_id=ready["exchange_id"],
                selected_contact_point_ids=[ready["candidate_contact"]],
                platform_only=False,
            )
        assert excinfo.value.code == "CONTACT_POINT_NOT_VERIFIED"


@pytest.mark.asyncio
async def test_withdrawal_closes_only_the_withdrawing_members_channels() -> None:
    async with session_factory() as session:
        ready = await _ready_pair(session)
        for user, contact in (
            (ready["viewer"], ready["viewer_contact"]),
            (ready["candidate"], ready["candidate_contact"]),
        ):
            await exchange_service.submit_consent(
                session,
                user_id=user.id,
                exchange_id=ready["exchange_id"],
                selected_contact_point_ids=[contact],
                platform_only=False,
            )
            await session.commit()

        await exchange_service.withdraw_consent(
            session, user_id=ready["viewer"].id, exchange_id=ready["exchange_id"]
        )
        await session.commit()

        # The viewer withdrew their own channel, so the candidate can no longer
        # see it; the viewer's access to the candidate's channel is the
        # candidate's decision and is untouched.
        candidate_view = await exchange_service.get_exchange(
            session, user_id=ready["candidate"].id, exchange_id=ready["exchange_id"]
        )
        viewer_view = await exchange_service.get_exchange(
            session, user_id=ready["viewer"].id, exchange_id=ready["exchange_id"]
        )
        assert candidate_view["contacts"] == []
        assert len(viewer_view["contacts"]) == 1


@pytest.mark.asyncio
async def test_the_disclosures_are_returned_with_every_view() -> None:
    async with session_factory() as session:
        ready = await _ready_pair(session)
        view = await exchange_service.get_exchange(
            session, user_id=ready["viewer"].id, exchange_id=ready["exchange_id"]
        )
        assert len(view["disclosures"]) == 3
        assert any("cannot delete" in line for line in view["disclosures"])
