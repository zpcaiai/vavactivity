"""Pure paid-assessment product rules (B17).

Requirement coverage:

* ASSESS-001 a *generic* catalogue / purchase / entitlement / attempt /
  report-version framework. This module deliberately contains no DISC, MBTI,
  Five Love Languages or any other third-party instrument's items, scoring keys
  or normative data. Those instruments are licensed; the platform models the
  commerce and delivery around a question bank an administrator supplies, and
  every version must declare where its content came from.
* Publishing a version without a recorded, verified licence reference is
  rejected here and again by a database CHECK constraint in migration
  ``20260812_0101``. Two independent layers, because "we forgot to record the
  licence" is the failure that gets a platform sued.
* A purchase grants exactly the version that was bought. Publishing v2 must
  never silently upgrade (or downgrade) somebody who paid for v1.
* Refund and revocation behaviour is defined explicitly rather than left to
  whoever writes the admin tool: see :func:`plan_revocation`.
* DEC-001 safe default: the feature ships behind ``PAID_ASSESSMENTS_ENABLED``
  defaulting to false.

No database, settings, network or clock access. ``now`` is always a parameter.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID

# ---------------------------------------------------------------------------
# Shared errors
# ---------------------------------------------------------------------------


class AssessmentRuleError(Exception):
    """Raised when a caller violates a paid-assessment rule.

    ``code`` is the stable machine identifier; ``message`` is operator-facing
    English. Member-facing copy is localized in the frontend from ``code``.
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


# ---------------------------------------------------------------------------
# ASSESS-001 - catalogue and licensing
# ---------------------------------------------------------------------------


class ProductStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class VersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class ContentSource(StrEnum):
    """Where a version's items came from.

    This is the field that makes the licensing rule enforceable. It is stored
    per version, not per product, because a product may move from a licensed
    instrument to an in-house replacement without rewriting history.
    """

    #: Written by the platform's own editors. Still needs a reference (an
    #: internal authorship/ownership record) so provenance is never blank.
    ADMINISTRATOR_AUTHORED = "administrator_authored"
    #: Third-party instrument used under a commercial licence.
    LICENSED_THIRD_PARTY = "licensed_third_party"
    #: Out of copyright or explicitly released for reuse.
    PUBLIC_DOMAIN = "public_domain"
    #: Supplied by a partner under a contract.
    PARTNER_SUPPLIED = "partner_supplied"


#: Every source requires a reference. There is deliberately no "unknown" or
#: "none" member: a version whose provenance nobody recorded is exactly the
#: version that must not reach paying members.
LICENCE_REQUIRED_SOURCES: frozenset[ContentSource] = frozenset(ContentSource)

_VERSION_TRANSITIONS: dict[VersionStatus, frozenset[VersionStatus]] = {
    VersionStatus.DRAFT: frozenset({VersionStatus.PUBLISHED, VersionStatus.RETIRED}),
    # A published version is immutable. Retiring it stops new purchases while
    # leaving everybody who already bought it able to finish.
    VersionStatus.PUBLISHED: frozenset({VersionStatus.RETIRED}),
    VersionStatus.RETIRED: frozenset(),
}


def validate_version_transition(current: str, target: str) -> None:
    try:
        current_status = VersionStatus(current)
        target_status = VersionStatus(target)
    except ValueError as exc:
        raise AssessmentRuleError("ASSESSMENT_VERSION_STATUS_UNKNOWN", str(exc)) from exc
    if target_status not in _VERSION_TRANSITIONS[current_status]:
        raise AssessmentRuleError(
            "ASSESSMENT_VERSION_TRANSITION_INVALID",
            f"Cannot move an assessment version from {current_status} to {target_status}.",
            details={"current": current_status.value, "target": target_status.value},
        )


@dataclass(frozen=True)
class LicenseRecord:
    """Provenance of one assessment version's content.

    ``license_reference`` is free text on purpose — a contract number, a
    purchase order, an internal authorship ticket — because the shape differs
    per licensor. What is *not* optional is that something identifying is
    recorded and that a named human verified it at a known time.
    """

    content_source: ContentSource
    license_reference: str | None = None
    license_verified_at: datetime | None = None
    license_verified_by: UUID | None = None
    licensor_name: str | None = None

    def is_complete(self) -> bool:
        return bool(
            (self.license_reference or "").strip()
            and self.license_verified_at is not None
            and self.license_verified_by is not None
        )


MIN_LICENSE_REFERENCE_LENGTH = 3


def ensure_license_recorded(record: LicenseRecord, *, now: datetime) -> None:
    """Refuse to treat a version as licensed unless it demonstrably is.

    Called by :func:`ensure_version_publishable`; kept separate so the same
    check can be run by an audit job over already-stored rows.
    """

    if now.tzinfo is None:
        raise AssessmentRuleError("ASSESSMENT_NAIVE_DATETIME", "now must be timezone-aware.")
    reference = (record.license_reference or "").strip()
    if len(reference) < MIN_LICENSE_REFERENCE_LENGTH:
        raise AssessmentRuleError(
            "ASSESSMENT_LICENSE_REFERENCE_REQUIRED",
            "A version cannot be published without a recorded licence reference.",
            details={"content_source": record.content_source.value},
        )
    if record.license_verified_at is None or record.license_verified_by is None:
        raise AssessmentRuleError(
            "ASSESSMENT_LICENSE_NOT_VERIFIED",
            "A licence reference must be verified by a named administrator before publication.",
            details={"content_source": record.content_source.value},
        )
    if record.license_verified_at.tzinfo is None:
        raise AssessmentRuleError(
            "ASSESSMENT_NAIVE_DATETIME", "license_verified_at must be timezone-aware."
        )
    if record.license_verified_at > now:
        # A future verification timestamp means somebody typed a date instead of
        # verifying anything.
        raise AssessmentRuleError(
            "ASSESSMENT_LICENSE_VERIFIED_IN_FUTURE",
            "The licence verification timestamp is in the future.",
            details={"license_verified_at": record.license_verified_at.isoformat()},
        )
    if (
        record.content_source
        in (
            ContentSource.LICENSED_THIRD_PARTY,
            ContentSource.PARTNER_SUPPLIED,
        )
        and not (record.licensor_name or "").strip()
    ):
        raise AssessmentRuleError(
            "ASSESSMENT_LICENSOR_REQUIRED",
            "Third-party and partner-supplied content must name the licensor.",
            details={"content_source": record.content_source.value},
        )


@dataclass(frozen=True)
class AssessmentQuestionSpec:
    """One administrator-supplied question. No shipped content (ASSESS-001)."""

    question_id: UUID
    question_code: str
    dimension_code: str
    weight: int = 1
    scale_min: int = 1
    scale_max: int = 5
    reverse_scored: bool = False
    position: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.weight <= 10:
            raise AssessmentRuleError(
                "ASSESSMENT_QUESTION_WEIGHT_INVALID",
                "Question weight must be between 1 and 10.",
                details={"question_code": self.question_code},
            )
        if not 1 <= self.scale_min < self.scale_max <= 10:
            raise AssessmentRuleError(
                "ASSESSMENT_QUESTION_SCALE_INVALID",
                "Scale must satisfy 1 <= min < max <= 10.",
                details={"question_code": self.question_code},
            )
        if not self.dimension_code.strip():
            raise AssessmentRuleError(
                "ASSESSMENT_QUESTION_DIMENSION_REQUIRED",
                "Every question must belong to a named dimension.",
                details={"question_code": self.question_code},
            )


@dataclass(frozen=True)
class AssessmentVersionSpec:
    """A purchasable, immutable-once-published assessment version."""

    version_id: UUID
    product_id: UUID
    semantic_version: str
    algorithm_version: str
    license: LicenseRecord
    price_minor_units: int
    currency: str = "CNY"
    questions: tuple[AssessmentQuestionSpec, ...] = ()

    def __post_init__(self) -> None:
        codes = [question.question_code for question in self.questions]
        if len(set(codes)) != len(codes):
            raise AssessmentRuleError(
                "ASSESSMENT_QUESTION_CODE_DUPLICATE",
                "Question codes must be unique within a version.",
            )
        if self.price_minor_units < 0:
            raise AssessmentRuleError("ASSESSMENT_PRICE_INVALID", "A price cannot be negative.")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise AssessmentRuleError(
                "ASSESSMENT_CURRENCY_INVALID", "Currency must be a 3-letter uppercase code."
            )

    def dimensions(self) -> tuple[str, ...]:
        seen: list[str] = []
        for question in self.questions:
            if question.dimension_code not in seen:
                seen.append(question.dimension_code)
        return tuple(sorted(seen))


def ensure_version_publishable(version: AssessmentVersionSpec, *, now: datetime) -> None:
    """The publication gate.

    A version reaches paying members only when it (a) has content, and (b) can
    prove where that content came from. The licence check runs even for
    administrator-authored content, because "we wrote it ourselves" is itself a
    provenance claim that somebody should have to record and sign.
    """

    if not version.questions:
        raise AssessmentRuleError(
            "ASSESSMENT_VERSION_EMPTY",
            "A version cannot be published with no questions; the question bank is "
            "administrator-supplied and ships empty.",
            details={"semantic_version": version.semantic_version},
        )
    ensure_license_recorded(version.license, now=now)
    if version.price_minor_units <= 0:
        raise AssessmentRuleError(
            "ASSESSMENT_PRICE_REQUIRED",
            "A paid assessment version needs a price above zero before publication.",
            details={"semantic_version": version.semantic_version},
        )


# ---------------------------------------------------------------------------
# ASSESS-001 - purchase and entitlement
# ---------------------------------------------------------------------------


class PurchaseStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class EntitlementStatus(StrEnum):
    ACTIVE = "active"
    CONSUMED = "consumed"
    REVOKED = "revoked"
    EXPIRED = "expired"


_PURCHASE_TRANSITIONS: dict[PurchaseStatus, frozenset[PurchaseStatus]] = {
    PurchaseStatus.PENDING: frozenset(
        {PurchaseStatus.PAID, PurchaseStatus.FAILED, PurchaseStatus.CANCELLED}
    ),
    PurchaseStatus.PAID: frozenset({PurchaseStatus.REFUNDED}),
    PurchaseStatus.FAILED: frozenset(),
    PurchaseStatus.CANCELLED: frozenset(),
    PurchaseStatus.REFUNDED: frozenset(),
}


def validate_purchase_transition(current: str, target: str) -> None:
    try:
        current_status = PurchaseStatus(current)
        target_status = PurchaseStatus(target)
    except ValueError as exc:
        raise AssessmentRuleError("ASSESSMENT_PURCHASE_STATUS_UNKNOWN", str(exc)) from exc
    if target_status not in _PURCHASE_TRANSITIONS[current_status]:
        raise AssessmentRuleError(
            "ASSESSMENT_PURCHASE_TRANSITION_INVALID",
            f"Cannot move a purchase from {current_status} to {target_status}.",
            details={"current": current_status.value, "target": target_status.value},
        )


def purchase_idempotency_key(user_id: UUID, order_id: str) -> str:
    """One purchase row per payment order, however many callbacks arrive."""

    return f"assessment-purchase:{user_id}:{order_id}"


@dataclass(frozen=True)
class PurchaseIntent:
    user_id: UUID
    product_id: UUID
    version_id: UUID
    semantic_version: str
    algorithm_version: str
    price_minor_units: int
    currency: str
    attempts_granted: int
    idempotency_key: str


def build_purchase_intent(
    version: AssessmentVersionSpec,
    *,
    user_id: UUID,
    order_id: str,
    version_status: str,
    product_status: str,
    quoted_price_minor_units: int,
    attempts_granted: int = 1,
) -> PurchaseIntent:
    """Pin a purchase to one exact version.

    ``version_id`` is captured here and carried on the purchase, the
    entitlement and every attempt. Nothing downstream ever resolves "the
    product's current version", which is what stops a member who paid for v1
    from being silently moved onto v2 when the catalogue is updated — the
    version-drift bug this framework exists to prevent.

    The quoted price is compared against the version's price so a stale client
    cannot buy yesterday's cheaper listing.
    """

    if VersionStatus(version_status) is not VersionStatus.PUBLISHED:
        raise AssessmentRuleError(
            "ASSESSMENT_VERSION_NOT_PURCHASABLE",
            "Only a published version can be purchased.",
            details={"version_status": version_status},
        )
    if ProductStatus(product_status) is not ProductStatus.ACTIVE:
        raise AssessmentRuleError(
            "ASSESSMENT_PRODUCT_NOT_ACTIVE",
            "This assessment product is not on sale.",
            details={"product_status": product_status},
        )
    if quoted_price_minor_units != version.price_minor_units:
        raise AssessmentRuleError(
            "ASSESSMENT_PRICE_MISMATCH",
            "The quoted price no longer matches the published price for this version.",
            details={
                "quoted": quoted_price_minor_units,
                "published": version.price_minor_units,
            },
        )
    if attempts_granted < 1:
        raise AssessmentRuleError(
            "ASSESSMENT_ATTEMPTS_INVALID", "A purchase must grant at least one attempt."
        )
    return PurchaseIntent(
        user_id=user_id,
        product_id=version.product_id,
        version_id=version.version_id,
        semantic_version=version.semantic_version,
        algorithm_version=version.algorithm_version,
        price_minor_units=version.price_minor_units,
        currency=version.currency,
        attempts_granted=attempts_granted,
        idempotency_key=purchase_idempotency_key(user_id, order_id),
    )


@dataclass(frozen=True)
class EntitlementState:
    entitlement_id: UUID
    user_id: UUID
    version_id: UUID
    status: EntitlementStatus
    attempts_granted: int = 1
    attempts_consumed: int = 0
    expires_at: datetime | None = None

    @property
    def attempts_remaining(self) -> int:
        return max(0, self.attempts_granted - self.attempts_consumed)

    def is_expired(self, now: datetime) -> bool:
        if self.expires_at is None:
            return False
        if now.tzinfo is None or self.expires_at.tzinfo is None:
            raise AssessmentRuleError(
                "ASSESSMENT_NAIVE_DATETIME", "Entitlement timestamps must be timezone-aware."
            )
        return now >= self.expires_at


def ensure_entitlement_usable(state: EntitlementState, *, now: datetime) -> None:
    """Gate every attempt start and every report read."""

    if state.status is EntitlementStatus.REVOKED:
        raise AssessmentRuleError(
            "ASSESSMENT_ENTITLEMENT_REVOKED",
            "This entitlement was revoked and can no longer be used.",
            details={"entitlement_id": str(state.entitlement_id)},
        )
    if state.status is EntitlementStatus.EXPIRED or state.is_expired(now):
        raise AssessmentRuleError("ASSESSMENT_ENTITLEMENT_EXPIRED", "This entitlement has expired.")
    if state.attempts_remaining <= 0:
        raise AssessmentRuleError(
            "ASSESSMENT_ENTITLEMENT_EXHAUSTED",
            "No attempts remain on this entitlement.",
            details={
                "attempts_granted": state.attempts_granted,
                "attempts_consumed": state.attempts_consumed,
            },
        )


def ensure_version_matches_entitlement(
    *, entitlement_version_id: UUID, requested_version_id: UUID
) -> None:
    """No "latest version" drift after purchase.

    Every attempt, score and report resolves its questions through the version
    the entitlement names. If a caller ever asks for a different version — a
    client caching the catalogue, an admin tool defaulting to "current" — the
    request is refused rather than quietly served with content the member did
    not buy.
    """

    if entitlement_version_id != requested_version_id:
        raise AssessmentRuleError(
            "ASSESSMENT_VERSION_DRIFT",
            "This entitlement is bound to a different assessment version.",
            details={
                "entitled_version_id": str(entitlement_version_id),
                "requested_version_id": str(requested_version_id),
            },
        )


# ---------------------------------------------------------------------------
# ASSESS-001 - attempts and reports
# ---------------------------------------------------------------------------


class AttemptStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    SCORED = "scored"
    ABANDONED = "abandoned"
    #: Terminated by a refund or revocation. Kept, never deleted.
    VOIDED = "voided"


class ReportStatus(StrEnum):
    GENERATED = "generated"
    REVOKED = "revoked"


_ATTEMPT_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    AttemptStatus.IN_PROGRESS: frozenset(
        {AttemptStatus.SUBMITTED, AttemptStatus.ABANDONED, AttemptStatus.VOIDED}
    ),
    AttemptStatus.SUBMITTED: frozenset({AttemptStatus.SCORED, AttemptStatus.VOIDED}),
    AttemptStatus.SCORED: frozenset({AttemptStatus.VOIDED}),
    AttemptStatus.ABANDONED: frozenset({AttemptStatus.VOIDED}),
    AttemptStatus.VOIDED: frozenset(),
}


def validate_attempt_transition(current: str, target: str) -> None:
    try:
        current_status = AttemptStatus(current)
        target_status = AttemptStatus(target)
    except ValueError as exc:
        raise AssessmentRuleError("ASSESSMENT_ATTEMPT_STATUS_UNKNOWN", str(exc)) from exc
    if target_status not in _ATTEMPT_TRANSITIONS[current_status]:
        raise AssessmentRuleError(
            "ASSESSMENT_ATTEMPT_TRANSITION_INVALID",
            f"Cannot move an attempt from {current_status} to {target_status}.",
            details={"current": current_status.value, "target": target_status.value},
        )


def validate_attempt_answers(
    version: AssessmentVersionSpec, answers: Mapping[str, int], *, partial: bool = False
) -> dict[str, int]:
    by_code = {question.question_code: question for question in version.questions}
    cleaned: dict[str, int] = {}
    for code, value in answers.items():
        question = by_code.get(code)
        if question is None:
            raise AssessmentRuleError(
                "ASSESSMENT_ANSWER_QUESTION_UNKNOWN",
                "An answer refers to a question that is not part of this version.",
                details={"question_code": code},
            )
        if not isinstance(value, int) or isinstance(value, bool):
            raise AssessmentRuleError(
                "ASSESSMENT_ANSWER_TYPE_INVALID",
                "An answer must be an integer point on the question's scale.",
                details={"question_code": code},
            )
        if not question.scale_min <= value <= question.scale_max:
            raise AssessmentRuleError(
                "ASSESSMENT_ANSWER_OUT_OF_RANGE",
                f"Answer must be between {question.scale_min} and {question.scale_max}.",
                details={"question_code": code, "value": value},
            )
        cleaned[code] = value
    if not partial:
        missing = [code for code in by_code if code not in cleaned]
        if missing:
            raise AssessmentRuleError(
                "ASSESSMENT_ANSWER_MISSING",
                "Every question must be answered before submitting.",
                details={"question_codes": sorted(missing)},
            )
    return cleaned


SCORE_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class DimensionScore:
    dimension_code: str
    raw_total: int
    min_total: int
    max_total: int
    normalized: Decimal
    question_count: int


@dataclass(frozen=True)
class ScoreSet:
    algorithm_version: str
    semantic_version: str
    dimensions: tuple[DimensionScore, ...]


def score_attempt(version: AssessmentVersionSpec, answers: Mapping[str, int]) -> ScoreSet:
    """Generic weighted scoring, identical in spirit to SCOPE's.

    Dimension codes come from the version's own questions, so the framework
    carries no opinion about what the dimensions *are* — that is exactly what
    keeps it usable for a licensed instrument without embedding the instrument.
    Integer weights plus :class:`~decimal.Decimal` normalisation make the result
    reproducible from (answers, version, algorithm_version).
    """

    cleaned = validate_attempt_answers(version, answers)
    dimensions: list[DimensionScore] = []
    for dimension_code in version.dimensions():
        questions = [
            question for question in version.questions if question.dimension_code == dimension_code
        ]
        raw_total = 0
        min_total = 0
        max_total = 0
        for question in sorted(questions, key=lambda item: (item.position, item.question_code)):
            value = cleaned[question.question_code]
            if question.reverse_scored:
                value = question.scale_min + question.scale_max - value
            raw_total += question.weight * value
            min_total += question.weight * question.scale_min
            max_total += question.weight * question.scale_max
        span = max_total - min_total
        if span <= 0:  # pragma: no cover - guarded by scale validation
            raise AssessmentRuleError(
                "ASSESSMENT_SCORE_SPAN_INVALID", "A dimension must have a non-zero span."
            )
        normalized = ((Decimal(raw_total - min_total) / Decimal(span)) * Decimal(100)).quantize(
            SCORE_QUANTUM, rounding=ROUND_HALF_UP
        )
        dimensions.append(
            DimensionScore(
                dimension_code=dimension_code,
                raw_total=raw_total,
                min_total=min_total,
                max_total=max_total,
                normalized=normalized,
                question_count=len(questions),
            )
        )
    return ScoreSet(
        algorithm_version=version.algorithm_version,
        semantic_version=version.semantic_version,
        dimensions=tuple(dimensions),
    )


def scores_fingerprint(scores: ScoreSet) -> str:
    digest = hashlib.sha256()
    digest.update(scores.algorithm_version.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(scores.semantic_version.encode("utf-8"))
    for score in scores.dimensions:
        digest.update(b"\x00")
        digest.update(f"{score.dimension_code}={score.normalized}".encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class AdviceBlock:
    """AI narrative attached to a paid report, kept apart from the scores."""

    body: str
    model_code: str
    prompt_version: str
    generated_at: datetime
    disclaimer_code: str = "assessment_ai_advice"
    is_ai_generated: bool = True

    def __post_init__(self) -> None:
        if not self.body.strip():
            raise AssessmentRuleError("ASSESSMENT_ADVICE_EMPTY", "Advice cannot be empty.")
        if self.generated_at.tzinfo is None:
            raise AssessmentRuleError(
                "ASSESSMENT_NAIVE_DATETIME", "generated_at must be timezone-aware."
            )


def assemble_report_payload(
    *, scores: ScoreSet, advice: AdviceBlock | None, generated_at: datetime
) -> dict[str, object]:
    """Two top-level keys: deterministic ``scores`` and separate ``advice``."""

    if generated_at.tzinfo is None:
        raise AssessmentRuleError("ASSESSMENT_NAIVE_DATETIME", "generated_at must be tz-aware.")
    scores_block: dict[str, object] = {
        "deterministic": True,
        "algorithm_version": scores.algorithm_version,
        "semantic_version": scores.semantic_version,
        "generated_at": generated_at.isoformat(),
        "dimensions": [
            {
                "dimension_code": item.dimension_code,
                "normalized": str(item.normalized),
                "raw_total": item.raw_total,
                "min_total": item.min_total,
                "max_total": item.max_total,
                "question_count": item.question_count,
            }
            for item in scores.dimensions
        ],
        "fingerprint": scores_fingerprint(scores),
    }
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
    return {"scores": scores_block, "advice": advice_block}


def report_idempotency_key(attempt_id: UUID, algorithm_version: str) -> str:
    return f"assessment-report:{attempt_id}:{algorithm_version}"


def attempt_idempotency_key(entitlement_id: UUID, sequence: int) -> str:
    """One attempt row per (entitlement, sequence), so a retried start is safe."""

    return f"assessment-attempt:{entitlement_id}:{sequence}"


# ---------------------------------------------------------------------------
# ASSESS-001 - refund and revocation policy
# ---------------------------------------------------------------------------


class RefundTrigger(StrEnum):
    #: Member asked, inside the refund window, before the report existed.
    MEMBER_REQUEST = "member_request"
    #: Payment reversed by the provider or the bank.
    PAYMENT_REVERSAL = "payment_reversal"
    #: Operations decision — always requires a reason and an override flag.
    ADMIN_GOODWILL = "admin_goodwill"
    #: The licence behind the version was withdrawn; nobody may keep reading it.
    LICENSE_WITHDRAWN = "license_withdrawn"


class AttemptAction(StrEnum):
    NONE = "none"
    #: Terminate an unfinished attempt. The member loses access immediately.
    VOID = "void"
    #: Keep a finished attempt's record for audit while revoking access.
    RETAIN_SEALED = "retain_sealed"


class ReportAction(StrEnum):
    NONE = "none"
    #: Row retained, member access withdrawn. A generated report is *never*
    #: hard-deleted: it is evidence of what the member was shown.
    REVOKE_ACCESS = "revoke_access"


@dataclass(frozen=True)
class RevocationPlan:
    entitlement_status: EntitlementStatus
    attempt_action: AttemptAction
    report_action: ReportAction
    refund_allowed: bool
    reason_code: str


def plan_revocation(
    *,
    trigger: str,
    attempt_status: str | None,
    report_status: str | None,
    admin_override: bool = False,
    reason: str | None = None,
) -> RevocationPlan:
    """Define, in one place, what a refund does to work already in flight.

    The policy, stated explicitly so nobody has to infer it from admin-tool
    behaviour:

    * **Entitlement** always ends up ``revoked``. A refunded member does not
      keep a usable entitlement.
    * **In-progress attempt** -> ``void``. Answers already typed are kept in the
      row (they are the member's own data and may be needed for a dispute) but
      the attempt can never be submitted or scored.
    * **Submitted / scored attempt** -> ``retain_sealed``. The record stays for
      audit and accounting; access goes away with the entitlement.
    * **Generated report** -> ``revoke_access``, never delete. Deleting it would
      destroy the evidence of what the member was actually shown.
    * **Refund eligibility**: automatic while no report has been generated. Once
      a report exists the product has been delivered, so a refund needs an
      explicit administrative override with a reason — except for a payment
      reversal (the money is already gone) or a withdrawn licence (the platform
      is at fault, so the member is made whole regardless).
    """

    try:
        trigger_value = RefundTrigger(trigger)
    except ValueError as exc:
        raise AssessmentRuleError("ASSESSMENT_REFUND_TRIGGER_UNKNOWN", str(exc)) from exc

    attempt_state = AttemptStatus(attempt_status) if attempt_status else None
    report_state = ReportStatus(report_status) if report_status else None

    if attempt_state in (AttemptStatus.IN_PROGRESS,):
        attempt_action = AttemptAction.VOID
    elif attempt_state in (
        AttemptStatus.SUBMITTED,
        AttemptStatus.SCORED,
        AttemptStatus.ABANDONED,
    ):
        attempt_action = AttemptAction.RETAIN_SEALED
    else:
        attempt_action = AttemptAction.NONE

    report_existed = report_state is ReportStatus.GENERATED
    report_action = ReportAction.REVOKE_ACCESS if report_existed else ReportAction.NONE

    refund_allowed = True
    reason_code = "REFUND_BEFORE_DELIVERY"
    if report_existed:
        if trigger_value in (RefundTrigger.PAYMENT_REVERSAL, RefundTrigger.LICENSE_WITHDRAWN):
            reason_code = f"REFUND_FORCED_{trigger_value.value.upper()}"
        elif trigger_value is RefundTrigger.ADMIN_GOODWILL and admin_override:
            if len((reason or "").strip()) < 4:
                raise AssessmentRuleError(
                    "ASSESSMENT_REFUND_REASON_REQUIRED",
                    "Refunding a delivered report requires a written reason.",
                )
            reason_code = "REFUND_GOODWILL_OVERRIDE"
        else:
            refund_allowed = False
            reason_code = "REPORT_ALREADY_DELIVERED"

    return RevocationPlan(
        entitlement_status=EntitlementStatus.REVOKED,
        attempt_action=attempt_action,
        report_action=report_action,
        refund_allowed=refund_allowed,
        reason_code=reason_code,
    )


def ensure_refund_window_open(*, purchased_at: datetime, now: datetime, window_hours: int) -> None:
    """Self-service refunds are time-boxed; administrators are not.

    Separated from :func:`plan_revocation` so an administrative refund can
    deliberately skip it while a member-initiated one cannot.
    """

    if purchased_at.tzinfo is None or now.tzinfo is None:
        raise AssessmentRuleError(
            "ASSESSMENT_NAIVE_DATETIME", "Refund timestamps must be timezone-aware."
        )
    if window_hours <= 0:
        raise AssessmentRuleError(
            "ASSESSMENT_REFUND_WINDOW_CLOSED", "Self-service refunds are disabled."
        )
    elapsed_hours = (now - purchased_at).total_seconds() / 3600
    if elapsed_hours > window_hours:
        raise AssessmentRuleError(
            "ASSESSMENT_REFUND_WINDOW_CLOSED",
            f"The {window_hours}-hour self-service refund window has closed.",
            details={"elapsed_hours": round(elapsed_hours, 2)},
        )


def ensure_report_readable(
    *, viewer_id: UUID, owner_id: UUID, report_status: str, entitlement_status: str
) -> None:
    """A report belongs to the member who bought it, in the state it is in."""

    if viewer_id != owner_id:
        raise AssessmentRuleError(
            "ASSESSMENT_REPORT_FORBIDDEN",
            "An assessment report can only be read by the member it belongs to.",
        )
    if ReportStatus(report_status) is ReportStatus.REVOKED:
        raise AssessmentRuleError(
            "ASSESSMENT_REPORT_REVOKED", "This report was revoked and is no longer available."
        )
    if EntitlementStatus(entitlement_status) is EntitlementStatus.REVOKED:
        raise AssessmentRuleError(
            "ASSESSMENT_ENTITLEMENT_REVOKED",
            "The entitlement behind this report was revoked.",
        )


def catalogue_view(
    versions: Sequence[Mapping[str, object]], *, include_unpublished: bool = False
) -> list[Mapping[str, object]]:
    """Filter a catalogue listing for member consumption.

    Draft versions are invisible to members even by direct id, because a draft
    may carry unlicensed content that has not been reviewed yet.
    """

    if include_unpublished:
        return list(versions)
    return [
        version
        for version in versions
        if str(version.get("status")) == VersionStatus.PUBLISHED.value
    ]
