"""Rebuild the recommendation pool from the current Batch 13 projections."""

from __future__ import annotations

import asyncio

from vav.core.database import session_factory
from vav.modules.recommendations.service import rebuild_pool


async def build_recommendation_pool() -> None:
    async with session_factory() as session:
        result = await rebuild_pool(session)
    print(
        f"Recommendation pool rebuilt: {result['synced']} projections synced, "
        f"{result['eligible']} eligible"
    )


if __name__ == "__main__":
    asyncio.run(build_recommendation_pool())
