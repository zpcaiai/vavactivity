from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.base import Base


def uuid_pk() -> Mapped[UUID]:
    return mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class KnowledgeSpace(Base):
    __tablename__ = "knowledge_spaces"
    id: Mapped[UUID] = uuid_pk()
    space_code: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'draft'"))
    default_locale: Mapped[str] = mapped_column(String(16))
    supported_locales: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text('\'["zh-CN","zh-TW","en"]\'::jsonb')
    )
    default_sensitivity: Mapped[str] = mapped_column(String(32), server_default=text("'internal'"))
    retrieval_policy: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    allowed_roles: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    id: Mapped[UUID] = uuid_pk()
    space_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("knowledge_spaces.id"))
    source_code: Mapped[str] = mapped_column(String(128), unique=True)
    source_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    connector_config_encrypted: Mapped[str | None] = mapped_column(Text)
    sensitivity: Mapped[str] = mapped_column(String(32), server_default=text("'internal'"))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'active'"))
    source_reference_type: Mapped[str | None] = mapped_column(String(64))
    source_reference_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    sync_mode: Mapped[str] = mapped_column(String(32), server_default=text("'manual'"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_version: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeAuthorization(Base):
    __tablename__ = "knowledge_authorizations"
    id: Mapped[UUID] = uuid_pk()
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_sources.id")
    )
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_documents.id")
    )
    status: Mapped[str] = mapped_column(String(32))
    allow_rag: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    allow_public_quote: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    allow_external_training: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    allowed_regions: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    prohibited_regions: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    rights_holder_name: Mapped[str] = mapped_column(String(300), server_default=text("'VAV'"))
    authorization_basis: Mapped[str] = mapped_column(
        String(64), server_default=text("'owned_by_vav'")
    )
    allowed_uses: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[\"rag_retrieval\"]'::jsonb")
    )
    prohibited_uses: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[\"external_model_training\"]'::jsonb")
    )
    citation_permission: Mapped[str] = mapped_column(String(64), server_default=text("'none'"))
    evidence_encrypted: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[UUID] = uuid_pk()
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_sources.id")
    )
    space_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("knowledge_spaces.id"))
    document_code: Mapped[str] = mapped_column(String(128), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    locale: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'draft'"))
    document_type: Mapped[str] = mapped_column(String(64), server_default=text("'manual_entry'"))
    sensitivity: Mapped[str] = mapped_column(String(32), server_default=text("'internal'"))
    current_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    published_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeDocumentVersion(Base):
    __tablename__ = "knowledge_document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number"),)
    id: Mapped[UUID] = uuid_pk()
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_documents.id")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), server_default=text("'uploaded'"))
    mime_type: Mapped[str] = mapped_column(String(128))
    source_filename: Mapped[str | None] = mapped_column(String(500))
    source_byte_size: Mapped[int | None] = mapped_column()
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    original_storage_key_encrypted: Mapped[str | None] = mapped_column(Text)
    raw_text_encrypted: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    parsed_blocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    parse_quality_bps: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    source_locator: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    source_reference_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    processing_configuration: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeEmbeddingProfile(Base):
    __tablename__ = "knowledge_embedding_profiles"
    id: Mapped[UUID] = uuid_pk()
    profile_code: Mapped[str] = mapped_column(String(128), unique=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    dimensions: Mapped[int] = mapped_column(Integer)
    distance_metric: Mapped[str] = mapped_column(String(32), server_default=text("'cosine'"))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeIndexVersion(Base):
    __tablename__ = "knowledge_index_versions"
    __table_args__ = (UniqueConstraint("space_id", "version_number"),)
    id: Mapped[UUID] = uuid_pk()
    space_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("knowledge_spaces.id"))
    version_number: Mapped[int] = mapped_column(Integer)
    embedding_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_embedding_profiles.id")
    )
    chunk_strategy: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'building'"))
    previous_index_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_index_versions.id")
    )
    evaluation_status: Mapped[str] = mapped_column(String(32), server_default=text("'not_run'"))
    retrieval_configuration: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    document_version_manifest: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    chunk_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    embedding_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    validation_report: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("index_version_id", "document_version_id", "chunk_number"),)
    id: Mapped[UUID] = uuid_pk()
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_document_versions.id")
    )
    index_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_index_versions.id")
    )
    parent_chunk_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_chunks.id")
    )
    previous_chunk_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_chunks.id")
    )
    next_chunk_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_chunks.id")
    )
    chunk_number: Mapped[int] = mapped_column(Integer)
    chunk_type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    token_count: Mapped[int] = mapped_column(Integer)
    title_path: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    block_ids: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    source_locator: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    allowed_roles: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    sensitivity: Mapped[str] = mapped_column(String(32), server_default=text("'internal'"))
    injection_suspected: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'published'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeEvaluationDataset(Base):
    __tablename__ = "knowledge_evaluation_datasets"
    id: Mapped[UUID] = uuid_pk()
    dataset_code: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeEvaluationCase(Base):
    __tablename__ = "knowledge_evaluation_cases"
    __table_args__ = (UniqueConstraint("dataset_id", "case_code"),)
    id: Mapped[UUID] = uuid_pk()
    dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_evaluation_datasets.id")
    )
    case_code: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(16))
    region: Mapped[str | None] = mapped_column(String(32))
    query: Mapped[str] = mapped_column(Text)
    expected_document_codes: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    forbidden_document_codes: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    expected_no_answer: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    principal_roles: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    required_concepts: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    safety_boundary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class KnowledgeUpload(Base):
    __tablename__ = "knowledge_uploads"
    id: Mapped[UUID] = uuid_pk()
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_sources.id")
    )
    document_code: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(500))
    locale: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(500))
    declared_mime_type: Mapped[str] = mapped_column(String(128))
    expected_byte_size: Mapped[int] = mapped_column()
    expected_sha256: Mapped[str] = mapped_column(String(64))
    bucket_name: Mapped[str] = mapped_column(String(128))
    object_key_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), server_default=text("'pending_upload'"))
    virus_scan_status: Mapped[str] = mapped_column(String(32), server_default=text("'not_run'"))
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeParsedBlock(Base):
    __tablename__ = "knowledge_parsed_blocks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "block_index"),
        UniqueConstraint("document_version_id", "block_id"),
    )
    id: Mapped[UUID] = uuid_pk()
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_document_versions.id")
    )
    block_index: Mapped[int] = mapped_column(Integer)
    block_id: Mapped[str] = mapped_column(String(128))
    block_type: Mapped[str] = mapped_column(String(32))
    raw_text_encrypted: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    heading_level: Mapped[int | None] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    source_locator: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    parsing_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    parent_block_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeParsingReport(Base):
    __tablename__ = "knowledge_parsing_reports"
    id: Mapped[UUID] = uuid_pk()
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_document_versions.id"), unique=True
    )
    parser_name: Mapped[str] = mapped_column(String(128))
    parser_version: Mapped[str] = mapped_column(String(64))
    text_character_count: Mapped[int] = mapped_column(Integer)
    block_count: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    quality_score_basis_points: Mapped[int] = mapped_column(Integer)
    warnings: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    errors: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    requires_manual_review: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
