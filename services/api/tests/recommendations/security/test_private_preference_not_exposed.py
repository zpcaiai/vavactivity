"""One member's preferences and directional score stay private."""

# ruff: noqa: E501
from __future__ import annotations

import pytest

from vav.core.database import session_factory
from vav.modules.recommendations import batches, explanations, service

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_the_member_view_hides_scores_and_other_preferences() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )
        await batches.generate_batch(session, viewer.id)
        await session.commit()
        items = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        assert items

        for item in items:
            view = explanations.member_view(item["explanation_snapshot"])
            serialised = service.json_value(view).lower()
            for marker in ("score", "bps", "%", "weight", "preference_criteria", "hard_constraint"):
                assert marker not in serialised


@pytest.mark.asyncio
async def test_stored_items_keep_scores_server_side_only() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )
        await batches.generate_batch(session, viewer.id)
        await session.commit()
        items = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()

        item = items[0]
        # The reverse-direction score exists for diagnostics...
        assert 0 <= item["candidate_to_viewer_score_bps"] <= 10_000
        # ...but never inside anything shaped for the member.
        assert "candidate_to_viewer_score_bps" not in service.json_value(
            item["visible_profile_snapshot"]
        )
