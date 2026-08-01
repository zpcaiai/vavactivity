from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from vav.core.database import session_factory
from vav.models.knowledge import KnowledgeDocumentVersion, KnowledgeSource
from vav.modules.knowledge.service import knowledge_service


@pytest.mark.asyncio
async def test_source_snapshot_change_creates_version_and_published_payload_is_immutable() -> None:
    document_code = f"immutable-{uuid4().hex}"
    async with session_factory() as session:
        source = await session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.source_code == "vav-authorized-foundations"
            )
        )
        assert source is not None
        first = await knowledge_service.ingest(
            session,
            source=source,
            document_code=document_code,
            title="Immutable version proof",
            locale="en",
            mime_type="text/plain",
            raw_text="A published source snapshot cannot be edited in place.",
            source_locator={"source_version": 1},
        )
        first.status = "approved"
        await session.commit()
        await knowledge_service.publish(session, version=first, allowed_roles=[])
        first_id = first.id
        first.normalized_text = "mutated after publication"
        with pytest.raises(DBAPIError, match="immutable"):
            await session.commit()
        await session.rollback()
        first = await session.get(KnowledgeDocumentVersion, first_id)
        assert first is not None
        source = await session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.source_code == "vav-authorized-foundations"
            )
        )
        assert source is not None
        second = await knowledge_service.ingest(
            session,
            source=source,
            document_code=document_code,
            title="Immutable version proof",
            locale="en",
            mime_type="text/plain",
            raw_text="A published source snapshot cannot be edited in place.",
            source_locator={"source_version": 2},
        )
        assert second.id != first.id
        assert second.version_number == first.version_number + 1
        assert second.status == "review_required"
