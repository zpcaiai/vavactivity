from __future__ import annotations

# ruff: noqa: E501
import hashlib
import math
import re
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.knowledge import (
    KnowledgeAuthorization,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeEmbeddingProfile,
    KnowledgeIndexVersion,
    KnowledgeParsedBlock,
    KnowledgeParsingReport,
    KnowledgeSource,
    KnowledgeSpace,
)
from vav.modules.courses.crypto import encrypt_sensitive
from vav.modules.knowledge.parsing import parse_document


def now() -> datetime:
    return datetime.now(UTC)


def fake_embedding(value: str, dimensions: int = 64) -> list[float]:
    """Deterministic local-only feature hashing with overlap semantics."""
    normalized = value.casefold()
    words = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]", normalized)
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    features = words + [cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))]
    result = [0.0] * dimensions
    for feature in features:
        digest = hashlib.sha256(feature.encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        result[bucket] += 1.0 if digest[4] % 2 == 0 else -1.0
    norm = math.sqrt(sum(item * item for item in result)) or 1.0
    return [item / norm for item in result]


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{item:.9f}" for item in values) + "]"


def normalize_text(value: str) -> str:
    return "\n".join(
        line.strip() for line in value.replace("\r\n", "\n").splitlines() if line.strip()
    )


def detect_findings(value: str) -> list[tuple[str, str, bool]]:
    findings: list[tuple[str, str, bool]] = []
    if re.search(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*\S+", value):
        findings.append(("secret", "critical", True))
    if re.search(
        r"(?i)(ignore (all|previous) instructions|system prompt|execute this tool)", value
    ):
        findings.append(("prompt_injection", "high", False))
    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", value):
        findings.append(("pii", "high", True))
    return findings


def semantic_chunks(value: str, target_words: int = 160) -> list[str]:
    paragraphs = [item.strip() for item in value.split("\n") if item.strip()]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        words = paragraph.split()
        if current and size + len(words) > target_words:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(paragraph)
        size += len(words)
    if current:
        chunks.append("\n".join(current))
    return chunks or [value]


async def active_authorization(
    session: AsyncSession,
    source_id: UUID,
    *,
    document_id: UUID | None = None,
    require_quote: bool = False,
) -> KnowledgeAuthorization | None:
    current = now()
    conditions = [
        KnowledgeAuthorization.source_id == source_id,
        KnowledgeAuthorization.status == "approved",
        KnowledgeAuthorization.allow_rag.is_(True),
        KnowledgeAuthorization.allowed_uses.op("?")("rag_retrieval"),
        ~KnowledgeAuthorization.prohibited_uses.op("?")("rag_retrieval"),
        KnowledgeAuthorization.valid_from <= current,
        KnowledgeAuthorization.revoked_at.is_(None),
        (
            KnowledgeAuthorization.valid_until.is_(None)
            | (KnowledgeAuthorization.valid_until > current)
        ),
    ]
    if require_quote:
        conditions.append(KnowledgeAuthorization.allow_public_quote.is_(True))
    if document_id is not None:
        document_authorization_exists = await session.scalar(
            select(KnowledgeAuthorization.id)
            .where(KnowledgeAuthorization.document_id == document_id)
            .limit(1)
        )
        conditions.append(
            KnowledgeAuthorization.document_id == document_id
            if document_authorization_exists
            else KnowledgeAuthorization.document_id.is_(None)
        )
    value: KnowledgeAuthorization | None = await session.scalar(
        select(KnowledgeAuthorization)
        .where(*conditions)
        .order_by(KnowledgeAuthorization.version.desc())
        .limit(1)
    )
    return value


class KnowledgeService:
    async def ingest(
        self,
        session: AsyncSession,
        *,
        source: KnowledgeSource,
        document_code: str,
        title: str,
        locale: str,
        mime_type: str,
        raw_text: str,
        source_locator: dict[str, object],
        source_filename: str | None = None,
        raw_payload: bytes | None = None,
    ) -> KnowledgeDocumentVersion:
        payload = raw_payload if raw_payload is not None else raw_text.encode()
        parsed = parse_document(payload, mime_type)
        normalized = parsed.normalized_text
        checksum = hashlib.sha256(payload).hexdigest()
        document = await session.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.document_code == document_code)
        )
        if document is None:
            document = KnowledgeDocument(
                source_id=source.id,
                space_id=source.space_id,
                document_code=document_code,
                title=title,
                locale=locale,
                document_type=source.source_type,
                sensitivity=source.sensitivity,
                status="processing",
            )
            session.add(document)
            await session.flush()
        existing = await session.scalar(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == document.id,
                KnowledgeDocumentVersion.checksum_sha256 == checksum,
                KnowledgeDocumentVersion.source_reference_snapshot == source_locator,
            )
        )
        if existing:
            return existing
        number = (
            await session.scalar(
                select(func.max(KnowledgeDocumentVersion.version_number)).where(
                    KnowledgeDocumentVersion.document_id == document.id
                )
            )
            or 0
        ) + 1
        findings = detect_findings(normalized)
        quality = parsed.quality_bps
        low_quality = quality < get_settings().knowledge_min_parse_quality_bps
        version = KnowledgeDocumentVersion(
            document_id=document.id,
            version_number=number,
            status="blocked" if any(item[2] for item in findings) else "review_required",
            mime_type=mime_type,
            checksum_sha256=checksum,
            source_filename=source_filename,
            source_byte_size=len(payload),
            raw_text_encrypted=encrypt_sensitive({"text": raw_text}),
            normalized_text=normalized,
            parsed_blocks=parsed.blocks,
            parse_quality_bps=quality,
            source_locator=source_locator,
            source_reference_snapshot=source_locator,
            processing_configuration={
                "parser": parsed.parser_name,
                "minimum_quality_bps": get_settings().knowledge_min_parse_quality_bps,
            },
        )
        session.add(version)
        await session.flush()
        for index, block in enumerate(parsed.blocks):
            session.add(
                KnowledgeParsedBlock(
                    document_version_id=version.id,
                    block_index=index,
                    block_id=str(block["block_id"]),
                    block_type=str(block["block_type"]),
                    raw_text_encrypted=encrypt_sensitive({"text": block.get("text")}),
                    normalized_text=str(block.get("text") or ""),
                    heading_level=block.get("heading_level"),
                    page_number=block.get("page_number"),
                    section_path=list(block.get("section_path") or []),
                    source_locator=dict(block.get("source_locator") or {}),
                    parsing_metadata={"parser": parsed.parser_name},
                    parent_block_id=block.get("parent_block_id"),
                )
            )
        session.add(
            KnowledgeParsingReport(
                document_version_id=version.id,
                parser_name=parsed.parser_name,
                parser_version="1",
                text_character_count=len(normalized),
                block_count=len(parsed.blocks),
                page_count=parsed.page_count,
                quality_score_basis_points=quality,
                warnings=parsed.warnings,
                errors=[],
                requires_manual_review=low_quality,
            )
        )
        for finding_type, severity, blocks in findings:
            await session.execute(
                text(
                    "INSERT INTO knowledge_findings "
                    "(document_version_id,finding_type,severity,details_encrypted,blocks_publication) "
                    "VALUES (:version_id,:type,:severity,:details,:blocks)"
                ),
                {
                    "version_id": version.id,
                    "type": finding_type,
                    "severity": severity,
                    "details": encrypt_sensitive({"finding": finding_type}),
                    "blocks": blocks,
                },
            )
        await session.commit()
        return version

    async def publish(
        self,
        session: AsyncSession,
        *,
        version: KnowledgeDocumentVersion,
        allowed_roles: list[str],
        actor_id: UUID | None = None,
        reason: str = "approved publication",
    ) -> int:
        document = await session.get(KnowledgeDocument, version.document_id)
        assert document is not None
        source = await session.get(KnowledgeSource, document.source_id)
        assert source is not None
        if await active_authorization(session, source.id, document_id=document.id) is None:
            raise VavError(
                "KNOWLEDGE_AUTHORIZATION_REQUIRED",
                "Valid RAG authorization is required.",
                status_code=409,
            )
        if version.status != "approved":
            raise VavError(
                "KNOWLEDGE_REVIEW_REQUIRED",
                "The document version must pass human review before publication.",
                status_code=409,
            )
        blockers = await session.scalar(
            text(
                "SELECT count(*) FROM knowledge_findings "
                "WHERE document_version_id=:id AND blocks_publication=true AND status='open'"
            ),
            {"id": version.id},
        )
        if blockers:
            raise VavError(
                "KNOWLEDGE_PUBLICATION_BLOCKED",
                "Blocking content findings must be resolved.",
                status_code=409,
            )
        index = await session.scalar(
            select(KnowledgeIndexVersion)
            .where(
                KnowledgeIndexVersion.space_id == source.space_id,
                KnowledgeIndexVersion.status == "active",
            )
            .limit(1)
        )
        if index is None:
            raise VavError(
                "KNOWLEDGE_INDEX_NOT_ACTIVE", "An active index is required.", status_code=409
            )
        profile = await session.get(KnowledgeEmbeddingProfile, index.embedding_profile_id)
        assert profile is not None
        chunks = semantic_chunks(version.normalized_text)
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
            sensitivity=source.sensitivity,
            injection_suspected=any(
                item[0] == "prompt_injection" for item in detect_findings(version.normalized_text)
            ),
            status="published",
        )
        session.add(parent)
        await session.flush()
        for number, content in enumerate(chunks, 1):
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            injection = any(item[0] == "prompt_injection" for item in detect_findings(content))
            chunk = KnowledgeChunk(
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
                allowed_roles=allowed_roles,
                sensitivity=source.sensitivity,
                injection_suspected=injection,
                status="published",
            )
            session.add(chunk)
            await session.flush()
            embedding = vector_literal(fake_embedding(content, profile.dimensions))
            await session.execute(
                text(
                    "INSERT INTO knowledge_embeddings "
                    "(chunk_id,embedding_profile_id,embedding,content_sha256,token_count) "
                    "VALUES (:chunk,:profile,CAST(:embedding AS vector),:hash,:tokens)"
                ),
                {
                    "chunk": chunk.id,
                    "profile": profile.id,
                    "embedding": embedding,
                    "hash": content_hash,
                    "tokens": chunk.token_count,
                },
            )
        version.status = "published"
        version.published_at = now()
        document.status = "published"
        document.current_version_id = version.id
        document.published_version_id = version.id
        if actor_id:
            await session.execute(
                text(
                    "INSERT INTO knowledge_audit_events "
                    "(event_type,actor_id,subject_type,subject_id,reason,details_encrypted) "
                    "VALUES ('knowledge.document.published',:actor,'document_version',"
                    ":subject,:reason,:details)"
                ),
                {
                    "actor": actor_id,
                    "subject": version.id,
                    "reason": reason,
                    "details": encrypt_sensitive(
                        {"document_id": str(document.id), "allowed_roles": allowed_roles}
                    ),
                },
            )
        await session.commit()
        return len(chunks)

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        space: KnowledgeSpace,
        query: str,
        locale: str,
        region: str | None,
        roles: list[str],
        top_k: int,
        public: bool,
        actor_id: UUID | None,
        index_version_id: UUID | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        index = (
            await session.get(KnowledgeIndexVersion, index_version_id)
            if index_version_id
            else await session.scalar(
                select(KnowledgeIndexVersion).where(
                    KnowledgeIndexVersion.space_id == space.id,
                    KnowledgeIndexVersion.status == "active",
                )
            )
        )
        if index is None or index.space_id != space.id:
            return {"items": [], "no_answer": True}
        profile = await session.get(KnowledgeEmbeddingProfile, index.embedding_profile_id)
        assert profile is not None
        role_set = set(roles)
        if space.allowed_roles and not role_set.intersection(space.allowed_roles):
            return {"items": [], "no_answer": True, "latency_ms": 0}
        base_sql = """
          FROM knowledge_chunks kc
          JOIN knowledge_document_versions dv ON dv.id=kc.document_version_id
          JOIN knowledge_documents d ON d.id=dv.document_id AND d.current_version_id=dv.id
          JOIN knowledge_sources s ON s.id=d.source_id
          JOIN knowledge_embeddings e ON e.chunk_id=kc.id AND e.embedding_profile_id=:profile
          WHERE kc.index_version_id=:index AND kc.status='published' AND kc.chunk_type!='parent'
            AND dv.status='published'
            AND d.locale=:locale
            AND (d.valid_from IS NULL OR d.valid_from<=now())
            AND (d.valid_until IS NULL OR d.valid_until>now())
            AND (kc.allowed_roles='[]'::jsonb OR kc.allowed_roles ?| CAST(:roles AS text[]))
            AND EXISTS (
              SELECT 1 FROM knowledge_authorizations a
              WHERE a.source_id=s.id AND a.status='approved' AND a.allow_rag=true
                AND a.revoked_at IS NULL AND a.valid_from<=now()
                AND (a.valid_until IS NULL OR a.valid_until>now())
                AND (CAST(:region AS text) IS NULL OR a.allowed_regions='[]'::jsonb
                     OR a.allowed_regions ? CAST(:region AS text))
                AND (CAST(:region AS text) IS NULL OR NOT (
                     a.prohibited_regions ? CAST(:region AS text)))
                AND a.allowed_uses ? 'rag_retrieval'
                AND NOT (a.prohibited_uses ? 'rag_retrieval')
                AND (:public=false OR a.allow_public_quote=true)
                AND (
                  a.document_id=d.id OR (
                    a.document_id IS NULL AND NOT EXISTS (
                      SELECT 1 FROM knowledge_authorizations da WHERE da.document_id=d.id
                    )
                  )
                )
            )
            AND (:public=false OR s.sensitivity='public')
        """
        vector_rows = (
            await session.execute(
                text(
                    "SELECT kc.id, (e.embedding <=> CAST(:embedding AS vector)) AS distance "
                    + base_sql
                    + " ORDER BY distance, kc.id LIMIT 40"
                ),
                {
                    "embedding": vector_literal(fake_embedding(query, profile.dimensions)),
                    "profile": profile.id,
                    "index": index.id,
                    "locale": locale,
                    "region": region,
                    "roles": sorted(role_set),
                    "public": public,
                },
            )
        ).all()
        lexical_rows = (
            await session.execute(
                text(
                    "SELECT kc.id, ts_rank_cd(kc.search_vector, plainto_tsquery('simple', :query)) AS score "
                    + base_sql
                    + " AND kc.search_vector @@ plainto_tsquery('simple', :query) ORDER BY score DESC, kc.id LIMIT 40"
                ),
                {
                    "query": query,
                    "profile": profile.id,
                    "index": index.id,
                    "locale": locale,
                    "region": region,
                    "roles": sorted(role_set),
                    "public": public,
                },
            )
        ).all()
        scores: dict[UUID, float] = {}
        for rank, row in enumerate(vector_rows, 1):
            scores[row.id] = scores.get(row.id, 0.0) + 1 / (60 + rank)
        for rank, row in enumerate(lexical_rows, 1):
            scores[row.id] = scores.get(row.id, 0.0) + 1 / (60 + rank)
        ordered = sorted(scores, key=lambda item: (-scores[item], str(item)))
        distances = {row.id: float(row.distance) for row in vector_rows}
        lexical_ids = {row.id for row in lexical_rows}
        items: list[dict[str, Any]] = []
        for chunk_id in ordered:
            chunk = await session.get(KnowledgeChunk, chunk_id)
            assert chunk is not None
            if chunk.allowed_roles and not role_set.intersection(chunk.allowed_roles):
                continue
            if chunk_id not in lexical_ids and distances.get(chunk_id, 2.0) > 0.75:
                continue
            version = await session.get(KnowledgeDocumentVersion, chunk.document_version_id)
            assert version is not None
            document = await session.get(KnowledgeDocument, version.document_id)
            assert document is not None
            source = await session.get(KnowledgeSource, document.source_id)
            assert source is not None
            auth = await active_authorization(
                session, source.id, document_id=document.id, require_quote=public
            )
            if auth is None:
                continue
            excerpt = chunk.content[:500] if (not public or auth.allow_public_quote) else None
            items.append(
                {
                    "document_id": str(document.id),
                    "document_code": document.document_code,
                    "document_version_id": str(version.id),
                    "version_number": version.version_number,
                    "chunk_id": str(chunk.id),
                    "parent_chunk_id": str(chunk.parent_chunk_id)
                    if chunk.parent_chunk_id
                    else None,
                    "score": scores[chunk.id],
                    "source_locator": chunk.source_locator,
                    "excerpt": excerpt,
                    "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest()
                    if excerpt
                    else None,
                    "injection_suspected": chunk.injection_suspected,
                }
            )
            if len(items) >= top_k:
                break
        latency = int((time.perf_counter() - started) * 1000)
        scope_hash = hashlib.sha256("|".join(sorted(role_set)).encode()).hexdigest()
        query_id = await session.scalar(
            text(
                "INSERT INTO knowledge_retrieval_queries "
                "(space_id,actor_id,permission_scope_hash,query_encrypted,query_sha256,purpose,region,"
                "candidate_count,index_version_id,locale,result_count,no_answer,latency_ms) "
                "VALUES (:space,:actor,:scope,:query,:query_hash,'rag_retrieval',:region,"
                ":candidates,:index,:locale,:count,:no_answer,:latency) RETURNING id"
            ),
            {
                "space": space.id,
                "actor": actor_id,
                "scope": scope_hash,
                "query": encrypt_sensitive({"query": query, "region": region}),
                "query_hash": hashlib.sha256(query.encode()).hexdigest(),
                "region": region,
                "candidates": len(scores),
                "index": index.id,
                "locale": locale,
                "count": len(items),
                "no_answer": not items,
                "latency": latency,
            },
        )
        for item in items:
            citation_id = await session.scalar(
                text(
                    "INSERT INTO knowledge_citations "
                    "(retrieval_query_id,document_id,document_version_id,chunk_id,source_locator,excerpt,excerpt_sha256) "
                    "VALUES (:query,:document,:version,:chunk,CAST(:locator AS jsonb),"
                    ":excerpt,:hash) RETURNING id"
                ),
                {
                    "query": query_id,
                    "document": UUID(item["document_id"]),
                    "version": UUID(item["document_version_id"]),
                    "chunk": UUID(item["chunk_id"]),
                    "locator": __import__("json").dumps(item["source_locator"]),
                    "excerpt": item["excerpt"],
                    "hash": item["excerpt_sha256"],
                },
            )
            item["citation_id"] = str(citation_id)
        await session.commit()
        return {"items": items, "no_answer": not items, "latency_ms": latency}


knowledge_service = KnowledgeService()
