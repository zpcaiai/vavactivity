from __future__ import annotations

import asyncio

from sqlalchemy import select

from vav.cli.seed_knowledge import CONNECTOR_SOURCES, seed_knowledge
from vav.core.database import session_factory
from vav.models.knowledge import KnowledgeSource
from vav.modules.knowledge.connectors import sync_source


async def main() -> None:
    await seed_knowledge()
    total = 0
    async with session_factory() as session:
        for source_code, _source_type, _space_code, _title in CONNECTOR_SOURCES:
            source = await session.scalar(
                select(KnowledgeSource).where(KnowledgeSource.source_code == source_code)
            )
            assert source is not None
            total += len(await sync_source(session, source))
    print(
        f"Knowledge connector fixtures ingested: {total} review-required versions; "
        "private learner, registration and counseling records excluded"
    )


if __name__ == "__main__":
    asyncio.run(main())
