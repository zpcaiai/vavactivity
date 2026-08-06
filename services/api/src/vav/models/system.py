from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.base import Base, RecordMixin


class SystemMetadata(RecordMixin, Base):
    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class SystemSetting(RecordMixin, Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutboxEvent(RecordMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_pending", "published_at", "created_at"),)

    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))


class IdempotencyKey(RecordMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("uq_idempotency_scope_key", "scope", "key", unique=True),)

    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(nullable=True)
    response_body: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(RecordMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_actor_created", "actor_id", "created_at"),
        Index("ix_audit_events_subject_created", "subject_type", "subject_id", "created_at"),
    )

    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(120), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SystemFeatureFlag(Base):
    __tablename__ = "system_feature_flags"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    flag_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    targeting_policy: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    default_value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemReleaseRecord(Base):
    __tablename__ = "system_release_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    release_version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    git_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    image_digests: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    database_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_checksums: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    configuration_fingerprint: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    evidence_manifest: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemMaintenanceState(Base):
    __tablename__ = "system_maintenance_states"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    environment: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    write_scope: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    public_message: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    changed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemBackfillJob(Base):
    __tablename__ = "system_backfill_jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    job_code: Mapped[str] = mapped_column(String(128), nullable=False)
    release_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    cursor_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    processed_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    failed_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate_limit_per_second: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemBackupRecord(Base):
    __tablename__ = "system_backup_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    backup_type: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backup_reference_encrypted: Mapped[str | None] = mapped_column(Text)
    checksum_manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_release_version: Mapped[str | None] = mapped_column(String(64))
    source_database_revision: Mapped[str | None] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemRestoreDrill(Base):
    __tablename__ = "system_restore_drills"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    drill_code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    backup_record_id: Mapped[UUID | None] = mapped_column(ForeignKey("system_backup_records.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    target_release_version: Mapped[str | None] = mapped_column(String(64))
    target_database_revision: Mapped[str | None] = mapped_column(String(64))
    verification_manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    failure_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemCapacityBaseline(Base):
    __tablename__ = "system_capacity_baselines"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    release_version: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    scenario_code: Mapped[str] = mapped_column(String(128), nullable=False)
    infrastructure_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    load_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    result_metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    tested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
