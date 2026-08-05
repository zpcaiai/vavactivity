"""Generate recommendation batches for every eligible member.

Used by local acceptance runs; each member goes through the same pipeline the
scheduled worker uses, so a fixture batch is never a special case.
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
        await service.rebuild_pool(session)
        await session.commit()

    async with session_factory() as session:
        rows = (
            await session.execute(
                text("SELECT user_id FROM recommendation_pool_entries WHERE eligible = true")
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
