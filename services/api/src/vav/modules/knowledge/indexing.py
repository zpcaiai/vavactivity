from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeEmbeddingProfile,
    KnowledgeIndexVersion,
    KnowledgeSource,
    KnowledgeSpace,
)
from vav.modules.courses.crypto import encrypt_sensitive
from vav.modules.knowledge.service import (
    active_authorization,
    detect_findings,
    fake_embedding,
    semantic_chunks,
    vector_literal,
)


async def build_candidate_index(
    session: AsyncSession,
    *,
    space: KnowledgeSpace,
    profile: KnowledgeEmbeddingProfile,
    actor_id: UUID | None = None,
) -> KnowledgeIndexVersion:
    active = await session.scalar(
        select(KnowledgeIndexVersion).where(
            KnowledgeIndexVersion.space_id == space.id,
            KnowledgeIndexVersion.status == "active",
        )
    )
    number = (
        await session.scalar(
            select(func.max(KnowledgeIndexVersion.version_number)).where(
                KnowledgeIndexVersion.space_id == space.id
            )
        )
        or 0
    ) + 1
    index = KnowledgeIndexVersion(
        space_id=space.id,
        version_number=number,
        embedding_profile_id=profile.id,
        chunk_strategy="heading_aware_parent_child_v1",
        status="building",
        previous_index_id=active.id if active else None,
        retrieval_configuration={"fusion": "rrf", "candidate_count": 40, "reranker": "safe_noop"},
    )
    session.add(index)
    await session.flush()
    rows = (
        await session.execute(
            select(KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeSource)
            .join(
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.id == KnowledgeDocument.current_version_id,
            )
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
            .where(
                KnowledgeDocument.space_id == space.id,
                KnowledgeDocument.status == "published",
                KnowledgeDocumentVersion.status == "published",
                KnowledgeSource.status == "active",
            )
        )
    ).all()
    manifest: list[dict[str, object]] = []
    seen_content: set[str] = set()
    chunk_count = 0
    embedding_count = 0
    for document, version, source in rows:
        if await active_authorization(session, source.id, document_id=document.id) is None:
            continue
        current_chunk = (
            await session.scalar(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.index_version_id == active.id,
                    KnowledgeChunk.document_version_id == version.id,
                    KnowledgeChunk.chunk_type != "parent",
                )
            )
            if active
            else None
        )
        allowed_roles = current_chunk.allowed_roles if current_chunk else space.allowed_roles
        manifest.append(
            {
                "document_id": str(document.id),
                "document_version_id": str(version.id),
                "checksum_sha256": version.checksum_sha256,
            }
        )
        parent = KnowledgeChunk(
            document_version_id=version.id,
            index_version_id=index.id,
            chunk_number=0,
            chunk_type="parent",
            content=version.normalized_text,
            content_sha256=hashlib.sha256(version.normalized_text.encode()).hexdigest(),
            token_count=len(version.normalized_text.split()),
            title_path=[document.title],
            source_locator=version.source_locator,
            allowed_roles=allowed_roles,
            sensitivity=document.sensitivity,
            injection_suspected=any(
                finding[0] == "prompt_injection"
                for finding in detect_findings(version.normalized_text)
            ),
            status="published",
        )
        session.add(parent)
        await session.flush()
        children: list[KnowledgeChunk] = []
        for number, content in enumerate(semantic_chunks(version.normalized_text), 1):
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            if content_hash in seen_content:
                continue
            seen_content.add(content_hash)
            child = KnowledgeChunk(
                document_version_id=version.id,
                index_version_id=index.id,
                parent_chunk_id=parent.id,
                chunk_number=number,
                chunk_type="semantic",
                content=content,
                content_sha256=content_hash,
                token_count=len(content.split()),
                title_path=[document.title],
                source_locator={**version.source_locator, "chunk": number},
                block_ids=[
                    str(block.get("block_id"))
                    for block in version.parsed_blocks
                    if block.get("block_id")
                ],
                allowed_roles=allowed_roles,
                sensitivity=document.sensitivity,
                injection_suspected=any(
                    finding[0] == "prompt_injection" for finding in detect_findings(content)
                ),
                status="published",
            )
            session.add(child)
            await session.flush()
            children.append(child)
            await session.execute(
                text(
                    "INSERT INTO knowledge_embeddings "
                    "(chunk_id,embedding_profile_id,embedding,content_sha256,token_count,"
                    "status,attempts) VALUES (:chunk,:profile,CAST(:embedding AS vector),"
                    ":hash,:tokens,'succeeded',1)"
                ),
                {
                    "chunk": child.id,
                    "profile": profile.id,
                    "embedding": vector_literal(fake_embedding(content, profile.dimensions)),
                    "hash": content_hash,
                    "tokens": child.token_count,
                },
            )
            chunk_count += 1
            embedding_count += 1
        for position, child in enumerate(children):
            child.previous_chunk_id = children[position - 1].id if position else None
            child.next_chunk_id = (
                children[position + 1].id if position + 1 < len(children) else None
            )
    if not manifest or not chunk_count:
        await session.rollback()
        raise VavError(
            "KNOWLEDGE_INDEX_EMPTY",
            "No authorized published documents are available for indexing.",
            status_code=409,
        )
    index.document_version_manifest = manifest
    index.chunk_count = chunk_count
    index.embedding_count = embedding_count
    index.validation_report = {
        "manifest_documents": len(manifest),
        "chunk_embedding_match": chunk_count == embedding_count,
        "duplicate_chunks_suppressed": True,
        "actor_id": str(actor_id) if actor_id else None,
    }
    index.status = "ready_for_evaluation"
    await session.commit()
    return index


async def activate_index_version(
    session: AsyncSession,
    *,
    index: KnowledgeIndexVersion,
    actor_id: UUID,
    reason: str,
) -> KnowledgeIndexVersion:
    if index.evaluation_status != "passed" or index.status != "ready_for_evaluation":
        raise VavError(
            "KNOWLEDGE_INDEX_GATE_FAILED",
            "A passed candidate evaluation is required.",
            status_code=409,
        )
    previous = await session.scalar(
        select(KnowledgeIndexVersion)
        .where(
            KnowledgeIndexVersion.space_id == index.space_id,
            KnowledgeIndexVersion.status == "active",
        )
        .with_for_update()
    )
    if previous:
        previous.status = "superseded"
        index.previous_index_id = previous.id
        await session.flush()
    index.status = "active"
    index.activated_at = datetime.now(UTC)
    await session.execute(
        text(
            "INSERT INTO knowledge_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,details_encrypted) "
            "VALUES ('knowledge.index.activated',:actor,'index_version',:subject,"
            ":reason,:details)"
        ),
        {
            "actor": actor_id,
            "subject": index.id,
            "reason": reason,
            "details": encrypt_sensitive(
                {"previous_index_id": str(previous.id) if previous else None}
            ),
        },
    )
    await session.commit()
    return index


async def rollback_index_version(
    session: AsyncSession,
    *,
    current: KnowledgeIndexVersion,
    actor_id: UUID,
    reason: str,
) -> KnowledgeIndexVersion:
    previous = (
        await session.get(KnowledgeIndexVersion, current.previous_index_id)
        if current.previous_index_id
        else None
    )
    if (
        current.status != "active"
        or previous is None
        or previous.evaluation_status != "passed"
        or previous.status != "superseded"
    ):
        raise VavError(
            "KNOWLEDGE_ROLLBACK_UNAVAILABLE",
            "A passed superseded index is required.",
            status_code=409,
        )
    current.status = "rolled_back"
    await session.flush()
    previous.status = "active"
    previous.activated_at = datetime.now(UTC)
    await session.execute(
        text(
            "INSERT INTO knowledge_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,details_encrypted) "
            "VALUES ('knowledge.index.rolled_back',:actor,'index_version',:subject,"
            ":reason,:details)"
        ),
        {
            "actor": actor_id,
            "subject": current.id,
            "reason": reason,
            "details": encrypt_sensitive({"restored_index_id": str(previous.id)}),
        },
    )
    await session.commit()
    return previous
