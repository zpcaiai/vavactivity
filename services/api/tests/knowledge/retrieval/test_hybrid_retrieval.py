from uuid import uuid4

import pytest
from sqlalchemy import select

from vav.core.database import session_factory
from vav.models.knowledge import KnowledgeSource, KnowledgeSpace
from vav.modules.knowledge.service import knowledge_service


@pytest.mark.asyncio
async def test_pgvector_and_full_text_fusion_returns_versioned_citation() -> None:
    async with session_factory() as session:
        space = await session.scalar(
            select(KnowledgeSpace).where(KnowledgeSpace.space_code == "vav-public-guidance")
        )
        assert space is not None
        result = await knowledge_service.retrieve(
            session,
            space=space,
            query="健康边界 尊重",
            locale="zh-CN",
            region=None,
            roles=[],
            top_k=8,
            public=True,
            actor_id=None,
        )
    assert result["no_answer"] is False
    item = result["items"][0]
    assert item["document_code"] == "healthy-boundaries-zh"
    assert item["document_version_id"]
    assert item["chunk_id"]
    assert item["citation_id"]
    assert item["excerpt_sha256"]


@pytest.mark.asyncio
async def test_locale_filter_prevents_cross_locale_results() -> None:
    async with session_factory() as session:
        space = await session.scalar(select(KnowledgeSpace).limit(1))
        assert space is not None
        result = await knowledge_service.retrieve(
            session,
            space=space,
            query="healthy boundaries",
            locale="fr",
            region=None,
            roles=[],
            top_k=8,
            public=True,
            actor_id=None,
        )
    assert result["items"] == []
    assert result["no_answer"] is True


@pytest.mark.asyncio
async def test_role_acl_is_applied_in_query_and_child_cites_parent() -> None:
    marker = f"restrictedknowledgeproof{uuid4().hex}"
    document_code = f"restricted-{uuid4().hex}"
    async with session_factory() as session:
        space = await session.scalar(
            select(KnowledgeSpace).where(KnowledgeSpace.space_code == "vav-public-guidance")
        )
        source = await session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.source_code == "vav-authorized-foundations"
            )
        )
        assert space is not None
        assert source is not None
        version = await knowledge_service.ingest(
            session,
            source=source,
            document_code=document_code,
            title="Restricted parent-child proof",
            locale="en",
            mime_type="text/plain",
            raw_text=f"{marker} is visible only to the internal knowledge role.",
            source_locator={"fixture": "role-acl-parent-child"},
        )
        version.status = "approved"
        await session.commit()
        await knowledge_service.publish(
            session, version=version, allowed_roles=["knowledge_internal"]
        )
        denied = await knowledge_service.retrieve(
            session,
            space=space,
            query=marker,
            locale="en",
            region=None,
            roles=[],
            top_k=8,
            public=False,
            actor_id=None,
        )
        allowed = await knowledge_service.retrieve(
            session,
            space=space,
            query=marker,
            locale="en",
            region=None,
            roles=["knowledge_internal"],
            top_k=8,
            public=False,
            actor_id=None,
        )

    assert all(item["document_code"] != document_code for item in denied["items"])
    matching = [item for item in allowed["items"] if item["document_code"] == document_code]
    assert len(matching) == 1
    assert matching[0]["parent_chunk_id"] is not None
