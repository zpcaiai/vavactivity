from uuid import uuid4

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import invitations

from ..helpers import create_interaction_fixture, create_match


@pytest.mark.asyncio
async def test_invitation_message_cannot_bypass_contact_consent() -> None:
    async with session_factory() as session:
        fixture = await create_interaction_fixture(session)
        match_id = await create_match(session, fixture)
        with pytest.raises(VavError) as error:
            await invitations.send_invitation(
                session,
                sender_user_id=fixture.first.id,
                match_id=match_id,
                message="加我微信 vav-test 或访问 https://example.com",
                idempotency_key=f"invitation-{uuid4()}",
            )
        assert error.value.code == "INVITATION_MESSAGE_REJECTED"
