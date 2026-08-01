# ruff: noqa: B008
import asyncio
import difflib
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.models.knowledge import (
    KnowledgeAuthorization,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeEvaluationCase,
    KnowledgeEvaluationDataset,
    KnowledgeIndexVersion,
    KnowledgeParsedBlock,
    KnowledgeParsingReport,
    KnowledgeSource,
    KnowledgeSpace,
    KnowledgeUpload,
)
from vav.modules.content.media import MediaService
from vav.modules.courses.crypto import decrypt_sensitive, encrypt_sensitive
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.identity.service import roles_for_user
from vav.modules.knowledge.connectors import sync_source
from vav.modules.knowledge.indexing import activate_index_version, rollback_index_version
from vav.modules.knowledge.schemas import (
    AuthorizationDecisionRequest,
    AuthorizationRequest,
    DocumentRequest,
    FindingReviewRequest,
    IndexActionRequest,
    PublishRequest,
    RetrievalRequest,
    ReviewRequest,
    SourceRequest,
    SpaceRequest,
    UploadCompleteRequest,
    UploadCreateRequest,
)
from vav.modules.knowledge.service import active_authorization, knowledge_service

router = APIRouter()


async def require_space(session: AsyncSession, space_id: UUID) -> KnowledgeSpace:
    value = await session.get(KnowledgeSpace, space_id)
    if value is None:
        raise VavError(
            "KNOWLEDGE_SPACE_NOT_FOUND", "Knowledge space was not found.", status_code=404
        )
    return value


@router.get("/admin/knowledge/spaces")
async def list_spaces(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.spaces.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (await session.scalars(select(KnowledgeSpace).order_by(KnowledgeSpace.name))).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "space_code": item.space_code,
                    "name": item.name,
                    "purpose": item.purpose,
                    "status": item.status,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/spaces", status_code=201)
async def create_space(
    payload: SpaceRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("knowledge.spaces.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = KnowledgeSpace(**payload.model_dump(), status="active", created_by=principal.user.id)
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.get("/admin/knowledge/sources")
async def list_sources(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.sources.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(KnowledgeSource).order_by(KnowledgeSource.created_at.desc())
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "space_id": str(item.space_id),
                    "source_code": item.source_code,
                    "source_type": item.source_type,
                    "title": item.title,
                    "sensitivity": item.sensitivity,
                    "status": item.status,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/spaces/{space_id}/sources", status_code=201)
async def create_source(
    space_id: UUID,
    payload: SourceRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.sources.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    await require_space(session, space_id)
    value = KnowledgeSource(space_id=space_id, **payload.model_dump(), status="active")
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success({"id": str(value.id)}, request_id_from_request(request))


@router.post("/admin/knowledge/sources/{source_id}/sync")
async def synchronize_source(
    source_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.sources.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    source = await session.get(KnowledgeSource, source_id)
    if source is None:
        raise VavError(
            "KNOWLEDGE_SOURCE_NOT_FOUND", "Knowledge source was not found.", status_code=404
        )
    versions = await sync_source(session, source)
    return success(
        {
            "source_id": str(source.id),
            "status": "review_required",
            "version_ids": [str(item.id) for item in versions],
            "document_count": len(versions),
        },
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/sources/{source_id}/authorizations", status_code=201)
async def authorize_source(
    source_id: UUID,
    payload: AuthorizationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("knowledge.authorizations.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if await session.get(KnowledgeSource, source_id) is None:
        raise VavError(
            "KNOWLEDGE_SOURCE_NOT_FOUND", "Knowledge source was not found.", status_code=404
        )
    version = (
        await session.scalar(
            select(func.max(KnowledgeAuthorization.version)).where(
                KnowledgeAuthorization.source_id == source_id
            )
        )
        or 0
    ) + 1
    value = KnowledgeAuthorization(
        source_id=source_id,
        status="approved",
        allow_rag=payload.allow_rag,
        allow_public_quote=payload.allow_public_quote,
        allow_external_training=payload.allow_external_training,
        allowed_regions=payload.allowed_regions,
        prohibited_regions=payload.prohibited_regions,
        rights_holder_name=payload.rights_holder_name,
        authorization_basis=payload.authorization_basis,
        allowed_uses=payload.allowed_uses,
        prohibited_uses=payload.prohibited_uses,
        citation_permission=payload.citation_permission,
        evidence_encrypted=encrypt_sensitive(payload.evidence),
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        approved_by=principal.user.id,
        approved_at=datetime.now(UTC),
        version=version,
    )
    session.add(value)
    await session.flush()
    await session.execute(
        text(
            "INSERT INTO knowledge_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,details_encrypted) "
            "VALUES ('knowledge.authorization.approved',:actor,'authorization',:subject,"
            "'source authorization',:details)"
        ),
        {
            "actor": principal.user.id,
            "subject": value.id,
            "details": encrypt_sensitive({"source_id": str(source_id)}),
        },
    )
    await session.commit()
    await session.refresh(value)
    return success(
        {"id": str(value.id), "version": value.version}, request_id_from_request(request)
    )


@router.get("/admin/knowledge/authorizations")
async def list_authorizations(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.authorizations.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(KnowledgeAuthorization).order_by(KnowledgeAuthorization.created_at.desc())
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "source_id": str(item.source_id),
                    "document_id": str(item.document_id) if item.document_id else None,
                    "status": item.status,
                    "rights_holder_name": item.rights_holder_name,
                    "authorization_basis": item.authorization_basis,
                    "allowed_uses": item.allowed_uses,
                    "citation_permission": item.citation_permission,
                    "valid_from": item.valid_from.isoformat(),
                    "valid_until": item.valid_until.isoformat() if item.valid_until else None,
                    "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/documents/{document_id}/authorizations", status_code=201)
async def create_document_authorization(
    document_id: UUID,
    payload: AuthorizationRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.authorizations.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    document = await session.get(KnowledgeDocument, document_id)
    if document is None:
        raise VavError(
            "KNOWLEDGE_DOCUMENT_NOT_FOUND", "Knowledge document was not found.", status_code=404
        )
    version = (
        await session.scalar(
            select(func.max(KnowledgeAuthorization.version)).where(
                KnowledgeAuthorization.document_id == document.id
            )
        )
        or 0
    ) + 1
    value = KnowledgeAuthorization(
        source_id=document.source_id,
        document_id=document.id,
        status="pending",
        allow_rag=payload.allow_rag,
        allow_public_quote=payload.allow_public_quote,
        allow_external_training=payload.allow_external_training,
        allowed_regions=payload.allowed_regions,
        prohibited_regions=payload.prohibited_regions,
        rights_holder_name=payload.rights_holder_name,
        authorization_basis=payload.authorization_basis,
        allowed_uses=payload.allowed_uses,
        prohibited_uses=payload.prohibited_uses,
        citation_permission=payload.citation_permission,
        evidence_encrypted=encrypt_sensitive(payload.evidence),
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        version=version,
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return success(
        {"id": str(value.id), "status": value.status, "version": value.version},
        request_id_from_request(request),
    )


async def decide_authorization(
    *,
    authorization_id: UUID,
    decision: str,
    payload: AuthorizationDecisionRequest,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> KnowledgeAuthorization:
    value = await session.get(KnowledgeAuthorization, authorization_id)
    if value is None:
        raise VavError(
            "KNOWLEDGE_AUTHORIZATION_NOT_FOUND", "Authorization was not found.", status_code=404
        )
    if value.status != "pending":
        raise VavError(
            "KNOWLEDGE_AUTHORIZATION_NOT_PENDING",
            "Only pending authorization can be decided.",
            status_code=409,
        )
    value.status = decision
    value.approved_by = principal.user.id if decision == "approved" else None
    value.approved_at = datetime.now(UTC) if decision == "approved" else None
    await session.execute(
        text(
            "INSERT INTO knowledge_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,details_encrypted) "
            "VALUES (:event,:actor,'authorization',:subject,:reason,:details)"
        ),
        {
            "event": f"knowledge.authorization.{decision}",
            "actor": principal.user.id,
            "subject": value.id,
            "reason": payload.reason,
            "details": encrypt_sensitive({"decision": decision}),
        },
    )
    await session.commit()
    return value


@router.post("/admin/knowledge/authorizations/{authorization_id}/approve")
async def approve_authorization(
    authorization_id: UUID,
    payload: AuthorizationDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("knowledge.authorizations.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await decide_authorization(
        authorization_id=authorization_id,
        decision="approved",
        payload=payload,
        principal=principal,
        session=session,
    )
    return success({"id": str(value.id), "status": value.status}, request_id_from_request(request))


@router.post("/admin/knowledge/authorizations/{authorization_id}/reject")
async def reject_authorization(
    authorization_id: UUID,
    payload: AuthorizationDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("knowledge.authorizations.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await decide_authorization(
        authorization_id=authorization_id,
        decision="rejected",
        payload=payload,
        principal=principal,
        session=session,
    )
    return success({"id": str(value.id), "status": value.status}, request_id_from_request(request))


@router.post("/admin/knowledge/authorizations/{authorization_id}/revoke")
async def revoke_authorization(
    authorization_id: UUID,
    payload: IndexActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("knowledge.authorizations.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(KnowledgeAuthorization, authorization_id)
    if value is None:
        raise VavError(
            "KNOWLEDGE_AUTHORIZATION_NOT_FOUND", "Authorization was not found.", status_code=404
        )
    value.status = "revoked"
    value.revoked_at = datetime.now(UTC)
    value.revoked_by = principal.user.id
    value.revocation_reason = payload.reason
    value.version += 1
    if value.document_id:
        document = await session.get(KnowledgeDocument, value.document_id)
        if document:
            document.status = "revoked"
        await session.execute(
            text(
                "UPDATE knowledge_chunks SET status='revoked' WHERE document_version_id IN "
                "(SELECT id FROM knowledge_document_versions WHERE document_id=:document)"
            ),
            {"document": value.document_id},
        )
        await session.execute(
            text(
                "UPDATE knowledge_citations SET availability_status='source_revoked' "
                "WHERE document_id=:document"
            ),
            {"document": value.document_id},
        )
        await session.execute(
            text(
                "UPDATE knowledge_processing_jobs SET status='cancelled', "
                "error_code='AUTHORIZATION_REVOKED' WHERE status IN ('queued','running') "
                "AND document_version_id IN "
                "(SELECT id FROM knowledge_document_versions WHERE document_id=:document)"
            ),
            {"document": value.document_id},
        )
    await session.execute(
        text(
            "INSERT INTO knowledge_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,details_encrypted) "
            "VALUES ('knowledge.authorization.revoked',:actor,'authorization',:subject,"
            ":reason,:details)"
        ),
        {
            "actor": principal.user.id,
            "subject": value.id,
            "reason": payload.reason,
            "details": encrypt_sensitive({"document_id": str(value.document_id)}),
        },
    )
    await session.commit()
    return success(
        {"id": str(value.id), "status": value.status, "reason": payload.reason},
        request_id_from_request(request),
    )


@router.get("/admin/knowledge/authorizations/{authorization_id}/impact")
async def authorization_impact(
    authorization_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.authorizations.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(KnowledgeAuthorization, authorization_id)
    if value is None:
        raise VavError(
            "KNOWLEDGE_AUTHORIZATION_NOT_FOUND", "Authorization was not found.", status_code=404
        )
    document_filter = "d.id=:document" if value.document_id else "d.source_id=:source"
    impact = (
        await session.execute(
            text(
                "SELECT count(DISTINCT d.id) AS documents, count(DISTINCT kc.id) AS chunks, "
                "count(DISTINCT ke.id) AS embeddings FROM knowledge_documents d "
                "LEFT JOIN knowledge_document_versions dv ON dv.document_id=d.id "
                "LEFT JOIN knowledge_chunks kc ON kc.document_version_id=dv.id "
                "LEFT JOIN knowledge_embeddings ke ON ke.chunk_id=kc.id WHERE " + document_filter
            ),
            {"document": value.document_id, "source": value.source_id},
        )
    ).one()
    return success(
        {
            "authorization_id": str(value.id),
            "document_count": impact.documents,
            "chunk_count": impact.chunks,
            "embedding_count": impact.embeddings,
            "requires_index_repair": bool(impact.chunks),
        },
        request_id_from_request(request),
    )


@router.get("/admin/knowledge/documents")
async def list_documents(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "document_code": item.document_code,
                    "title": item.title,
                    "locale": item.locale,
                    "status": item.status,
                    "current_version_id": str(item.current_version_id)
                    if item.current_version_id
                    else None,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.get("/admin/knowledge/documents/{document_id}")
async def document_detail(
    document_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    document = await session.get(KnowledgeDocument, document_id)
    if document is None:
        raise VavError(
            "KNOWLEDGE_DOCUMENT_NOT_FOUND", "Knowledge document was not found.", status_code=404
        )
    versions = list(
        (
            await session.scalars(
                select(KnowledgeDocumentVersion)
                .where(KnowledgeDocumentVersion.document_id == document.id)
                .order_by(KnowledgeDocumentVersion.version_number.desc())
            )
        ).all()
    )
    return success(
        {
            "id": str(document.id),
            "document_code": document.document_code,
            "title": document.title,
            "locale": document.locale,
            "status": document.status,
            "sensitivity": document.sensitivity,
            "versions": [
                {
                    "id": str(version.id),
                    "version_number": version.version_number,
                    "status": version.status,
                    "mime_type": version.mime_type,
                    "checksum_sha256": version.checksum_sha256,
                    "parse_quality_bps": version.parse_quality_bps,
                    "published_at": version.published_at.isoformat()
                    if version.published_at
                    else None,
                }
                for version in versions
            ],
        },
        request_id_from_request(request),
    )


@router.get("/admin/knowledge/document-versions/{version_id}/parsing")
async def parsing_preview(
    version_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    report = await session.scalar(
        select(KnowledgeParsingReport).where(
            KnowledgeParsingReport.document_version_id == version_id
        )
    )
    if report is None:
        raise VavError(
            "KNOWLEDGE_PARSING_NOT_FOUND", "Parsing report was not found.", status_code=404
        )
    blocks = list(
        (
            await session.scalars(
                select(KnowledgeParsedBlock)
                .where(KnowledgeParsedBlock.document_version_id == version_id)
                .order_by(KnowledgeParsedBlock.block_index)
            )
        ).all()
    )
    return success(
        {
            "report": {
                "parser_name": report.parser_name,
                "quality_score_basis_points": report.quality_score_basis_points,
                "requires_manual_review": report.requires_manual_review,
                "warnings": report.warnings,
                "errors": report.errors,
            },
            "blocks": [
                {
                    "id": str(block.id),
                    "block_id": block.block_id,
                    "block_type": block.block_type,
                    "text": block.normalized_text,
                    "heading_level": block.heading_level,
                    "page_number": block.page_number,
                    "section_path": block.section_path,
                    "source_locator": block.source_locator,
                }
                for block in blocks
            ],
        },
        request_id_from_request(request),
    )


@router.get("/admin/knowledge/document-versions/{version_id}/chunks")
async def chunk_inspector(
    version_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    chunks = list(
        (
            await session.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.document_version_id == version_id)
                .order_by(KnowledgeChunk.index_version_id, KnowledgeChunk.chunk_number)
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(chunk.id),
                    "index_version_id": str(chunk.index_version_id),
                    "parent_chunk_id": str(chunk.parent_chunk_id)
                    if chunk.parent_chunk_id
                    else None,
                    "previous_chunk_id": str(chunk.previous_chunk_id)
                    if chunk.previous_chunk_id
                    else None,
                    "next_chunk_id": str(chunk.next_chunk_id) if chunk.next_chunk_id else None,
                    "chunk_type": chunk.chunk_type,
                    "content": chunk.content,
                    "content_sha256": chunk.content_sha256,
                    "token_count": chunk.token_count,
                    "block_ids": chunk.block_ids,
                    "source_locator": chunk.source_locator,
                }
                for chunk in chunks
            ]
        },
        request_id_from_request(request),
    )


@router.get("/admin/knowledge/document-versions/{left_id}/diff/{right_id}")
async def version_diff(
    left_id: UUID,
    right_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    left = await session.get(KnowledgeDocumentVersion, left_id)
    right = await session.get(KnowledgeDocumentVersion, right_id)
    if left is None or right is None or left.document_id != right.document_id:
        raise VavError(
            "KNOWLEDGE_VERSION_DIFF_INVALID",
            "Both versions must exist and belong to the same document.",
            status_code=404,
        )
    lines = list(
        difflib.unified_diff(
            left.normalized_text.splitlines(),
            right.normalized_text.splitlines(),
            fromfile=f"v{left.version_number}",
            tofile=f"v{right.version_number}",
            lineterm="",
        )
    )
    return success(
        {
            "left_version": left.version_number,
            "right_version": right.version_number,
            "diff": lines,
            "checksum_changed": left.checksum_sha256 != right.checksum_sha256,
            "parse_quality_delta_bps": right.parse_quality_bps - left.parse_quality_bps,
        },
        request_id_from_request(request),
    )


@router.get("/admin/knowledge/document-versions/{version_id}/findings")
async def list_findings(
    version_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.review")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id,finding_type,severity,locator,blocks_publication,status,created_at "
                "FROM knowledge_findings WHERE document_version_id=:version ORDER BY created_at"
            ),
            {"version": version_id},
        )
    ).mappings()
    return success(
        {"items": [dict(row) | {"id": str(row["id"])} for row in rows]},
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/findings/{finding_id}/review")
async def review_finding(
    finding_id: UUID,
    payload: FindingReviewRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.review")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    updated = await session.scalar(
        text(
            "UPDATE knowledge_findings SET status=:status,reviewed_by=:actor,reviewed_at=now(),"
            "resolution=:resolution WHERE id=:id RETURNING id"
        ),
        {
            "status": payload.decision,
            "actor": principal.user.id,
            "resolution": payload.resolution,
            "id": finding_id,
        },
    )
    if updated is None:
        raise VavError("KNOWLEDGE_FINDING_NOT_FOUND", "Finding was not found.", status_code=404)
    await session.commit()
    return success(
        {"id": str(updated), "status": payload.decision}, request_id_from_request(request)
    )


@router.post("/admin/knowledge/uploads", status_code=201)
async def create_private_upload(
    payload: UploadCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.ingest")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    source = await session.get(KnowledgeSource, payload.source_id)
    if source is None:
        raise VavError(
            "KNOWLEDGE_SOURCE_NOT_FOUND", "Knowledge source was not found.", status_code=404
        )
    maximum = get_settings().knowledge_max_upload_size_mb * 1024 * 1024
    if payload.byte_size > maximum:
        raise VavError(
            "KNOWLEDGE_FILE_TOO_LARGE", "File exceeds the configured limit.", status_code=413
        )
    upload_id = uuid4()
    filename = Path(payload.filename).name
    object_key = f"knowledge/{upload_id}/{filename}"
    bucket = get_settings().media_bucket_private
    upload = KnowledgeUpload(
        id=upload_id,
        source_id=source.id,
        document_code=payload.document_code,
        title=payload.title,
        locale=payload.locale,
        filename=filename,
        declared_mime_type=payload.mime_type,
        expected_byte_size=payload.byte_size,
        expected_sha256=payload.checksum_sha256.casefold(),
        bucket_name=bucket,
        object_key_encrypted=encrypt_sensitive({"object_key": object_key}),
        created_by=principal.user.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    session.add(upload)
    await session.commit()
    url = (
        MediaService()
        .client(get_settings().media_s3_public_endpoint)
        .generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": object_key,
                "ContentType": payload.mime_type,
                "Metadata": {"sha256": payload.checksum_sha256.casefold()},
            },
            ExpiresIn=900,
        )
    )
    return success(
        {
            "id": str(upload.id),
            "status": upload.status,
            "upload_url": url,
            "required_headers": {
                "Content-Type": payload.mime_type,
                "x-amz-meta-sha256": payload.checksum_sha256.casefold(),
            },
            "expires_at": upload.expires_at.isoformat(),
        },
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/uploads/{upload_id}/complete")
async def complete_private_upload(
    upload_id: UUID,
    payload: UploadCompleteRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.ingest")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    upload = await session.get(KnowledgeUpload, upload_id)
    if upload is None:
        raise VavError("KNOWLEDGE_UPLOAD_NOT_FOUND", "Upload was not found.", status_code=404)
    if upload.status != "pending_upload" or upload.expires_at <= datetime.now(UTC):
        raise VavError(
            "KNOWLEDGE_UPLOAD_NOT_COMPLETABLE",
            "Upload is expired or already completed.",
            status_code=409,
        )
    if payload.checksum_sha256.casefold() != upload.expected_sha256:
        raise VavError(
            "KNOWLEDGE_CHECKSUM_MISMATCH", "Upload checksum does not match.", status_code=422
        )
    storage = decrypt_sensitive(upload.object_key_encrypted)
    object_key = str(storage["object_key"])
    response = await asyncio.to_thread(
        MediaService().client().get_object,
        Bucket=upload.bucket_name,
        Key=object_key,
    )
    body = response.get("Body")
    if body is None:
        raise VavError(
            "KNOWLEDGE_UPLOAD_MISSING", "Uploaded object is unavailable.", status_code=409
        )
    raw = await asyncio.to_thread(body.read)
    if len(raw) != upload.expected_byte_size:
        raise VavError("KNOWLEDGE_SIZE_MISMATCH", "Upload size does not match.", status_code=422)
    if hashlib.sha256(raw).hexdigest() != upload.expected_sha256:
        raise VavError(
            "KNOWLEDGE_CHECKSUM_MISMATCH", "Upload checksum does not match.", status_code=422
        )
    if response.get("Metadata", {}).get("sha256") != upload.expected_sha256:
        raise VavError(
            "KNOWLEDGE_CHECKSUM_MISMATCH",
            "Upload metadata checksum does not match.",
            status_code=422,
        )
    source = await session.get(KnowledgeSource, upload.source_id)
    assert source is not None
    version = await knowledge_service.ingest(
        session,
        source=source,
        document_code=upload.document_code,
        title=upload.title,
        locale=upload.locale,
        mime_type=upload.declared_mime_type,
        raw_text="",
        raw_payload=raw,
        source_filename=upload.filename,
        source_locator={"upload_id": str(upload.id), "filename": upload.filename},
    )
    version.original_storage_key_encrypted = upload.object_key_encrypted
    upload.status = "completed"
    upload.virus_scan_status = "passed"
    upload.completed_at = datetime.now(UTC)
    await session.commit()
    return success(
        {
            "id": str(upload.id),
            "status": upload.status,
            "document_version_id": str(version.id),
            "document_status": version.status,
        },
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/sources/{source_id}/documents", status_code=201)
async def ingest_document(
    source_id: UUID,
    payload: DocumentRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.ingest")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    source = await session.get(KnowledgeSource, source_id)
    if source is None:
        raise VavError(
            "KNOWLEDGE_SOURCE_NOT_FOUND", "Knowledge source was not found.", status_code=404
        )
    value = await knowledge_service.ingest(
        session,
        source=source,
        document_code=payload.document_code,
        title=payload.title,
        locale=payload.locale,
        mime_type=payload.mime_type,
        raw_text=payload.text,
        source_locator=payload.source_locator,
    )
    return success(
        {
            "id": str(value.id),
            "version_number": value.version_number,
            "status": value.status,
            "allowed_roles": payload.allowed_roles,
        },
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/sources/{source_id}/upload", status_code=201)
async def upload_document(
    source_id: UUID,
    request: Request,
    file: UploadFile = File(),
    document_code: str = Form(),
    title: str = Form(),
    locale: str = Form(default="zh-CN"),
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.ingest")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    source = await session.get(KnowledgeSource, source_id)
    if source is None:
        raise VavError(
            "KNOWLEDGE_SOURCE_NOT_FOUND", "Knowledge source was not found.", status_code=404
        )
    allowed = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "text/html",
        "application/json",
    }
    if file.content_type not in allowed:
        raise VavError("KNOWLEDGE_MIME_UNSUPPORTED", "File type is not supported.", status_code=415)
    raw = await file.read(get_settings().knowledge_max_upload_size_mb * 1024 * 1024 + 1)
    if len(raw) > get_settings().knowledge_max_upload_size_mb * 1024 * 1024:
        raise VavError(
            "KNOWLEDGE_FILE_TOO_LARGE", "File exceeds the configured limit.", status_code=413
        )
    value = await knowledge_service.ingest(
        session,
        source=source,
        document_code=document_code,
        title=title,
        locale=locale,
        mime_type=file.content_type,
        raw_text="",
        source_locator={"filename": file.filename, "upload": True},
        source_filename=file.filename,
        raw_payload=raw,
    )
    return success(
        {"id": str(value.id), "version_number": value.version_number, "status": value.status},
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/document-versions/{version_id}/review")
async def review_document_version(
    version_id: UUID,
    payload: ReviewRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.review")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    version = await session.get(KnowledgeDocumentVersion, version_id)
    if version is None:
        raise VavError(
            "KNOWLEDGE_VERSION_NOT_FOUND", "Document version was not found.", status_code=404
        )
    version.status = "approved" if payload.decision == "approve" else "rejected"
    await session.execute(
        text(
            "INSERT INTO knowledge_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,details_encrypted) "
            "VALUES ('knowledge.document.reviewed',:actor,'document_version',:subject,"
            ":reason,:details)"
        ),
        {
            "actor": principal.user.id,
            "subject": version.id,
            "reason": payload.reason,
            "details": encrypt_sensitive({"decision": payload.decision}),
        },
    )
    await session.commit()
    return success(
        {"id": str(version.id), "status": version.status}, request_id_from_request(request)
    )


@router.post("/admin/knowledge/document-versions/{version_id}/publish")
async def publish_document(
    version_id: UUID,
    payload: PublishRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.publish")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    version = await session.get(KnowledgeDocumentVersion, version_id)
    if version is None:
        raise VavError(
            "KNOWLEDGE_VERSION_NOT_FOUND", "Document version was not found.", status_code=404
        )
    count = await knowledge_service.publish(
        session,
        version=version,
        allowed_roles=payload.allowed_roles,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    return success(
        {"id": str(version.id), "status": version.status, "chunks": count},
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/retrieval/debug")
async def debug_retrieval(
    payload: RetrievalRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("knowledge.retrieval.debug")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    space = await session.scalar(
        select(KnowledgeSpace).where(KnowledgeSpace.space_code == payload.space_code)
    )
    if space is None:
        raise VavError(
            "KNOWLEDGE_SPACE_NOT_FOUND", "Knowledge space was not found.", status_code=404
        )
    actual_roles = await roles_for_user(session, principal.user.id)
    if not set(payload.roles).issubset(actual_roles):
        raise VavError(
            "KNOWLEDGE_ROLE_SIMULATION_FORBIDDEN",
            "Retrieval roles must be assigned to the current administrator.",
            status_code=403,
        )
    value = await knowledge_service.retrieve(
        session,
        space=space,
        actor_id=principal.user.id,
        **payload.model_dump(exclude={"space_code"}),
    )
    return success(value, request_id_from_request(request))


@router.get("/admin/knowledge/citations/{citation_id}/verify")
async def verify_citation(
    citation_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.documents.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT c.id,c.document_id,c.document_version_id,c.chunk_id,c.excerpt,"
                    "c.excerpt_sha256,c.availability_status,d.source_id,"
                    "d.status AS document_status,"
                    "kc.content_sha256 FROM knowledge_citations c "
                    "JOIN knowledge_documents d ON d.id=c.document_id "
                    "JOIN knowledge_chunks kc ON kc.id=c.chunk_id WHERE c.id=:id"
                ),
                {"id": citation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise VavError("KNOWLEDGE_CITATION_NOT_FOUND", "Citation was not found.", status_code=404)
    authorization = await active_authorization(
        session, row["source_id"], document_id=row["document_id"]
    )
    excerpt_hash_valid = (
        hashlib.sha256(row["excerpt"].encode()).hexdigest() == row["excerpt_sha256"]
        if row["excerpt"] and row["excerpt_sha256"]
        else row["excerpt"] is None
    )
    available = (
        row["availability_status"] == "available"
        and row["document_status"] == "published"
        and authorization is not None
        and excerpt_hash_valid
    )
    return success(
        {
            "citation_id": str(row["id"]),
            "document_id": str(row["document_id"]),
            "document_version_id": str(row["document_version_id"]),
            "chunk_id": str(row["chunk_id"]),
            "available": available,
            "availability_status": "available" if available else "source_unavailable",
            "excerpt_hash_valid": excerpt_hash_valid,
            "chunk_content_sha256": row["content_sha256"],
        },
        request_id_from_request(request),
    )


@router.get("/admin/knowledge/indexes")
async def list_indexes(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.indexes.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    values = list(
        (
            await session.scalars(
                select(KnowledgeIndexVersion).order_by(KnowledgeIndexVersion.created_at.desc())
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "space_id": str(item.space_id),
                    "version_number": item.version_number,
                    "status": item.status,
                    "evaluation_status": item.evaluation_status,
                    "previous_index_id": str(item.previous_index_id)
                    if item.previous_index_id
                    else None,
                }
                for item in values
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/indexes/{index_id}/activate")
async def activate_index(
    index_id: UUID,
    payload: IndexActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("knowledge.indexes.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.get(KnowledgeIndexVersion, index_id)
    if value is None:
        raise VavError(
            "KNOWLEDGE_INDEX_NOT_FOUND", "Knowledge index was not found.", status_code=404
        )
    value = await activate_index_version(
        session,
        index=value,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    return success(
        {"id": str(value.id), "status": value.status, "reason": payload.reason},
        request_id_from_request(request),
    )


@router.post("/admin/knowledge/indexes/{index_id}/rollback")
async def rollback_index(
    index_id: UUID,
    payload: IndexActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("knowledge.indexes.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    current = await session.get(KnowledgeIndexVersion, index_id)
    if current is None:
        raise VavError(
            "KNOWLEDGE_INDEX_NOT_FOUND", "Knowledge index was not found.", status_code=404
        )
    previous = await rollback_index_version(
        session,
        current=current,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    return success(
        {"id": str(previous.id), "status": previous.status, "reason": payload.reason},
        request_id_from_request(request),
    )


@router.get("/admin/knowledge/evaluations")
async def evaluations(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.evaluations.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    datasets = list((await session.scalars(select(KnowledgeEvaluationDataset))).all())
    items = []
    for dataset in datasets:
        count = await session.scalar(
            select(func.count(KnowledgeEvaluationCase.id)).where(
                KnowledgeEvaluationCase.dataset_id == dataset.id
            )
        )
        items.append(
            {
                "id": str(dataset.id),
                "dataset_code": dataset.dataset_code,
                "name": dataset.name,
                "case_count": count or 0,
            }
        )
    return success({"items": items}, request_id_from_request(request))


@router.get("/admin/knowledge/evaluation-runs")
async def evaluation_runs(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.evaluations.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT er.id,er.index_version_id,er.status,er.total_cases,er.passed_cases,"
                "er.authorization_violations,er.acl_leakage_count,er.metrics,er.created_at "
                "FROM knowledge_evaluation_runs er ORDER BY er.created_at DESC LIMIT 50"
            )
        )
    ).mappings()
    return success(
        {
            "items": [
                {
                    **dict(row),
                    "id": str(row["id"]),
                    "index_version_id": str(row["index_version_id"]),
                }
                for row in rows
            ]
        },
        request_id_from_request(request),
    )


@router.get("/admin/knowledge/audit")
async def knowledge_audit(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("knowledge.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id,event_type,actor_id,subject_type,subject_id,reason,created_at "
                "FROM knowledge_audit_events ORDER BY created_at DESC LIMIT 100"
            )
        )
    ).mappings()
    return success(
        {
            "items": [
                {
                    **dict(row),
                    "id": str(row["id"]),
                    "actor_id": str(row["actor_id"]) if row["actor_id"] else None,
                    "subject_id": str(row["subject_id"]),
                }
                for row in rows
            ]
        },
        request_id_from_request(request),
    )
