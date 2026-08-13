"""Paid assessment framework ORM models (B17).

Schema documentation only; the service layer uses raw SQL. The licensing rule
(``status='published'`` requires a verified licence reference) is a real CHECK
constraint in migration ``20260812_0101`` as well as a domain rule.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.activities import created_at, updated_at, uuid_pk
from vav.models.base import Base


class AssessmentProduct(Base):
    """A catalogue entry. ``title_code`` is an identifier, not display copy."""

    __tablename__ = "assessment_products"
    __table_args__ = (UniqueConstraint("product_code"),)

    id: Mapped[UUID] = uuid_pk()
    product_code: Mapped[str] = mapped_column(String(128), nullable=False)
    title_code: Mapped[str] = mapped_column(String(128), nullable=False)
    category_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    refund_window_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("72")
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AssessmentVersion(Base):
    """A purchasable version, with its content provenance.

    ``content_source`` + ``license_reference`` + ``license_verified_at`` are the
    fields that make ASSESS-001's publication gate enforceable. No third-party
    instrument's items ship in code; they are authored against a version whose
    licence is recorded here.
    """

    __tablename__ = "assessment_versions"
    __table_args__ = (UniqueConstraint("product_id", "semantic_version"),)

    id: Mapped[UUID] = uuid_pk()
    product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_products.id"), nullable=False
    )
    semantic_version: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    content_source: Mapped[str] = mapped_column(String(32), nullable=False)
    license_reference: Mapped[str | None] = mapped_column(String(255))
    license_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    license_verified_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id")
    )
    licensor_name: Mapped[str | None] = mapped_column(String(255))
    license_note: Mapped[str | None] = mapped_column(Text)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    price_minor_units: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'CNY'"))
    published_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AssessmentVersionQuestion(Base):
    """Administrator-supplied item. Ships empty."""

    __tablename__ = "assessment_version_questions"
    __table_args__ = (UniqueConstraint("version_id", "question_code"),)

    id: Mapped[UUID] = uuid_pk()
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_versions.id"), nullable=False
    )
    question_code: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension_code: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    scale_min: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    scale_max: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    reverse_scored: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = created_at()


class AssessmentPurchase(Base):
    """A payment for one exact version.

    ``version_id`` is not nullable and is never rewritten: it is the anchor that
    prevents version drift after purchase.
    """

    __tablename__ = "assessment_purchases"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_products.id"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_versions.id"), nullable=False
    )
    order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    price_minor_units: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'CNY'"))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refund_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AssessmentEntitlement(Base):
    """What the purchase actually grants: attempts on one pinned version."""

    __tablename__ = "assessment_entitlements"
    __table_args__ = (UniqueConstraint("purchase_id"),)

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    purchase_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_purchases.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_products.id"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_versions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    attempts_granted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    attempts_consumed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AssessmentAttempt(Base):
    """One sitting. Answers are encrypted; a voided attempt is kept, not deleted."""

    __tablename__ = "assessment_attempts"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[UUID] = uuid_pk()
    entitlement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_entitlements.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_versions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'in_progress'")
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    answers_encrypted: Mapped[str | None] = mapped_column(Text)
    answer_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    started_at: Mapped[datetime] = created_at()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AssessmentReport(Base):
    """Deterministic ``scores`` plus a clearly separated AI ``advice_*`` block."""

    __tablename__ = "assessment_reports"
    __table_args__ = (UniqueConstraint("attempt_id"), UniqueConstraint("idempotency_key"))

    id: Mapped[UUID] = uuid_pk()
    attempt_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_attempts.id"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_versions.id"), nullable=False
    )
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scores_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'generated'")
    )
    advice_encrypted: Mapped[str | None] = mapped_column(Text)
    advice_model: Mapped[str | None] = mapped_column(String(64))
    advice_prompt_version: Mapped[str | None] = mapped_column(String(64))
    advice_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    advice_disclaimer_code: Mapped[str | None] = mapped_column(String(128))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(64))
    generated_at: Mapped[datetime] = created_at()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AssessmentRefundEvent(Base):
    """Append-only audit of every refund decision, including refusals."""

    __tablename__ = "assessment_refund_events"

    id: Mapped[UUID] = uuid_pk()
    purchase_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment_purchases.id"), nullable=False
    )
    entitlement_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_action: Mapped[str] = mapped_column(String(24), nullable=False)
    report_action: Mapped[str] = mapped_column(String(24), nullable=False)
    refund_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = created_at()
