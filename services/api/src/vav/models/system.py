from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func, text
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
