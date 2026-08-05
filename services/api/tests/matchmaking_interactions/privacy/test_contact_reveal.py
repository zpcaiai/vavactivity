import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import contact_exchange
from vav.modules.privacy.crypto import encrypt_private, searchable_hmac

from ..helpers import (
    accept_introduction,
    activate_contact_exchange,
    create_interaction_fixture,
    create_match,
)


@pytest.mark.asyncio
async def test_reveal_token_does_not_cover_a_contact_value_changed_after_issue() -> None:
    async with session_factory() as session:
        fixture = await create_interaction_fixture(session)
        match_id = await create_match(session, fixture)
        await accept_introduction(session, fixture, match_id)
        exchange_id, _first_point, second_point = await activate_contact_exchange(
            session, fixture, match_id
        )
        issued = await contact_exchange.issue_reveal_token(
            session,
            user_id=fixture.first.id,
            exchange_id=exchange_id,
            contact_point_id=second_point,
        )
        await session.execute(
            text(
                "UPDATE user_contact_points SET value_encrypted=:encrypted,value_hmac=:hmac "
                "WHERE id=:id"
            ),
            {
                "id": second_point,
                "encrypted": encrypt_private("changed@example.com"),
                "hmac": searchable_hmac("changed@example.com"),
            },
        )
        with pytest.raises(VavError) as error:
            await contact_exchange.reveal(
                session,
                user_id=fixture.first.id,
                exchange_id=exchange_id,
                reveal_token=issued["reveal_token"],
            )
        assert error.value.code == "CONTACT_CONSENT_STALE"
        status = await session.scalar(
            text(
                "SELECT status FROM matchmaking_contact_exchange_grants "
                "WHERE contact_exchange_request_id=:exchange AND viewer_user_id=:viewer"
            ),
            {"exchange": exchange_id, "viewer": fixture.first.id},
        )
        assert status == "suspended"
