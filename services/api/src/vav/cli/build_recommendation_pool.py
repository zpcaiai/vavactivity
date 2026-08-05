"""Rebuild the recommendation pool from approved profile projections."""

from __future__ import annotations

import asyncio

from vav.core.database import session_factory
from vav.modules.recommendations import service


async def main() -> None:
    async with session_factory() as session:
        count = await service.rebuild_pool(session)
        await session.commit()
    print(f"rebuilt {count} recommendation pool entries")


if __name__ == "__main__":
    asyncio.run(main())
