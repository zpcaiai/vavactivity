"""Pure couple-binding and SCOPE assessment rules (B16).

Requirement coverage:

* COUPLE-001 two-sided binding only: invite -> accept/reject -> active, plus an
  audited unbind. There is no code path in this module that produces an active
  relationship from a single member's action.
* SCOPE-001 one free SCOPE assessment **per relationship pair**, independent
  sealed answering by both partners, a completion barrier before any report is
  produced, versioned reproducible five-dimension scoring, and AI advice that is
  structurally separated from the deterministic scores.
* DEC-001 safe default: the platform ships no questionnaire content. Every rule
  below works against an administrator-authored question bank; an empty bank is
  a valid (and the shipped) state, it simply cannot be published.

This module has no database, settings, network or clock access. Every function
that needs the current time takes ``now`` as an argument, and every function
that needs stored state takes it as a plain value, so the whole rule set is
unit-testable without PostgreSQL.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID

# ---------------------------------------------------------------------------
# Shared errors
# ---------------------------------------------------------------------------


class CoupleRuleError(Exception):
    """Raised when a caller violates a couple-binding or SCOPE rule.

    ``code`` is the stable machine identifier surfaced to clients; ``message``
    is an operator-facing English sentence. Member-facing copy is localized in
    the frontend from ``code``, never from ``message`` (no invented Chinese
    copy lives in the backend).
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


# ---------------------------------------------------------------------------
# COUPLE-001 - the pair key
# ---------------------------------------------------------------------------


def pair_key(user_a: UUID, user_b: UUID) -> str:
    """Stable identity of *the two people*, independent of any relationship row.

    This is the single most important primitive in the module. The free SCOPE
    benefit (SCOPE-001) is keyed on this string, not on ``couple_relationships.id``.
    Unbinding deletes nothing and rebinding creates a **new** relationship row,
    so if the benefit were keyed on the relationship id the same pair could
    unbind and rebind to mint themselves an unlimited number of free
    assessments. Sorting the two ids means ``pair_key(a, b) == pair_key(b, a)``,
    so it also does not matter who invited whom the second time round.
    """

    if user_a == user_b:
        raise CoupleRuleError(
            "COUPLE_SELF_PAIR_FORBIDDEN", "A member cannot form a pair with themselves."
        )
    low, high = sorted((user_a, user_b), key=str)
    return f"{low}:{high}"


def pair_members(key: str) -> tuple[UUID, UUID]:
    """Inverse of :func:`pair_key`, used when replaying audit rows."""

    parts = key.split(":")
    if len(parts) != 2:
        raise CoupleRuleError("COUPLE_PAIR_KEY_MALFORMED", "The pair key is not well formed.")
    try:
        return UUID(parts[0]), UUID(parts[1])
    except ValueError as exc:
        raise CoupleRuleError("COUPLE_PAIR_KEY_MALFORMED", str(exc)) from exc


def free_scope_benefit_key(key: str) -> str:
    """Idempotency key for the once-per-pair free SCOPE grant."""

    return f"scope-free:{key}"


# ---------------------------------------------------------------------------
# COUPLE-001 - invitation lifecycle
# ---------------------------------------------------------------------------


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class RelationshipState(StrEnum):
    ACTIVE = "active"
    UNBOUND = "unbound"


class RelationshipKind(StrEnum):
    """What the couple declares the binding to be.

    Deliberately a closed set that maps one-to-one onto the statuses already
    accepted by ``member_relationship_statuses`` (migration 20260812_0096), so a
    binding can never write a status that table would reject.
    """

    DATING = "dating"
    ENGAGED = "engaged"
    MARRIED = "married"


#: Status written to ``member_relationship_statuses`` when a binding confirms.
#: Every one of these is outside ``MATCHMAKING_ELIGIBLE_STATUSES``, which is how
#: a confirmed binding closes matchmaking for both partners (MATCH-001).
_KIND_TO_STATUS: dict[RelationshipKind, str] = {
    RelationshipKind.DATING: "dating",
    RelationshipKind.ENGAGED: "engaged",
    RelationshipKind.MARRIED: "married",
}

#: Status written on unbind. Not ``single``: the platform must never assert on a
#: member's behalf that they are available again. ``undisclosed`` fails closed,
#: and the member re-opens matchmaking by declaring it themselves.
UNBOUND_STATUS = "undisclosed"

DEFAULT_INVITATION_TTL_HOURS = 72

_INVITATION_TRANSITIONS: dict[InvitationStatus, frozenset[InvitationStatus]] = {
    InvitationStatus.PENDING: frozenset(
        {
            InvitationStatus.ACCEPTED,
            InvitationStatus.REJECTED,
            InvitationStatus.CANCELLED,
            InvitationStatus.EXPIRED,
        }
    ),
    # Terminal. A new intention requires a new invitation, which keeps the
    # audit trail one row per decision (COUPLE-001).
    InvitationStatus.ACCEPTED: frozenset(),
    InvitationStatus.REJECTED: frozenset(),
    InvitationStatus.CANCELLED: frozenset(),
    InvitationStatus.EXPIRED: frozenset(),
}


def validate_invitation_transition(current: str, target: str) -> None:
    try:
        current_status = InvitationStatus(current)
        target_status = InvitationStatus(target)
    except ValueError as exc:
        raise CoupleRuleError("COUPLE_INVITATION_STATUS_UNKNOWN", str(exc)) from exc
    if target_status not in _INVITATION_TRANSITIONS[current_status]:
        raise CoupleRuleError(
            "COUPLE_INVITATION_TRANSITION_INVALID",
            f"Cannot move a couple invitation from {current_status} to {target_status}.",
            details={"current": current_status.value, "target": target_status.value},
        )


def invitation_expires_at(*, created_at: datetime, ttl_hours: int) -> datetime:
    if created_at.tzinfo is None:
        raise CoupleRuleError("COUPLE_NAIVE_DATETIME", "created_at must be timezone-aware.")
    if ttl_hours <= 0:
        raise CoupleRuleError(
            "COUPLE_INVITATION_TTL_INVALID", "The invitation lifetime must be positive."
        )
    return created_at + timedelta(hours=ttl_hours)


def is_invitation_expired(*, expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None or now.tzinfo is None:
        raise CoupleRuleError("COUPLE_NAIVE_DATETIME", "Invitation timestamps must be tz-aware.")
    return now >= expires_at


def validate_invitation_creation(
    *,
    inviter_id: UUID,
    invitee_id: UUID,
    relationship_kind: str,
    inviter_active_relationship_id: UUID | None,
    invitee_active_relationship_id: UUID | None,
    has_pending_invitation_for_pair: bool,
    blocked: bool = False,
) -> tuple[str, RelationshipKind]:
    """Guard the *first* half of a two-sided binding.

    An invitation on its own binds nobody, but it still has to be refused early
    when it cannot possibly succeed: a member already in an active binding, an
    invitee already in one, a duplicate pending invitation for the same pair, or
    a blocked relationship. Returning the pair key here means the caller stores
    it on the invitation row, so the accept path never has to recompute trust.
    """

    key = pair_key(inviter_id, invitee_id)
    try:
        kind = RelationshipKind(relationship_kind)
    except ValueError as exc:
        raise CoupleRuleError("COUPLE_RELATIONSHIP_KIND_UNKNOWN", str(exc)) from exc
    if blocked:
        raise CoupleRuleError(
            "COUPLE_INVITATION_BLOCKED",
            "An interaction restriction exists between these two members.",
        )
    if inviter_active_relationship_id is not None:
        raise CoupleRuleError(
            "COUPLE_RELATIONSHIP_CONFLICT",
            "The inviter is already in an active binding and must unbind first.",
            details={"relationship_id": str(inviter_active_relationship_id), "role": "inviter"},
        )
    if invitee_active_relationship_id is not None:
        raise CoupleRuleError(
            "COUPLE_RELATIONSHIP_CONFLICT",
            "The invited member is already in an active binding.",
            details={"relationship_id": str(invitee_active_relationship_id), "role": "invitee"},
        )
    if has_pending_invitation_for_pair:
        raise CoupleRuleError(
            "COUPLE_INVITATION_DUPLICATE",
            "A pending invitation already exists between these two members.",
            details={"pair_key": key},
        )
    return key, kind


def ensure_invitation_actor(*, target: str, actor_id: UUID, inviter_id: UUID, invitee_id: UUID) -> None:
    """Who may move an invitation, and in which direction.

    This is the rule that makes the binding two-sided in the strict sense: only
    the *invitee* can accept. The inviter accepting their own invitation would
    be a unilateral binding, so it is rejected with its own error code rather
    than a generic permission failure — a reviewer should be able to grep for
    ``COUPLE_UNILATERAL_BINDING_FORBIDDEN`` and find nothing that bypasses it.
    """

    try:
        target_status = InvitationStatus(target)
    except ValueError as exc:
        raise CoupleRuleError("COUPLE_INVITATION_STATUS_UNKNOWN", str(exc)) from exc
    if target_status in (InvitationStatus.ACCEPTED, InvitationStatus.REJECTED):
        if actor_id == inviter_id:
            raise CoupleRuleError(
                "COUPLE_UNILATERAL_BINDING_FORBIDDEN",
                "The inviter cannot answer their own invitation; only the invited "
                "member can accept or reject it.",
            )
        if actor_id != invitee_id:
            raise CoupleRuleError(
                "COUPLE_INVITATION_ACTOR_INVALID",
                "Only the invited member can answer this invitation.",
            )
        return
    if target_status is InvitationStatus.CANCELLED and actor_id != inviter_id:
        raise CoupleRuleError(
            "COUPLE_INVITATION_ACTOR_INVALID", "Only the inviter can cancel an invitation."
        )


@dataclass(frozen=True)
class RelationshipStatusPlan:
    """A single write the service must apply to ``member_relationship_statuses``.

    The domain never touches the database, so a binding decision is expressed as
    the set of status writes it implies. The service replays them verbatim,
    which keeps "what a binding does to matchmaking access" reviewable in one
    place (MATCH-001 + COUPLE-001).
    """

    user_id: UUID
    status: str
    source: str
    actor_kind: str
    couple_relationship_id: UUID | None
    reason_code: str


@dataclass(frozen=True)
class BindingPlan:
    pair_key: str
    relationship_kind: RelationshipKind
    members: tuple[UUID, UUID]
    status_plans: tuple[RelationshipStatusPlan, ...]
    event_type: str = "bound"


def decide_binding(
    *,
    inviter_id: UUID,
    invitee_id: UUID,
    acceptor_id: UUID,
    invitation_status: str,
    relationship_kind: str,
    relationship_id: UUID,
    acceptor_active_relationship_id: UUID | None,
    inviter_active_relationship_id: UUID | None,
    expires_at: datetime,
    now: datetime,
) -> BindingPlan:
    """The only function in the module that can produce an active binding.

    Order of checks is deliberate:

    1. transition legality (a cancelled or already-accepted invitation is inert)
    2. actor legality — this is where a unilateral self-accept dies
    3. expiry — an expired invitation is never revived, it is re-sent
    4. relationship conflict for **both** sides, re-checked at accept time.
       The invitee may have bound to somebody else while this invitation sat in
       their inbox, and that second acceptance must fail rather than leave the
       member in two active bindings (COUPLE-001).

    Only then is the pair of status writes emitted, both with
    ``source='couple_binding'``, which is what closes matchmaking for the two of
    them and locks the status against unilateral self-declaration.
    """

    validate_invitation_transition(invitation_status, InvitationStatus.ACCEPTED)
    ensure_invitation_actor(
        target=InvitationStatus.ACCEPTED,
        actor_id=acceptor_id,
        inviter_id=inviter_id,
        invitee_id=invitee_id,
    )
    if is_invitation_expired(expires_at=expires_at, now=now):
        raise CoupleRuleError(
            "COUPLE_INVITATION_EXPIRED",
            "This invitation has expired; a new one must be sent.",
            details={"expires_at": expires_at.isoformat()},
        )
    if acceptor_active_relationship_id is not None:
        raise CoupleRuleError(
            "COUPLE_RELATIONSHIP_CONFLICT",
            "You are already in an active binding and cannot accept a second invitation.",
            details={"relationship_id": str(acceptor_active_relationship_id), "role": "invitee"},
        )
    if inviter_active_relationship_id is not None:
        raise CoupleRuleError(
            "COUPLE_RELATIONSHIP_CONFLICT",
            "The inviter has bound with somebody else since sending this invitation.",
            details={"relationship_id": str(inviter_active_relationship_id), "role": "inviter"},
        )
    try:
        kind = RelationshipKind(relationship_kind)
    except ValueError as exc:
        raise CoupleRuleError("COUPLE_RELATIONSHIP_KIND_UNKNOWN", str(exc)) from exc
    key = pair_key(inviter_id, invitee_id)
    status = _KIND_TO_STATUS[kind]
    plans = tuple(
        RelationshipStatusPlan(
            user_id=member,
            status=status,
            source="couple_binding",
            actor_kind="member",
            couple_relationship_id=relationship_id,
            reason_code="couple_binding_confirmed",
        )
        for member in sorted((inviter_id, invitee_id), key=str)
    )
    return BindingPlan(
        pair_key=key,
        relationship_kind=kind,
        members=(plans[0].user_id, plans[1].user_id),
        status_plans=plans,
    )


@dataclass(frozen=True)
class UnbindPlan:
    pair_key: str
    members: tuple[UUID, UUID]
    status_plans: tuple[RelationshipStatusPlan, ...]
    reason: str
    event_type: str


def plan_unbind(
    *,
    relationship_state: str,
    members: Sequence[UUID],
    actor_id: UUID | None,
    actor_kind: str,
    reason: str | None,
    key: str,
) -> UnbindPlan:
    """Release a binding, for either partner or an administrator.

    Unbinding is deliberately *not* symmetric with binding: one partner may end
    it alone, because requiring two-sided consent to leave would let a partner
    trap the other. Binding needs both; leaving needs one. Both partners' status
    rows are released, and both are reset to ``undisclosed`` rather than
    ``single`` so the platform never asserts availability on their behalf.

    ``source='admin'`` is used for the release write rather than
    ``self_declared`` because the status being released is couple-binding-locked
    and ``validate_status_change`` (B12) refuses a self-declared write over that
    lock. The release is a platform action taken on the member's instruction,
    which is exactly what that source means.
    """

    if relationship_state != RelationshipState.ACTIVE:
        raise CoupleRuleError(
            "COUPLE_RELATIONSHIP_NOT_ACTIVE",
            "Only an active binding can be unbound.",
            details={"state": relationship_state},
        )
    if actor_kind not in ("member", "admin", "system"):
        raise CoupleRuleError("COUPLE_ACTOR_KIND_UNKNOWN", f"Unknown actor kind: {actor_kind}")
    ordered = tuple(sorted(members, key=str))
    if len(ordered) != 2:
        raise CoupleRuleError(
            "COUPLE_RELATIONSHIP_MEMBERS_INVALID", "A binding always has exactly two members."
        )
    if actor_kind == "member":
        if actor_id is None or actor_id not in ordered:
            raise CoupleRuleError(
                "COUPLE_UNBIND_ACTOR_INVALID", "Only a member of the binding can unbind it."
            )
    elif actor_kind == "admin":
        cleaned = (reason or "").strip()
        if len(cleaned) < 4:
            # An administrative unbind overrides two members' stated
            # relationship, so it is never allowed to be unexplained.
            raise CoupleRuleError(
                "COUPLE_UNBIND_REASON_REQUIRED",
                "An administrative unbind requires a reason of at least 4 characters.",
            )
    plans = tuple(
        RelationshipStatusPlan(
            user_id=member,
            status=UNBOUND_STATUS,
            source="admin",
            actor_kind=actor_kind,
            couple_relationship_id=None,
            reason_code="couple_binding_released",
        )
        for member in ordered
    )
    return UnbindPlan(
        pair_key=key,
        members=ordered,
        status_plans=plans,
        reason=(reason or "").strip()[:1000],
        event_type="admin_unbound" if actor_kind == "admin" else "unbound",
    )


# ---------------------------------------------------------------------------
# SCOPE-001 - the free benefit, keyed on the pair
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FreeBenefitState:
    """Ledger for the one free SCOPE assessment a pair ever receives.

    ``pair_key`` is the primary key of this state, *not* a relationship id. See
    :func:`pair_key` for why.
    """

    pair_key: str
    granted: int = 1
    consumed: int = 0

    def __post_init__(self) -> None:
        if self.granted < 0 or self.consumed < 0:
            raise CoupleRuleError(
                "SCOPE_FREE_BENEFIT_INVALID", "Free-benefit counters cannot be negative."
            )
        if self.consumed > self.granted:
            raise CoupleRuleError(
                "SCOPE_FREE_BENEFIT_INVALID",
                "More free assessments were consumed than were granted.",
            )

    @property
    def remaining(self) -> int:
        return max(0, self.granted - self.consumed)


@dataclass(frozen=True)
class FreeBenefitDecision:
    pair_key: str
    idempotency_key: str
    remaining_after: int


def decide_free_scope_grant(state: FreeBenefitState) -> FreeBenefitDecision:
    """Decide whether this pair may start a *free* SCOPE assessment.

    The rule that matters for SCOPE-001: because ``state`` is looked up by pair
    key, an unbind followed by a rebind of the same two people returns the same
    already-consumed row. The pair therefore gets one free assessment for as
    long as the platform exists, no matter how many relationship rows they
    create. A pair that wants another assessment buys one (B17).
    """

    if state.remaining <= 0:
        raise CoupleRuleError(
            "SCOPE_FREE_BENEFIT_CONSUMED",
            "This pair has already used their free SCOPE assessment.",
            details={
                "pair_key": state.pair_key,
                "granted": state.granted,
                "consumed": state.consumed,
            },
        )
    return FreeBenefitDecision(
        pair_key=state.pair_key,
        idempotency_key=free_scope_benefit_key(state.pair_key),
        remaining_after=state.remaining - 1,
    )


def consume_free_scope_benefit(state: FreeBenefitState) -> FreeBenefitState:
    decide_free_scope_grant(state)
    return FreeBenefitState(
        pair_key=state.pair_key, granted=state.granted, consumed=state.consumed + 1
    )


# ---------------------------------------------------------------------------
# SCOPE-001 - versioned question bank
# ---------------------------------------------------------------------------


class ScopeDimension(StrEnum):
    """The five SCOPE dimensions, as generic relationship-domain labels.

    These are structural bucket names for an administrator-authored bank. No
    third-party instrument's items, scoring keys or normative tables ship with
    the platform (DEC-001 / licensing discipline shared with B17).
    """

    SUPPORT = "support"
    COMMUNICATION = "communication"
    OUTLOOK = "outlook"
    PARTNERSHIP = "partnership"
    EXPECTATIONS = "expectations"


#: Fixed iteration order. Report output is emitted in this order so two runs of
#: the same version produce byte-identical payloads (reproducibility).
SCOPE_DIMENSION_ORDER: tuple[ScopeDimension, ...] = (
    ScopeDimension.SUPPORT,
    ScopeDimension.COMMUNICATION,
    ScopeDimension.OUTLOOK,
    ScopeDimension.PARTNERSHIP,
    ScopeDimension.EXPECTATIONS,
)

SCORE_QUANTUM = Decimal("0.01")
MIN_QUESTION_WEIGHT = 1
MAX_QUESTION_WEIGHT = 10
SCALE_FLOOR = 1
SCALE_CEILING = 10


class ScopeVersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class ScopeQuestionSpec:
    """One administrator-authored question of a SCOPE version.

    ``weight`` is an integer on purpose. Floating-point weights would make the
    scoring only *approximately* reproducible across machines and Python
    versions; integer weights combined with :class:`decimal.Decimal` division
    make it exactly reproducible, which is the whole point of pinning
    ``algorithm_version`` to a version row.
    """

    question_id: UUID
    question_code: str
    dimension: ScopeDimension
    weight: int = 1
    scale_min: int = 1
    scale_max: int = 5
    reverse_scored: bool = False
    position: int = 0

    def __post_init__(self) -> None:
        if not MIN_QUESTION_WEIGHT <= self.weight <= MAX_QUESTION_WEIGHT:
            raise CoupleRuleError(
                "SCOPE_QUESTION_WEIGHT_INVALID",
                f"Question weight must be between {MIN_QUESTION_WEIGHT} and {MAX_QUESTION_WEIGHT}.",
                details={"question_code": self.question_code},
            )
        if not SCALE_FLOOR <= self.scale_min < self.scale_max <= SCALE_CEILING:
            raise CoupleRuleError(
                "SCOPE_QUESTION_SCALE_INVALID",
                f"Scale must satisfy {SCALE_FLOOR} <= min < max <= {SCALE_CEILING}.",
                details={"question_code": self.question_code},
            )


@dataclass(frozen=True)
class ScopeVersionSpec:
    """A frozen, versioned assessment definition.

    A version is immutable once published. Editing a published version would
    silently change the meaning of every historical report, so the workflow is
    always "publish a new semantic version".
    """

    version_code: str
    semantic_version: str
    algorithm_version: str
    questions: tuple[ScopeQuestionSpec, ...] = ()

    def __post_init__(self) -> None:
        codes = [question.question_code for question in self.questions]
        if len(set(codes)) != len(codes):
            raise CoupleRuleError(
                "SCOPE_QUESTION_CODE_DUPLICATE", "Question codes must be unique within a version."
            )

    def questions_for(self, dimension: ScopeDimension) -> tuple[ScopeQuestionSpec, ...]:
        return tuple(
            question for question in self.questions if question.dimension is dimension
        )


def ensure_version_publishable(version: ScopeVersionSpec) -> None:
    """A version may only be published once it can actually produce five scores.

    The platform ships with an empty bank (DEC-001), so this check is what stops
    an empty or half-authored version from reaching members and producing a
    report with missing dimensions.
    """

    if not version.questions:
        raise CoupleRuleError(
            "SCOPE_VERSION_EMPTY",
            "A SCOPE version cannot be published with no questions; the question "
            "bank is administrator-authored and ships empty.",
            details={"version_code": version.version_code},
        )
    missing = [
        dimension.value
        for dimension in SCOPE_DIMENSION_ORDER
        if not version.questions_for(dimension)
    ]
    if missing:
        raise CoupleRuleError(
            "SCOPE_VERSION_DIMENSION_MISSING",
            "Every one of the five SCOPE dimensions needs at least one question.",
            details={"missing_dimensions": missing},
        )


def validate_scope_answers(
    version: ScopeVersionSpec, answers: Mapping[str, int], *, partial: bool = False
) -> dict[str, int]:
    """Validate one partner's raw answers against the frozen question set.

    ``partial=True`` is used for autosaved drafts: shape is still checked but a
    missing answer is tolerated. A real submit always runs with
    ``partial=False``, because the completion barrier downstream assumes a
    submitted partner answered everything.
    """

    by_code = {question.question_code: question for question in version.questions}
    cleaned: dict[str, int] = {}
    for code, value in answers.items():
        question = by_code.get(code)
        if question is None:
            raise CoupleRuleError(
                "SCOPE_ANSWER_QUESTION_UNKNOWN",
                "An answer refers to a question that is not part of this version.",
                details={"question_code": code},
            )
        if not isinstance(value, int) or isinstance(value, bool):
            raise CoupleRuleError(
                "SCOPE_ANSWER_TYPE_INVALID",
                "A SCOPE answer must be an integer point on the question's scale.",
                details={"question_code": code},
            )
        if not question.scale_min <= value <= question.scale_max:
            raise CoupleRuleError(
                "SCOPE_ANSWER_OUT_OF_RANGE",
                f"Answer must be between {question.scale_min} and {question.scale_max}.",
                details={"question_code": code, "value": value},
            )
        cleaned[code] = value
    if not partial:
        missing = [code for code in by_code if code not in cleaned]
        if missing:
            raise CoupleRuleError(
                "SCOPE_ANSWER_MISSING",
                "Every question must be answered before submitting.",
                details={"question_codes": sorted(missing)},
            )
    return cleaned


# ---------------------------------------------------------------------------
# SCOPE-001 - sealed answers
# ---------------------------------------------------------------------------


def ensure_raw_answers_readable(*, viewer_id: UUID, owner_id: UUID) -> None:
    """The seal. Raw answers belong to exactly one person: their author.

    Independent answering is worthless if either partner can read the other's
    raw responses, so there is a single choke point and it is this function.
    Administrators are not exempt either — an operator investigating a dispute
    gets the deterministic scores and the audit trail, never the raw answers.
    """

    if viewer_id != owner_id:
        raise CoupleRuleError(
            "SCOPE_ANSWERS_SEALED",
            "A partner's raw SCOPE answers are sealed and cannot be read by anyone else.",
            details={"owner_id": str(owner_id)},
        )


def partner_progress_view(
    *, user_id: UUID, status: str, submitted_at: datetime | None
) -> dict[str, object]:
    """What one partner may learn about the other: progress, and nothing else.

    Returning a fixed, tiny shape here (rather than filtering a full row at the
    router) means a future column added to the submissions table cannot leak by
    accident.
    """

    return {
        "user_id": str(user_id),
        "status": ParticipantState(status).value,
        "submitted_at": submitted_at,
        "answers_visible": False,
    }


class ParticipantState(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"


class AssessmentState(StrEnum):
    COLLECTING = "collecting"
    COMPLETED = "completed"
    REPORT_READY = "report_ready"
    CANCELLED = "cancelled"


_ASSESSMENT_TRANSITIONS: dict[AssessmentState, frozenset[AssessmentState]] = {
    AssessmentState.COLLECTING: frozenset({AssessmentState.COMPLETED, AssessmentState.CANCELLED}),
    AssessmentState.COMPLETED: frozenset(
        {AssessmentState.REPORT_READY, AssessmentState.CANCELLED}
    ),
    AssessmentState.REPORT_READY: frozenset(),
    AssessmentState.CANCELLED: frozenset(),
}


def validate_assessment_transition(current: str, target: str) -> None:
    try:
        current_state = AssessmentState(current)
        target_state = AssessmentState(target)
    except ValueError as exc:
        raise CoupleRuleError("SCOPE_ASSESSMENT_STATE_UNKNOWN", str(exc)) from exc
    if target_state not in _ASSESSMENT_TRANSITIONS[current_state]:
        raise CoupleRuleError(
            "SCOPE_ASSESSMENT_TRANSITION_INVALID",
            f"Cannot move a SCOPE assessment from {current_state} to {target_state}.",
            details={"current": current_state.value, "target": target_state.value},
        )


@dataclass(frozen=True)
class ReportReadiness:
    ready: bool
    waiting_on: tuple[UUID, ...]
    reason_code: str


def evaluate_report_readiness(
    *, expected_members: Sequence[UUID], states: Mapping[UUID, str]
) -> ReportReadiness:
    """The completion barrier.

    No report — not a partial one, not a preview, not a "your side is done"
    teaser — exists until both partners have submitted. Anything less would let
    the first mover infer the second's answers from a moving score, which is the
    same leak the seal exists to prevent (SCOPE-001).
    """

    members = tuple(sorted(set(expected_members), key=str))
    if len(members) != 2:
        raise CoupleRuleError(
            "SCOPE_PARTICIPANTS_INVALID", "A SCOPE assessment always has exactly two participants."
        )
    unknown = [str(user) for user in states if user not in members]
    if unknown:
        raise CoupleRuleError(
            "SCOPE_PARTICIPANT_NOT_IN_RELATIONSHIP",
            "A submission exists for somebody who is not part of this relationship.",
            details={"user_ids": sorted(unknown)},
        )
    waiting: list[UUID] = []
    for member in members:
        state = states.get(member, ParticipantState.NOT_STARTED)
        if ParticipantState(state) is not ParticipantState.SUBMITTED:
            waiting.append(member)
    if waiting:
        return ReportReadiness(
            ready=False, waiting_on=tuple(waiting), reason_code="AWAITING_PARTNER_SUBMISSION"
        )
    return ReportReadiness(ready=True, waiting_on=(), reason_code="BOTH_SUBMITTED")


def ensure_report_ready(readiness: ReportReadiness) -> None:
    if not readiness.ready:
        raise CoupleRuleError(
            "SCOPE_REPORT_BARRIER",
            "The SCOPE report is generated only after both partners have submitted.",
            details={"waiting_on": [str(user) for user in readiness.waiting_on]},
        )


# ---------------------------------------------------------------------------
# SCOPE-001 - deterministic scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DimensionScore:
    dimension: ScopeDimension
    raw_total: int
    min_total: int
    max_total: int
    normalized: Decimal
    question_count: int


@dataclass(frozen=True)
class ScopeScoreSet:
    algorithm_version: str
    version_code: str
    semantic_version: str
    dimensions: tuple[DimensionScore, ...]
    composite: Decimal

    def by_dimension(self) -> dict[str, Decimal]:
        return {score.dimension.value: score.normalized for score in self.dimensions}


def _normalize(raw_total: int, min_total: int, max_total: int) -> Decimal:
    """Map a weighted raw total onto 0..100 with an exact, pinned rounding rule.

    ``Decimal`` with explicit ``ROUND_HALF_UP`` rather than float arithmetic:
    the same answers under the same ``algorithm_version`` must produce
    byte-identical output on every machine, forever, or a stored report can no
    longer be re-derived and defended.
    """

    span = max_total - min_total
    if span <= 0:
        raise CoupleRuleError(
            "SCOPE_SCORE_SPAN_INVALID", "A dimension must have a non-zero scoring span."
        )
    value = (Decimal(raw_total - min_total) / Decimal(span)) * Decimal(100)
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def score_scope(version: ScopeVersionSpec, answers: Mapping[str, int]) -> ScopeScoreSet:
    """Score one partner's submission. Pure, total and reproducible.

    Reproducibility guarantees, all tested:

    * dimension order is fixed by :data:`SCOPE_DIMENSION_ORDER`, never by dict
      or input ordering
    * answer iteration order does not affect the result (weighted sums commute)
    * arithmetic is integer + :class:`~decimal.Decimal`, never float
    * ``algorithm_version`` is carried into the result and into the fingerprint,
      so a report can always be tied back to the code that produced it
    """

    ensure_version_publishable(version)
    cleaned = validate_scope_answers(version, answers)
    dimensions: list[DimensionScore] = []
    for dimension in SCOPE_DIMENSION_ORDER:
        questions = version.questions_for(dimension)
        raw_total = 0
        min_total = 0
        max_total = 0
        for question in sorted(questions, key=lambda item: (item.position, item.question_code)):
            value = cleaned[question.question_code]
            if question.reverse_scored:
                # A reverse-keyed item is mirrored on its own scale so a high
                # raw answer still means "less of the dimension".
                value = question.scale_min + question.scale_max - value
            raw_total += question.weight * value
            min_total += question.weight * question.scale_min
            max_total += question.weight * question.scale_max
        dimensions.append(
            DimensionScore(
                dimension=dimension,
                raw_total=raw_total,
                min_total=min_total,
                max_total=max_total,
                normalized=_normalize(raw_total, min_total, max_total),
                question_count=len(questions),
            )
        )
    composite = (
        sum((score.normalized for score in dimensions), start=Decimal(0))
        / Decimal(len(dimensions))
    ).quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)
    return ScopeScoreSet(
        algorithm_version=version.algorithm_version,
        version_code=version.version_code,
        semantic_version=version.semantic_version,
        dimensions=tuple(dimensions),
        composite=composite,
    )


def scores_fingerprint(scores: ScopeScoreSet) -> str:
    """Stable hash proving a stored report was not silently re-scored."""

    digest = hashlib.sha256()
    digest.update(scores.algorithm_version.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(scores.version_code.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(scores.semantic_version.encode("utf-8"))
    for score in scores.dimensions:
        digest.update(b"\x00")
        digest.update(f"{score.dimension.value}={score.normalized}".encode())
    digest.update(b"\x00")
    digest.update(f"composite={scores.composite}".encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class AlignmentScore:
    dimension: ScopeDimension
    gap: Decimal
    alignment: Decimal


def compute_alignment(
    first: ScopeScoreSet, second: ScopeScoreSet
) -> tuple[AlignmentScore, ...]:
    """Pair-level view: how close the two partners scored on each dimension.

    This is intentionally the *only* cross-partner number produced. It exposes a
    distance, never the other partner's answers, and it is refused outright if
    the two sides were scored under different algorithm versions — comparing
    across versions would produce a number nobody could reproduce.
    """

    if first.algorithm_version != second.algorithm_version:
        raise CoupleRuleError(
            "SCOPE_ALGORITHM_VERSION_MISMATCH",
            "Both partners must be scored under the same algorithm version.",
            details={"first": first.algorithm_version, "second": second.algorithm_version},
        )
    left = first.by_dimension()
    right = second.by_dimension()
    result: list[AlignmentScore] = []
    for dimension in SCOPE_DIMENSION_ORDER:
        gap = abs(left[dimension.value] - right[dimension.value]).quantize(
            SCORE_QUANTUM, rounding=ROUND_HALF_UP
        )
        result.append(
            AlignmentScore(
                dimension=dimension,
                gap=gap,
                alignment=(Decimal(100) - gap).quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP),
            )
        )
    return tuple(result)


# ---------------------------------------------------------------------------
# SCOPE-001 - AI advice, kept structurally apart from the scores
# ---------------------------------------------------------------------------


class AdviceStatus(StrEnum):
    ABSENT = "absent"
    GENERATED = "generated"
    FAILED = "failed"


@dataclass(frozen=True)
class AdviceBlock:
    """Model-written narrative attached to a report.

    Held in its own dataclass, stored in its own columns and serialized under
    its own top-level key so that a reader — human or machine — can never
    mistake generated prose for a computed score. ``is_ai_generated`` is not
    configurable: anything travelling in this block is AI output by definition.
    """

    body: str
    model_code: str
    prompt_version: str
    generated_at: datetime
    disclaimer_code: str = "scope_ai_advice"
    is_ai_generated: bool = True

    def __post_init__(self) -> None:
        if not self.body.strip():
            raise CoupleRuleError("SCOPE_ADVICE_EMPTY", "Generated advice cannot be empty.")
        if self.generated_at.tzinfo is None:
            raise CoupleRuleError("COUPLE_NAIVE_DATETIME", "generated_at must be timezone-aware.")
        if not self.is_ai_generated:
            raise CoupleRuleError(
                "SCOPE_ADVICE_PROVENANCE_INVALID",
                "An advice block is AI-generated by definition and cannot claim otherwise.",
            )


#: Keys that must never appear inside the deterministic ``scores`` block.
_ADVICE_ONLY_KEYS: frozenset[str] = frozenset({"advice", "body", "model_code", "narrative"})


def assemble_report_payload(
    *,
    scores: Mapping[UUID, ScopeScoreSet],
    alignment: Sequence[AlignmentScore],
    advice: AdviceBlock | None,
    generated_at: datetime,
) -> dict[str, object]:
    """Build the stored/returned report body.

    Two top-level keys and no overlap between them:

    ``scores``
        Deterministic, reproducible from (answers, version, algorithm_version).
        Carries its own fingerprint so it can be re-derived and compared.
    ``advice``
        The AI narrative, or ``None``. Never merged into ``scores``, never used
        to compute anything, and safe to drop entirely if the advice feature is
        switched off.
    """

    if generated_at.tzinfo is None:
        raise CoupleRuleError("COUPLE_NAIVE_DATETIME", "generated_at must be timezone-aware.")
    per_member = []
    for user_id in sorted(scores, key=str):
        score_set = scores[user_id]
        per_member.append(
            {
                "user_id": str(user_id),
                "algorithm_version": score_set.algorithm_version,
                "dimensions": [
                    {
                        "dimension": item.dimension.value,
                        "normalized": str(item.normalized),
                        "raw_total": item.raw_total,
                        "min_total": item.min_total,
                        "max_total": item.max_total,
                        "question_count": item.question_count,
                    }
                    for item in score_set.dimensions
                ],
                "composite": str(score_set.composite),
                "fingerprint": scores_fingerprint(score_set),
            }
        )
    scores_block: dict[str, object] = {
        "deterministic": True,
        "generated_at": generated_at.isoformat(),
        "members": per_member,
        "alignment": [
            {
                "dimension": item.dimension.value,
                "gap": str(item.gap),
                "alignment": str(item.alignment),
            }
            for item in alignment
        ],
    }
    leaked = sorted(_ADVICE_ONLY_KEYS & set(scores_block))
    if leaked:  # pragma: no cover - structural guard
        raise CoupleRuleError(
            "SCOPE_REPORT_ADVICE_LEAK",
            "Advice fields must not appear inside the deterministic score block.",
            details={"keys": leaked},
        )
    advice_block: dict[str, object] | None = None
    if advice is not None:
        advice_block = {
            "is_ai_generated": True,
            "model_code": advice.model_code,
            "prompt_version": advice.prompt_version,
            "generated_at": advice.generated_at.isoformat(),
            "disclaimer_code": advice.disclaimer_code,
            "body": advice.body,
        }
    return {
        "scores": scores_block,
        "advice": advice_block,
        "advice_status": (
            AdviceStatus.GENERATED.value if advice is not None else AdviceStatus.ABSENT.value
        ),
    }


def report_idempotency_key(assessment_id: UUID, algorithm_version: str) -> str:
    """One report per (assessment, algorithm version), however many retries."""

    return f"scope-report:{assessment_id}:{algorithm_version}"


def binding_event_key(relationship_id: UUID, event_type: str, sequence: int) -> str:
    return f"couple-event:{relationship_id}:{event_type}:{sequence}"


def visible_members(members: Iterable[UUID], viewer_id: UUID) -> tuple[UUID, ...]:
    """Order members so the viewer is always first in a rendered report."""

    ordered = sorted(members, key=str)
    return tuple(sorted(ordered, key=lambda item: (item != viewer_id, str(item))))


#: Convenience for the service layer: the set of relationship states in which a
#: pair may start or continue a SCOPE assessment.
SCOPE_ACTIVE_RELATIONSHIP_STATES: frozenset[RelationshipState] = frozenset(
    {RelationshipState.ACTIVE}
)


def ensure_scope_relationship_active(state: str) -> None:
    """An assessment in flight stops if the pair unbinds.

    Continuing to collect intimate answers for a relationship that has ended is
    not something the platform should do silently, so the service cancels the
    assessment instead. The already-consumed free benefit is *not* returned —
    see :func:`decide_free_scope_grant`.
    """

    try:
        current = RelationshipState(state)
    except ValueError as exc:
        raise CoupleRuleError("COUPLE_RELATIONSHIP_STATE_UNKNOWN", str(exc)) from exc
    if current not in SCOPE_ACTIVE_RELATIONSHIP_STATES:
        raise CoupleRuleError(
            "COUPLE_RELATIONSHIP_NOT_ACTIVE",
            "A SCOPE assessment requires an active binding.",
            details={"state": current.value},
        )


@dataclass(frozen=True)
class ScopeInvitationSnapshot:
    """Read model returned to a member listing their invitations."""

    invitation_id: UUID
    inviter_id: UUID
    invitee_id: UUID
    status: InvitationStatus
    relationship_kind: RelationshipKind
    expires_at: datetime
    note_visible_to: frozenset[UUID] = field(default_factory=frozenset)

    def is_actionable_by(self, user_id: UUID, *, now: datetime) -> bool:
        if self.status is not InvitationStatus.PENDING:
            return False
        if is_invitation_expired(expires_at=self.expires_at, now=now):
            return False
        return user_id == self.invitee_id
