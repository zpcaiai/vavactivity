from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from vav.core.database import session_factory
from vav.models.knowledge import KnowledgeSource, KnowledgeSpace
from vav.modules.knowledge.service import active_authorization, knowledge_service


@pytest.mark.asyncio
async def test_upload_without_authorization_cannot_publish() -> None:
    async with session_factory() as session:
        space = await session.scalar(select(KnowledgeSpace).limit(1))
        assert space is not None
        source = KnowledgeSource(
            space_id=space.id,
            source_code=f"unauthorized-{uuid4().hex}",
            source_type="upload",
            title="Unauthorized source",
            sensitivity="restricted",
            status="active",
        )
        session.add(source)
        await session.commit()
        version = await knowledge_service.ingest(
            session,
            source=source,
            document_code=f"unauthorized-document-{uuid4().hex}",
            title="Must not publish",
            locale="en",
            mime_type="text/plain",
            raw_text="This content has no approved RAG rights.",
            source_locator={},
        )
        with pytest.raises(Exception, match="authorization"):
            await knowledge_service.publish(session, version=version, allowed_roles=[])


@pytest.mark.asyncio
async def test_revocation_is_effective_without_reindexing() -> None:
    async with session_factory() as session:
        source = await session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.source_code == "vav-authorized-foundations"
            )
        )
        assert source is not None
        authorization = await active_authorization(session, source.id)
        assert authorization is not None
        authorization.status = "revoked"
        authorization.revoked_at = datetime.now(UTC)
        await session.commit()
        assert await active_authorization(session, source.id) is None
        authorization.status = "approved"
        authorization.revoked_at = None
        await session.commit()


@pytest.mark.asyncio
async def test_public_quote_requires_independent_permission() -> None:
    async with session_factory() as session:
        source = await session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.source_code == "vav-authorized-foundations"
            )
        )
        assert source is not None
        authorization = await active_authorization(session, source.id)
        assert authorization is not None
        authorization.allow_public_quote = False
        await session.commit()
        assert await active_authorization(session, source.id) is not None
        assert await active_authorization(session, source.id, require_quote=True) is None
        authorization.allow_public_quote = True
        await session.commit()
