from __future__ import annotations

import asyncio

from sqlalchemy.dialects.postgresql import insert

from vav.core.database import session_factory
from vav.models.system import SystemMetadata


async def seed() -> None:
    async with session_factory() as session:
        statement = (
            insert(SystemMetadata)
            .values(key="installation", value={"seed_version": 1})
            .on_conflict_do_nothing(index_elements=[SystemMetadata.key])
        )
        await session.execute(statement)
        await session.commit()
    print("Seed complete: installation metadata is present")


if __name__ == "__main__":
    asyncio.run(seed())
