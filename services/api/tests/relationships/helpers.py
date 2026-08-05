"""Build a real Batch 15 handoff for Batch 16 tests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.models.identity import User

from ..matchmaking_interactions.helpers import (
    accept_introduction,
    create_interaction_fixture,
    create_match,
)


@dataclass(frozen=True)
class RelationshipFixture:
    first: User
    second: User
    journey_id: UUID
    match_id: UUID


async def create_relationship_fixture(session: AsyncSession) -> RelationshipFixture:
    interaction = await create_interaction_fixture(session)
    match_id = await create_match(session, interaction)
    invitation_id = await accept_introduction(session, interaction, match_id)
    journey_id = await session.scalar(
        text("SELECT id FROM relationship_journeys WHERE introduction_invitation_id=:invitation"),
        {"invitation": invitation_id},
    )
    assert journey_id is not None
    return RelationshipFixture(
        interaction.first, interaction.second, UUID(str(journey_id)), match_id
    )
