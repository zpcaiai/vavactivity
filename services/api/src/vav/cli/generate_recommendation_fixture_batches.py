"""Generate candidate pairs and batches for the seeded fixture members."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations.service import (
    generate_batch,
    generate_candidates,
    rebuild_pool,
)


async def generate_recommendation_fixture_batches() -> None:
    async with session_factory() as session:
        await rebuild_pool(session)
        user_ids = (
            (
                await session.execute(
                    text(
                        "SELECT user_id FROM recommendation_pool_entries WHERE eligible=true ORDER BY user_id"
                    )
                )
            )
            .scalars()
            .all()
        )
        generated = 0
        skipped: dict[str, int] = {}
        for user_id in user_ids:
            try:
                await generate_candidates(session, user_id)
                await generate_batch(session, user_id)
                generated += 1
            except VavError as error:
                skipped[error.code] = skipped.get(error.code, 0) + 1
    print(
        f"Recommendation fixtures: {len(user_ids)} eligible members, {generated} batches generated"
        + (f", skipped {skipped}" if skipped else "")
    )


if __name__ == "__main__":
    asyncio.run(generate_recommendation_fixture_batches())
