import pytest
from sqlalchemy import select

from vav.cli.seed_cms import SYSTEM_USER_ID
from vav.core.database import session_factory
from vav.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbeddingProfile,
    KnowledgeIndexVersion,
    KnowledgeSpace,
)
from vav.modules.knowledge.indexing import (
    activate_index_version,
    build_candidate_index,
    rollback_index_version,
)


@pytest.mark.asyncio
async def test_candidate_preserves_acl_and_supports_atomic_activation_rollback() -> None:
    async with session_factory() as session:
        space = await session.scalar(
            select(KnowledgeSpace).where(KnowledgeSpace.space_code == "vav-public-guidance")
        )
        profile = await session.scalar(
            select(KnowledgeEmbeddingProfile).where(KnowledgeEmbeddingProfile.status == "active")
        )
        assert space is not None
        assert profile is not None
        candidate = await build_candidate_index(session, space=space, profile=profile)
        restricted_document = await session.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.document_code.like("restricted-%"))
            .order_by(KnowledgeDocument.created_at.desc())
        )
        if restricted_document and restricted_document.current_version_id:
            restricted_chunk = await session.scalar(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.index_version_id == candidate.id,
                    KnowledgeChunk.document_version_id == restricted_document.current_version_id,
                    KnowledgeChunk.chunk_type == "semantic",
                )
            )
            assert restricted_chunk is not None
            assert restricted_chunk.allowed_roles == ["knowledge_internal"]
        previous_id = candidate.previous_index_id
        assert previous_id is not None
        candidate.evaluation_status = "passed"
        await session.commit()
        activated = await activate_index_version(
            session,
            index=candidate,
            actor_id=SYSTEM_USER_ID,
            reason="integration activation proof",
        )
        assert activated.status == "active"
        previous = await session.get(KnowledgeIndexVersion, previous_id)
        assert previous is not None and previous.status == "superseded"
        restored = await rollback_index_version(
            session,
            current=activated,
            actor_id=SYSTEM_USER_ID,
            reason="integration rollback proof",
        )
        assert restored.id == previous_id
        assert restored.status == "active"
        assert activated.status == "rolled_back"


@pytest.mark.asyncio
async def test_failed_evaluation_cannot_activate_candidate() -> None:
    async with session_factory() as session:
        space = await session.scalar(
            select(KnowledgeSpace).where(KnowledgeSpace.space_code == "vav-public-guidance")
        )
        profile = await session.scalar(
            select(KnowledgeEmbeddingProfile).where(KnowledgeEmbeddingProfile.status == "active")
        )
        assert space is not None
        assert profile is not None
        candidate = await build_candidate_index(session, space=space, profile=profile)
        candidate.evaluation_status = "failed"
        await session.commit()
        with pytest.raises(Exception, match="passed candidate evaluation"):
            await activate_index_version(
                session,
                index=candidate,
                actor_id=SYSTEM_USER_ID,
                reason="must fail closed",
            )
        candidate.status = "rolled_back"
        await session.commit()
