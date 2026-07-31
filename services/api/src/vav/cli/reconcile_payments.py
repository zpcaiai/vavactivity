from __future__ import annotations

import asyncio

from vav.core.database import get_engine, session_factory
from vav.modules.commerce.service import reconciliation_service


async def reconcile() -> None:
    async with session_factory() as session:
        count = await reconciliation_service.scan(session)
    await get_engine().dispose()
    print(f"Commerce reconciliation complete: {count} new discrepancies")


if __name__ == "__main__":
    asyncio.run(reconcile())
