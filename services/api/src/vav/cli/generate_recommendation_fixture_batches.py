"""Generate recommendation batches for the deterministic acceptance fixtures.

Used by local acceptance runs; each fixture member goes through the same pipeline
the scheduled worker uses, so a fixture batch is never a special case. Limiting
pool refreshes to fixture accounts keeps repeated E2E runs from rewriting and
auditing every real/demo member in a developer database.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.recommendations import batches, service


async def main() -> None:
    generated = 0
    skipped: dict[str, int] = {}
    async with session_factory() as session:
        fixture_rows = (
            await session.execute(
                text(
                    "SELECT p.user_id FROM dating_profile_recommendation_projections p "
                    "JOIN users u ON u.id=p.user_id "
                    "WHERE u.email LIKE 'recommendation-fixture-%@example.com' "
                    "ORDER BY p.user_id"
                )
            )
        ).all()
        for (user_id,) in fixture_rows:
            await service.rebuild_pool_entry(session, user_id)
        await session.commit()

    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT p.user_id FROM recommendation_pool_entries p "
                    "JOIN users u ON u.id=p.user_id "
                    "WHERE p.eligible = true "
                    "AND u.email LIKE 'recommendation-fixture-%@example.com'"
                )
            )
        ).all()

    for (user_id,) in rows:
        async with session_factory() as session:
            try:
                batch = await batches.generate_batch(session, user_id)
                await session.commit()
                generated += 1
                print(f"user {user_id}: batch {batch['id']} size {batch['generated_size']}")
            except VavError as error:
                await session.rollback()
                skipped[error.code] = skipped.get(error.code, 0) + 1

    print(f"generated {generated} batches; skipped {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
