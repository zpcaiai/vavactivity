import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.relationships import service

from ..helpers import create_relationship_fixture


async def _decide(proposal_id: UUID, actor_id: UUID) -> str:
    async with session_factory() as session:
        try:
            result = await service.decide_stage_proposal(
                session, proposal_id=proposal_id, actor_id=actor_id, accept=True
            )
            await session.commit()
            return result["status"]
        except VavError as exc:
            await session.rollback()
            return exc.code


@pytest.mark.asyncio
async def test_concurrent_accepts_advance_exactly_once() -> None:
    async with session_factory() as session:
        fixture = await create_relationship_fixture(session)
        proposal = await service.create_stage_proposal(
            session,
            journey_id=fixture.journey_id,
            actor_id=fixture.first.id,
            to_stage="initial_contact",
            message=None,
            idempotency_key=str(uuid4()),
        )
        proposal_id = UUID(proposal["proposal_id"])
        recipient_id = fixture.second.id
        journey_id = fixture.journey_id
        await session.commit()
    outcomes = await asyncio.gather(
        _decide(proposal_id, recipient_id), _decide(proposal_id, recipient_id)
    )
    assert sorted(outcomes) == ["RELATIONSHIP_PROPOSAL_STATE_CHANGED", "accepted"]
    async with session_factory() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM relationship_status_history "
                    "WHERE journey_id=:journey AND event_type='stage_proposal_accepted'"
                ),
                {"journey": journey_id},
            )
            == 1
        )
