from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import contact_exchange, invitations, likes, matches

from ..helpers import (
    accept_introduction,
    activate_contact_exchange,
    create_interaction_fixture,
    create_match,
)


@pytest.mark.asyncio
async def test_one_sided_like_is_private_and_mutual_like_creates_one_match() -> None:
    async with session_factory() as session:
        fixture = await create_interaction_fixture(session)
        first = await likes.create_like(
            session,
            viewer_user_id=fixture.first.id,
            recommendation_item_id=fixture.first_item_id,
            idempotency_key=f"like-{uuid4()}",
        )
        assert first["outcome"] == "one_sided"
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM outbox_events WHERE topic=:topic "
                    "AND payload->>'pair_id'=(SELECT id::text FROM matchmaking_pairs "
                    "WHERE user_low_id IN (:a,:b) AND user_high_id IN (:a,:b))"
                ),
                {
                    "topic": "matchmaking.mutual_match.created",
                    "a": fixture.first.id,
                    "b": fixture.second.id,
                },
            )
            == 0
        )

        second = await likes.create_like(
            session,
            viewer_user_id=fixture.second.id,
            recommendation_item_id=fixture.second_item_id,
            idempotency_key=f"like-{uuid4()}",
        )
        assert second["outcome"] == "mutual_match"
        match_id = UUID(second["mutual_match_id"])
        assert (
            await session.scalar(
                text("SELECT count(*) FROM matchmaking_mutual_matches WHERE id=:id"),
                {"id": match_id},
            )
            == 1
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM outbox_events WHERE topic=:topic AND aggregate_id=:id"),
                {"topic": "matchmaking.mutual_match.created", "id": str(match_id)},
            )
            == 1
        )


@pytest.mark.asyncio
async def test_invitation_acceptance_is_separate_and_hands_off_once() -> None:
    async with session_factory() as session:
        fixture = await create_interaction_fixture(session)
        match_id = await create_match(session, fixture)
        invitation_id = await accept_introduction(session, fixture, match_id)
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status,relationship_handoff_id "
                        "FROM matchmaking_introduction_invitations "
                        "WHERE id=:id"
                    ),
                    {"id": invitation_id},
                )
            )
            .mappings()
            .one()
        )
        assert row["status"] == "accepted"
        assert row["relationship_handoff_id"] is not None
        with pytest.raises(VavError) as error:
            await invitations.accept_invitation(
                session, user_id=fixture.second.id, invitation_id=invitation_id
            )
        assert error.value.code == "INVITATION_STATE_CHANGED"


@pytest.mark.asyncio
async def test_contact_details_require_two_specific_consents_and_reveal_once() -> None:
    async with session_factory() as session:
        fixture = await create_interaction_fixture(session)
        match_id = await create_match(session, fixture)
        await accept_introduction(session, fixture, match_id)
        exchange_id, first_point, second_point = await activate_contact_exchange(
            session, fixture, match_id
        )

        first_view = await contact_exchange.get_exchange(
            session, user_id=fixture.first.id, exchange_id=exchange_id
        )
        assert first_view["status"] == "active"
        assert first_view["contacts"][0]["contact_point_id"] == str(second_point)
        assert first_view["contacts"][0]["masked_value"] == "s***@example.com"

        issued = await contact_exchange.issue_reveal_token(
            session,
            user_id=fixture.first.id,
            exchange_id=exchange_id,
            contact_point_id=second_point,
        )
        revealed = await contact_exchange.reveal(
            session,
            user_id=fixture.first.id,
            exchange_id=exchange_id,
            reveal_token=issued["reveal_token"],
        )
        assert revealed["value"] == "second@example.com"
        with pytest.raises(VavError) as error:
            await contact_exchange.reveal(
                session,
                user_id=fixture.first.id,
                exchange_id=exchange_id,
                reveal_token=issued["reveal_token"],
            )
        assert error.value.code == "REVEAL_TOKEN_EXPIRED"

        await contact_exchange.withdraw_consent(
            session, user_id=fixture.second.id, exchange_id=exchange_id
        )
        with pytest.raises(VavError) as error:
            await contact_exchange.issue_reveal_token(
                session,
                user_id=fixture.first.id,
                exchange_id=exchange_id,
                contact_point_id=second_point,
            )
        assert error.value.code == "CONTACT_ACCESS_NOT_GRANTED"
        assert first_point != second_point


@pytest.mark.asyncio
async def test_match_member_read_is_not_available_to_a_third_user() -> None:
    async with session_factory() as session:
        fixture = await create_interaction_fixture(session)
        match_id = await create_match(session, fixture)
        third_fixture = await create_interaction_fixture(session)
        with pytest.raises(VavError) as error:
            await matches.member_match(session, user_id=third_fixture.first.id, match_id=match_id)
        assert error.value.code == "MUTUAL_MATCH_NOT_FOUND"
