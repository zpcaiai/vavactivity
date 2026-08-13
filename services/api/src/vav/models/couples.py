"""Couple binding and SCOPE assessment ORM models (B16).

These models document the schema for metadata and tooling; the service layer
queries through raw SQL. Anything security-relevant (the one-active-binding
primary key, the free-benefit uniqueness on ``pair_key``) is expressed here
*and* as real DDL in migration ``20260812_0100``.
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
    Numeric,
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


class CoupleInvitation(Base):
    """One side's intent. An invitation binds nobody by itself (COUPLE-001)."""

    __tablename__ = "couple_invitations"

    id: Mapped[UUID] = uuid_pk()
    #: Sorted "low:high" user-id pair. Stored so the accept path never has to
    #: recompute which two people this row is about.
    pair_key: Mapped[str] = mapped_column(String(96), nullable=False)
    inviter_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    invitee_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    relationship_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'dating'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    #: Free-text member input, encrypted through vav.modules.privacy.crypto.
    note_encrypted: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decline_reason_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CoupleRelationship(Base):
    """The binding itself. Rows are kept forever, including after unbinding."""

    __tablename__ = "couple_relationships"

    id: Mapped[UUID] = uuid_pk()
    pair_key: Mapped[str] = mapped_column(String(96), nullable=False)
    user_low_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    user_high_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    relationship_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    invitation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("couple_invitations.id")
    )
    bound_at: Mapped[datetime] = created_at()
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unbound_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    unbind_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CoupleActiveMember(Base):
    """One row per member currently in a binding.

    The primary key on ``user_id`` *is* the "one active binding per member"
    rule. Deleting the row on unbind is what frees the member to bind again.
    """

    __tablename__ = "couple_active_members"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    relationship_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("couple_relationships.id"), nullable=False
    )
    pair_key: Mapped[str] = mapped_column(String(96), nullable=False)
    bound_at: Mapped[datetime] = created_at()


class CoupleBindingEvent(Base):
    """Append-only audit of every transition (COUPLE-001)."""

    __tablename__ = "couple_binding_events"

    id: Mapped[UUID] = uuid_pk()
    pair_key: Mapped[str] = mapped_column(String(96), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    relationship_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    invitation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(24))
    to_state: Mapped[str | None] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class CoupleScopeFreeBenefit(Base):
    """The once-per-pair free SCOPE ledger.

    Keyed on ``pair_key``, never on a relationship id: unbinding and rebinding
    the same two people must not regenerate a consumed benefit (SCOPE-001).
    """

    __tablename__ = "couple_scope_free_benefits"

    pair_key: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_low_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    user_high_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    granted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    consumed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_relationship_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ScopeAssessmentVersion(Base):
    """A versioned assessment definition. Immutable once published."""

    __tablename__ = "scope_assessment_versions"
    __table_args__ = (UniqueConstraint("version_code", "semantic_version"),)

    id: Mapped[UUID] = uuid_pk()
    version_code: Mapped[str] = mapped_column(String(128), nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Pinned onto every report so a stored score can be re-derived.
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    published_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ScopeAssessmentQuestion(Base):
    """Administrator-authored question. Ships empty (DEC-001)."""

    __tablename__ = "scope_assessment_questions"
    __table_args__ = (UniqueConstraint("version_id", "question_code"),)

    id: Mapped[UUID] = uuid_pk()
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scope_assessment_versions.id"), nullable=False
    )
    question_code: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    scale_min: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    scale_max: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    reverse_scored: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = created_at()


class ScopeAssessment(Base):
    """One assessment run for one relationship on one version."""

    __tablename__ = "scope_assessments"
    __table_args__ = (UniqueConstraint("relationship_id", "version_id"),)

    id: Mapped[UUID] = uuid_pk()
    relationship_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("couple_relationships.id"), nullable=False
    )
    pair_key: Mapped[str] = mapped_column(String(96), nullable=False)
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scope_assessment_versions.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'collecting'")
    )
    entitlement_source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'free'")
    )
    #: Idempotency key of the free grant that paid for this run, when free.
    free_benefit_key: Mapped[str | None] = mapped_column(String(160))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ScopeParticipantSubmission(Base):
    """One partner's sealed answers.

    ``answers_encrypted`` is opaque at rest and is only ever decrypted for its
    author or inside the scoring path, which emits numbers (SCOPE-001).
    """

    __tablename__ = "scope_participant_submissions"
    __table_args__ = (UniqueConstraint("assessment_id", "user_id"),)

    id: Mapped[UUID] = uuid_pk()
    assessment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scope_assessments.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'not_started'")
    )
    answers_encrypted: Mapped[str | None] = mapped_column(Text)
    answer_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ScopeDimensionScore(Base):
    """Deterministic per-dimension score. Queryable; not encrypted."""

    __tablename__ = "scope_dimension_scores"
    __table_args__ = (UniqueConstraint("assessment_id", "user_id", "dimension"),)

    id: Mapped[UUID] = uuid_pk()
    assessment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scope_assessments.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_total: Mapped[int] = mapped_column(Integer, nullable=False)
    min_total: Mapped[int] = mapped_column(Integer, nullable=False)
    max_total: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_score: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at()


class ScopeReport(Base):
    """The pair's report.

    ``scores`` holds the deterministic block; the AI narrative lives in the
    ``advice_*`` columns. The split is structural so nobody can mistake
    generated prose for a computed score (SCOPE-001).
    """

    __tablename__ = "scope_reports"
    __table_args__ = (UniqueConstraint("assessment_id"), UniqueConstraint("idempotency_key"))

    id: Mapped[UUID] = uuid_pk()
    assessment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scope_assessments.id"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scope_assessment_versions.id"), nullable=False
    )
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scores_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    advice_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'absent'")
    )
    advice_encrypted: Mapped[str | None] = mapped_column(Text)
    advice_model: Mapped[str | None] = mapped_column(String(64))
    advice_prompt_version: Mapped[str | None] = mapped_column(String(64))
    advice_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    advice_disclaimer_code: Mapped[str | None] = mapped_column(String(128))
    generated_at: Mapped[datetime] = created_at()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
