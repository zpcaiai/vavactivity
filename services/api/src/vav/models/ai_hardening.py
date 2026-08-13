"""AI hardening ORM models (B19 part 1 / AI-001).

These models document the schema for metadata and tooling; the service layer
queries through raw SQL. Anything security-relevant is expressed here *and* as
real DDL in migration ``20260812_0103``:

* ``ai_usage_entries.idempotency_key`` is unique, so a retried request cannot be
  charged twice against a budget.
* ``ai_crisis_resources`` cannot be active without a recorded verifier.
* ``ai_launch_gates.is_met`` cannot be true without evidence.

``ai_conversations``, ``ai_messages``, ``ai_safety_policies``,
``ai_model_profiles`` and ``ai_model_routes`` already exist elsewhere and are
not redefined. ``conversation_id`` is stored without a foreign key so this
module deploys and rolls back independently of the assistant module.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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


class AiProviderProfile(Base):
    """One callable model behind one provider.

    Costs are integer millicents per 1000 tokens. Floating-point money in a
    spend limit is how a limit becomes advisory.
    """

    __tablename__ = "ai_provider_profiles"
    __table_args__ = (UniqueConstraint("provider_code", "model_code"),)

    id: Mapped[UUID] = uuid_pk()
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    model_code: Mapped[str] = mapped_column(String(128), nullable=False)
    input_cost_per_1k_millicents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    output_cost_per_1k_millicents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    max_context_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    #: Off by default: a newly added model is not silently put in front of members.
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    capabilities: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    #: Optional pointer into the existing ai_model_profiles catalogue. No FK:
    #: this module deploys independently of the assistant module's schema.
    model_profile_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AiProviderHealth(Base):
    """Circuit-breaker state, one row per provider."""

    __tablename__ = "ai_provider_health"

    provider_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'healthy'")
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    circuit_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = updated_at()


class AiBudgetPolicy(Base):
    """One ceiling per scope.

    An absent row means *not configured*, which the domain treats as a refusal
    rather than as unlimited - a fresh deployment cannot spend money before an
    operator has said how much.
    """

    __tablename__ = "ai_budget_policies"

    scope: Mapped[str] = mapped_column(String(24), primary_key=True)
    limit_tokens: Mapped[int | None] = mapped_column(BigInteger)
    limit_millicents: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AiUsageEntry(Base):
    """One row per request that reserved, spent or was refused budget.

    ``reserved`` rows count against the limit while a call is in flight, so two
    concurrent requests cannot both fit under the same remaining headroom.
    """

    __tablename__ = "ai_usage_entries"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    provider_code: Mapped[str | None] = mapped_column(String(64))
    model_code: Mapped[str | None] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cost_millicents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'reserved'")
    )
    refusal_code: Mapped[str | None] = mapped_column(String(64))
    #: Every response carries an AI-limitation label; the version used is
    #: recorded so a later change to the wording is traceable.
    limitation_label_code: Mapped[str] = mapped_column(String(64), nullable=False)
    limitation_label_version: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AiContentPolicyRule(Base):
    """Operator-authored screening rule. The platform ships none.

    Content-policy wording is a legal and clinical decision, not a developer's
    guess, so this table is empty after migration and stays empty until an
    operator writes to it.
    """

    __tablename__ = "ai_content_policy_rules"
    __table_args__ = (UniqueConstraint("rule_code"),)

    id: Mapped[UUID] = uuid_pk()
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    match_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    surface: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'input'"))
    locale: Mapped[str | None] = mapped_column(String(16))
    safety_policy_code: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AiPolicyDecision(Base):
    """The screening audit: rule codes and counts, never the member's text."""

    __tablename__ = "ai_policy_decisions"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    surface: Mapped[str] = mapped_column(String(8), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    matched_rule_codes: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    highest_severity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    audit: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AiCrisisResource(Base):
    """An operator-verified crisis resource for one geography.

    Ships empty. The platform invents no hotline numbers: when no verified,
    active resource exists for a member's geography, ``domain.route_crisis``
    escalates to a human instead of guessing.
    """

    __tablename__ = "ai_crisis_resources"
    __table_args__ = (UniqueConstraint("resource_code", "geography_code", "locale"),)

    id: Mapped[UUID] = uuid_pk()
    resource_code: Mapped[str] = mapped_column(String(64), nullable=False)
    geography_code: Mapped[str] = mapped_column(String(8), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    contact_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    contact_value: Mapped[str] = mapped_column(Text, nullable=False)
    #: Inactive until separately verified; editing the contact clears both.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    verified_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_note: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AiEscalationRunbook(Base):
    """The human-escalation runbook. Ships empty.

    Its absence is what makes ``launch_readiness`` report
    ``human_escalation_runbook`` unmet, which is the point: no launch claim
    without a runbook.
    """

    __tablename__ = "ai_escalation_runbooks"
    __table_args__ = (UniqueConstraint("runbook_code"),)

    id: Mapped[UUID] = uuid_pk()
    runbook_code: Mapped[str] = mapped_column(String(64), nullable=False)
    geography_code: Mapped[str | None] = mapped_column(String(8))
    owner_role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    document_reference: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledgement_target_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AiLaunchGate(Base):
    """One launch gate. Ships empty, and an absent gate reads as unmet."""

    __tablename__ = "ai_launch_gates"

    gate_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    is_met: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    #: A gate cannot be met without something to point at.
    evidence_ref: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    checked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
