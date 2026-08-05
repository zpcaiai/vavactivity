"""When safety cannot be evaluated, the pair is not recommended."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.modules.recommendations import service
from vav.modules.recommendations.gateways import ModerationGateway

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


class _BrokenSession:
    """A session whose safety query always fails."""

    async def execute(self, *args: object, **kwargs: object) -> object:
        raise OperationalError("SELECT 1", {}, Exception("moderation unavailable"))


@pytest.mark.asyncio
async def test_a_moderation_failure_denies_the_pair() -> None:
    gateway = ModerationGateway(_BrokenSession())  # type: ignore[arg-type]
    from uuid import uuid4

    decision = await gateway.evaluate_recommendation_pair(
        viewer_user_id=uuid4(), candidate_user_id=uuid4()
    )
    assert not decision.allowed
    assert decision.reason_code == "moderation_unavailable"


def test_failing_closed_cannot_be_switched_off() -> None:
    settings = get_settings()
    assert settings.recommendation_fail_closed_on_moderation_error
    assert settings.recommendation_require_zero_blocked_pair_leakage


@pytest.mark.asyncio
async def test_a_healthy_gateway_allows_an_unrestricted_pair() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        candidate, _ = await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )
        decision = await ModerationGateway(session).evaluate_recommendation_pair(
            viewer_user_id=viewer.id, candidate_user_id=candidate.id
        )
        assert decision.allowed
        assert decision.reason_code is None
        assert isinstance(session, AsyncSession)
        assert await service.pool_entry(session, candidate.id) is not None
