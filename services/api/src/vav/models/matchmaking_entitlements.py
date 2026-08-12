"""Matchmaking eligibility and entitlement ORM models (B12)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.activities import created_at, updated_at, uuid_pk
from vav.models.base import Base


class MemberRelationshipStatus(Base):
    """Authoritative relationship status. One row per member, always present."""

    __tablename__ = "member_relationship_statuses"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'undisclosed'")
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'self_declared'")
    )
    couple_relationship_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    declared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[datetime] = created_at()
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class MemberRelationshipStatusHistory(Base):
    __tablename__ = "member_relationship_status_history"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = created_at()


class MatchmakingEntitlement(Base):
    """Aggregate balance. Every change is also an entry row."""

    __tablename__ = "matchmaking_entitlements"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    granted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    consumed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'dec-004-pending'")
    )
    delivery_reset_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    first_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class MatchmakingEntitlementEntry(Base):
    __tablename__ = "matchmaking_entitlement_entries"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    granted_after: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_after: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'system'")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class MatchmakingWaitPoolEntry(Base):
    __tablename__ = "matchmaking_wait_pool_entries"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'waiting'")
    )
    entered_at: Mapped[datetime] = created_at()
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notify_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_opportunity_key: Mapped[str | None] = mapped_column(String(128))
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_reason: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = updated_at()


class MatchmakingDeliveryHistory(Base):
    __tablename__ = "matchmaking_delivery_history"
    __table_args__ = (UniqueConstraint("user_id", "candidate_user_id", "reset_generation"),)

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    candidate_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    first_delivered_at: Mapped[datetime] = created_at()
    last_delivered_at: Mapped[datetime] = created_at()
    delivery_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    first_batch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reset_generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class MatchmakingDeliveryReset(Base):
    """Audit row for each de-duplication reset. Nothing is deleted on reset."""

    __tablename__ = "matchmaking_delivery_resets"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    from_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    to_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


class MatchmakingDisclaimer(Base):
    """Approved disclaimer copy. Ships empty; editors supply the wording."""

    __tablename__ = "matchmaking_disclaimers"
    __table_args__ = (UniqueConstraint("disclaimer_code", "semantic_version", "locale"),)

    id: Mapped[UUID] = uuid_pk()
    disclaimer_code: Mapped[str] = mapped_column(String(128), nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(32), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
