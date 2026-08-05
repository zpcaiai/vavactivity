"""Balancing exposure never produces an unqualified recommendation."""

# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.recommendations import batches, service

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_every_produced_item_passed_both_directions() -> None:
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

        rows = (
            await session.execute(
                text(
                    "SELECT p.hard_constraint_snapshot, i.bidirectional_score_bps "
                    "FROM recommendation_items i "
                    "JOIN recommendation_candidate_pairs p ON p.id = i.candidate_pair_id "
                    "WHERE i.viewer_user_id=:viewer AND i.status <> 'invalidated'"
                ),
                {"viewer": viewer.id},
            )
        ).mappings()
        produced = [dict(row) for row in rows]
        assert produced
        for row in produced:
            snapshot = service._jsonb(row["hard_constraint_snapshot"]) or {}
            assert snapshot["passed"] is True
            assert snapshot["blocking_codes"] == []
            assert row["bidirectional_score_bps"] >= 5_000
