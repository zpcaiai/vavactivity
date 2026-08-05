from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.relationships import service

from ..helpers import create_relationship_fixture


@pytest.mark.asyncio
async def test_handoff_creates_one_journey_and_mutual_stage_change() -> None:
    async with session_factory() as session:
        fixture = await create_relationship_fixture(session)
        assert (
            await session.scalar(
                text("SELECT count(*) FROM relationship_journeys WHERE id=:id"),
                {"id": fixture.journey_id},
            )
            == 1
        )
        proposed = await service.create_stage_proposal(
            session,
            journey_id=fixture.journey_id,
            actor_id=fixture.first.id,
            to_stage="initial_contact",
            message="如果你也愿意，我们可以进入下一阶段。",
            idempotency_key=f"proposal-{uuid4()}",
        )
        current = await service.get_journey(session, fixture.journey_id, fixture.first.id)
        assert current["current_stage_code"] == "introduction_accepted"
        accepted = await service.decide_stage_proposal(
            session,
            proposal_id=UUID(proposed["proposal_id"]),
            actor_id=fixture.second.id,
            accept=True,
        )
        assert accepted["current_stage_code"] == "initial_contact"
        assert (await service.get_journey(session, fixture.journey_id, fixture.second.id))[
            "current_stage_code"
        ] == "initial_contact"


@pytest.mark.asyncio
async def test_pause_is_immediate_resume_is_mutual_and_end_is_unilateral() -> None:
    async with session_factory() as session:
        fixture = await create_relationship_fixture(session)
        paused = await service.pause(
            session,
            journey_id=fixture.journey_id,
            actor_id=fixture.first.id,
            private_reason="需要一些空间",
            visible_message="我想暂停一下。",
        )
        assert paused["status"] == "paused"
        requested = await service.request_resume(
            session, journey_id=fixture.journey_id, actor_id=fixture.first.id
        )
        with pytest.raises(VavError) as own_request:
            await service.decide_resume(
                session,
                pause_id=UUID(requested["pause_id"]),
                actor_id=fixture.first.id,
                accept=True,
            )
        assert own_request.value.code == "RELATIONSHIP_RESUME_REQUIRES_PARTNER"
        resumed = await service.decide_resume(
            session,
            pause_id=UUID(requested["pause_id"]),
            actor_id=fixture.second.id,
            accept=True,
        )
        assert resumed["status"] == "resumed"
        ended = await service.end_journey(
            session,
            journey_id=fixture.journey_id,
            actor_id=fixture.first.id,
            confirmed=True,
            reason_code="member_choice",
            private_reason="private",
            visible_message=None,
        )
        assert ended["status"] == "ended"
        assert (
            await session.scalar(
                text("SELECT status FROM matchmaking_mutual_matches WHERE id=:id"),
                {"id": fixture.match_id},
            )
            == "closed"
        )
