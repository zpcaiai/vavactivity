from __future__ import annotations

import asyncio

from sqlalchemy import select

from vav.core.database import session_factory
from vav.models.knowledge import (
    KnowledgeEmbeddingProfile,
    KnowledgeIndexVersion,
    KnowledgeSpace,
)
from vav.modules.knowledge.indexing import build_candidate_index


async def main() -> None:
    async with session_factory() as session:
        space = await session.scalar(
            select(KnowledgeSpace).where(KnowledgeSpace.space_code == "vav-public-guidance")
        )
        if space is None:
            raise RuntimeError("Seed knowledge before building an index.")
        active = await session.scalar(
            select(KnowledgeIndexVersion).where(
                KnowledgeIndexVersion.space_id == space.id,
                KnowledgeIndexVersion.status == "active",
            )
        )
        profile = (
            await session.get(KnowledgeEmbeddingProfile, active.embedding_profile_id)
            if active
            else await session.scalar(
                select(KnowledgeEmbeddingProfile).where(
                    KnowledgeEmbeddingProfile.status == "active"
                )
            )
        )
        if profile is None:
            raise RuntimeError("An active embedding profile is required.")
        candidate = await build_candidate_index(session, space=space, profile=profile)
    print(
        "Knowledge candidate index built: "
        f"id={candidate.id}, version={candidate.version_number}, "
        f"chunks={candidate.chunk_count}, embeddings={candidate.embedding_count}, "
        f"status={candidate.status}"
    )


if __name__ == "__main__":
    asyncio.run(main())
