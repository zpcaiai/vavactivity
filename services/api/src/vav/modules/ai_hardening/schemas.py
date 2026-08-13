"""Request payloads for the AI hardening module (B19 part 1)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")


class _Base(BaseModel):
    model_config = _STRICT


# ---------------------------------------------------------------------------
# Member-facing
# ---------------------------------------------------------------------------


class AiTurnRequest(_Base):
    """One member message.

    ``max_output_tokens`` is a member-visible cap that the server clamps to the
    provider's own ceiling; it exists so a client can ask for a short answer,
    never so it can ask for a longer one than the budget allows.
    """

    prompt: Annotated[str, Field(min_length=1, max_length=8000)]
    locale: Annotated[str, Field(max_length=16)] = "zh-CN"
    #: ISO-3166 alpha-2. Used only to route crisis resources; absent means the
    #: crisis path fails closed to a human.
    geography_code: Annotated[str, Field(max_length=8)] | None = None
    max_output_tokens: Annotated[int, Field(ge=1, le=4000)] = 800
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    #: A member asking for a person is honoured unconditionally.
    request_human: bool = False


class EscalationRequestPayload(_Base):
    reason_note: Annotated[str, Field(max_length=2000)] | None = None


# ---------------------------------------------------------------------------
# Administrative
# ---------------------------------------------------------------------------


class BudgetPolicyRequest(_Base):
    scope: Literal["user_daily", "conversation", "global_monthly"]
    #: Token ceiling for the two token scopes; ignored for the cost scope.
    limit_tokens: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    #: Thousandths of a cent, so budgets are exact integers.
    limit_millicents: Annotated[int, Field(ge=0, le=100_000_000_000)] | None = None
    is_active: bool = True


class PolicyRuleRequest(_Base):
    """Operator-authored content policy. The platform ships none."""

    rule_code: Annotated[str, Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")]
    category: Annotated[str, Field(min_length=2, max_length=64)]
    match_kind: Literal["keyword", "exact"]
    pattern: Annotated[str, Field(min_length=1, max_length=500)]
    action: Literal["allow", "flag", "block", "escalate"]
    severity: Annotated[int, Field(ge=0, le=10)] = 1
    surface: Literal["input", "output"] = "input"
    locale: Annotated[str, Field(max_length=16)] | None = None
    is_active: bool = True


class CrisisResourceRequest(_Base):
    """A crisis resource for one geography.

    Every field is operator-supplied. Nothing here has a default that could be
    mistaken for a real hotline, and a resource is unusable until an operator
    records who verified it.
    """

    resource_code: Annotated[str, Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")]
    geography_code: Annotated[str, Field(min_length=2, max_length=8)]
    locale: Annotated[str, Field(min_length=2, max_length=16)]
    contact_value: Annotated[str, Field(min_length=1, max_length=500)]
    contact_kind: Literal["phone", "sms", "url", "email"]
    is_active: bool = False


class CrisisResourceVerifyRequest(_Base):
    verification_note: Annotated[str, Field(min_length=4, max_length=2000)]
    activate: bool = True


class EscalationRunbookRequest(_Base):
    runbook_code: Annotated[str, Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")]
    geography_code: Annotated[str, Field(max_length=8)] | None = None
    owner_role_code: Annotated[str, Field(min_length=2, max_length=64)]
    document_reference: Annotated[str, Field(min_length=1, max_length=500)]
    acknowledgement_target_minutes: Annotated[int, Field(ge=1, le=10_080)] = 30
    is_active: bool = True


class EscalationDecisionRequest(_Base):
    status: Literal["acknowledged", "resolved", "cancelled"]
    note: Annotated[str, Field(max_length=2000)] | None = None


class LaunchGateRequest(_Base):
    gate_code: Literal[
        "human_escalation_runbook",
        "crisis_resources_configured",
        "content_policy_configured",
        "budget_limits_configured",
        "provider_fallback_configured",
        "limitation_label_configured",
    ]
    is_met: bool
    #: A link to the runbook, ticket or sign-off. A gate with no evidence never
    #: counts as met, whatever ``is_met`` says.
    evidence_ref: Annotated[str, Field(max_length=500)] | None = None
    note: Annotated[str, Field(max_length=2000)] | None = None
    checked_at: datetime | None = None
