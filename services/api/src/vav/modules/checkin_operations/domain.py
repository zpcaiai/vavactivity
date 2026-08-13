"""Pure onsite check-in operation rules (B08 / CHK-002).

This module deliberately contains no database, settings, network or clock
access so that every rule below is unit-testable without a real stack. The
service layer owns transactions and secrets; this layer owns decisions. Every
function that needs the current time takes ``now`` as an argument, and every
function that needs a key takes it as a ``bytes`` argument.

Requirement coverage:

* CHK-002 phone last-four lookup that never returns, logs or reconstructs a
  full phone number. The stored contact value is encrypted and its searchable
  HMAC covers the *whole* number, so a last-four search cannot be a direct HMAC
  match on the existing column. The honest design is a second, dedicated
  ``last_four_hmac`` column (see migration ``20260812_0105``) used purely to
  narrow candidates - never to prove identity.
* CHK-002 ambiguity: two or more candidates sharing a last-four is the normal
  case at scale, not an edge case. This module refuses to resolve a person from
  a last-four alone whenever more than one candidate matches, and the
  discriminator it offers instead is itself non-identifying: a masked name
  initial plus a registration-number suffix, addressed by an opaque choice
  token rather than by user id.
* CHK-002 onsite operator mode. The frontend part of "large touch targets,
  misoperation resistance" is layout; the server part is this module:
  an explicit confirm step behind a short-lived token, an undo window that
  demands a written reason, repeat scans that are idempotent successes rather
  than errors, and a per-operator sliding-window rate limit so a stuck scanner
  cannot spam the check-in endpoint.
* CHK-002 out-of-window check-in follows an explicit policy: configured early
  and late grace minutes, and anything outside them requires an override
  permission *and* a reason that is written to the audit trail.
"""

from __future__ import annotations

import hashlib
import hmac
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

# ---------------------------------------------------------------------------
# Shared errors
# ---------------------------------------------------------------------------


class CheckinRuleError(Exception):
    """Raised when a caller violates an onsite check-in rule.

    ``code`` is the stable machine identifier surfaced to clients; ``message``
    is an operator-facing English sentence. Member-facing copy is localized in
    the frontend from ``code``, never from ``message``.

    ``details`` is a mapping here because a rule's structured context is
    naturally keyed; the service layer wraps it in a single-element list when
    building a ``VavError``, whose ``details`` is a list in this codebase.
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


# ---------------------------------------------------------------------------
# Shared vocabulary, mirrored from the activities schema
# ---------------------------------------------------------------------------


class RegistrationStatus(StrEnum):
    """Mirrors the ``activity_registrations.status`` CHECK constraint."""

    STARTED = "started"
    PENDING_APPROVAL = "pending_approval"
    APPROVED_PENDING_PAYMENT = "approved_pending_payment"
    PENDING_PAYMENT = "pending_payment"
    PAYMENT_PROCESSING = "payment_processing"
    CONFIRMED = "confirmed"
    WAITLISTED = "waitlisted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AttendanceStatus(StrEnum):
    """Mirrors the ``activity_registrations.attendance_status`` CHECK constraint."""

    NOT_CHECKED_IN = "not_checked_in"
    CHECKED_IN = "checked_in"
    CHECKIN_REVOKED = "checkin_revoked"
    NO_SHOW = "no_show"


#: The only registration status that may be checked in. Everything else is a
#: refusal with its own code so the operator sees *why*, not just "no".
CHECKIN_ELIGIBLE_REGISTRATION_STATUSES: frozenset[str] = frozenset({RegistrationStatus.CONFIRMED})

#: Registration statuses that mean the person deliberately is not coming. These
#: get a distinct error code because the operator's next action differs: a
#: cancelled ticket is a front-desk conversation, a pending payment is a
#: payment link.
TERMINAL_REGISTRATION_STATUSES: frozenset[str] = frozenset(
    {RegistrationStatus.CANCELLED, RegistrationStatus.REJECTED, RegistrationStatus.EXPIRED}
)


def _require_aware(value: datetime, field_name: str) -> datetime:
    """Reject naive datetimes rather than silently assuming UTC."""

    if value.tzinfo is None:
        raise CheckinRuleError(
            "CHECKIN_NAIVE_DATETIME",
            f"{field_name} must be timezone-aware.",
            details={"field": field_name},
        )
    return value


# ---------------------------------------------------------------------------
# CHK-002 - phone last-four normalization and lookup keys
# ---------------------------------------------------------------------------

#: Characters an operator may realistically type or paste around a number.
_PHONE_PUNCTUATION = frozenset(" -()+. 　")

#: Minimum digits we accept as "a phone number" before deriving a last-four.
#: Four digits alone are a last-four, not a number; see ``ensure_last_four``.
MIN_PHONE_DIGITS = 6

#: Length of the trailing fragment used for narrowing. Fixed at four: making it
#: configurable would let an operator widen it to six or eight and turn a
#: narrowing hint into a phone-number oracle.
LAST_FOUR_LENGTH = 4


def normalize_phone_digits(raw: str) -> str:
    """Strip operator-typed punctuation and return the digits of a number.

    Raises rather than silently dropping unexpected characters: an input with
    letters in it is a mis-scan or a wrong field, and guessing at what the
    operator meant is how the wrong person gets checked in.
    """

    if raw is None:
        raise CheckinRuleError("CHECKIN_PHONE_INPUT_INVALID", "A phone value is required.")
    cleaned = "".join(char for char in raw.strip() if char not in _PHONE_PUNCTUATION)
    if not cleaned:
        raise CheckinRuleError("CHECKIN_PHONE_INPUT_INVALID", "A phone value is required.")
    if not cleaned.isdigit():
        raise CheckinRuleError(
            "CHECKIN_PHONE_INPUT_INVALID",
            "A phone value may only contain digits and separator punctuation.",
        )
    if len(cleaned) < MIN_PHONE_DIGITS:
        raise CheckinRuleError(
            "CHECKIN_PHONE_INPUT_TOO_SHORT",
            f"A phone value needs at least {MIN_PHONE_DIGITS} digits.",
            details={"digits": len(cleaned)},
        )
    return cleaned


def ensure_last_four(value: str) -> str:
    """Validate an operator-supplied last-four fragment.

    This is the *only* accepted lookup input on the onsite path. Accepting a
    longer fragment would let the search endpoint confirm progressively more of
    a member's number, one query at a time.
    """

    if value is None:
        raise CheckinRuleError("CHECKIN_LAST_FOUR_INVALID", "A last-four fragment is required.")
    cleaned = value.strip()
    if len(cleaned) != LAST_FOUR_LENGTH or not cleaned.isdigit():
        raise CheckinRuleError(
            "CHECKIN_LAST_FOUR_INVALID",
            "The last-four fragment must be exactly four digits.",
            details={"length": len(cleaned)},
        )
    return cleaned


def last_four_of(raw_phone: str) -> str:
    """Derive the storable fragment from a full number, on the write path."""

    return normalize_phone_digits(raw_phone)[-LAST_FOUR_LENGTH:]


def last_four_hmac(last_four: str, *, key: bytes, salt_version: str = "v1") -> str:
    """Deployment-salted HMAC of *only* the last four digits.

    Why a separate column rather than reusing ``user_contact_points.value_hmac``:
    that column is the HMAC of the whole number, which by construction cannot be
    matched from a fragment. Why an HMAC rather than the plain fragment: a
    dump of the table would otherwise be a free four-digit index over the whole
    member base. Why per-deployment salt: 10⁴ possible values are trivially
    enumerable, so the salt is the only thing standing between an offline copy
    and a rainbow table - the column is a *narrowing* aid, never a proof of
    identity, and is documented as such in the migration.

    The returned value is prefixed with the salt version so a key rotation can
    be rolled out incrementally: rows written under ``v1`` stay matchable while
    ``v2`` is backfilled.
    """

    fragment = ensure_last_four(last_four)
    if not key:
        raise CheckinRuleError(
            "CHECKIN_LAST_FOUR_KEY_MISSING",
            "A last-four HMAC key is required; refusing to hash with an empty key.",
        )
    digest = hmac.new(key, f"{salt_version}:{fragment}".encode(), hashlib.sha256).hexdigest()
    return f"{salt_version}:{digest}"


def mask_phone_fragment(last_four: str) -> str:
    """Render a fragment for an operator screen without implying a full number.

    Deliberately *not* ``***-****-1234``: that shape suggests the system knows
    and could show the rest. ``••••1234`` says "a number ending in".
    """

    return "••••" + ensure_last_four(last_four)


# ---------------------------------------------------------------------------
# CHK-002 - candidates, discriminators and opaque choice tokens
# ---------------------------------------------------------------------------


class LookupOutcome(StrEnum):
    NO_MATCH = "no_match"
    SINGLE_CANDIDATE = "single_candidate"
    AMBIGUOUS = "ambiguous"
    TOO_MANY = "too_many"


#: Above this count the result set is useless to an operator and is a signal
#: that someone is enumerating. The API returns ``TOO_MANY`` with no candidates
#: at all rather than a long list of maskings.
MAX_LOOKUP_CANDIDATES = 8


@dataclass(frozen=True)
class LookupCandidate:
    """One registration that shares the searched last-four.

    Everything identifying on this record stays server-side. Only the derived,
    masked fields ever reach a response - see :func:`candidate_choice_payload`.
    """

    registration_id: UUID
    user_id: UUID
    registration_number: str
    display_name: str
    registration_status: str
    attendance_status: str
    ticket_label: str = ""


@dataclass(frozen=True)
class LookupDecision:
    outcome: LookupOutcome
    candidates: tuple[LookupCandidate, ...]
    #: Set only for :attr:`LookupOutcome.SINGLE_CANDIDATE`. Even then this is
    #: *not* a check-in: the operator still has to confirm.
    resolved_registration_id: UUID | None
    requires_discriminator: bool


def decide_lookup_outcome(candidates: Sequence[LookupCandidate]) -> LookupDecision:
    """Classify a last-four search result.

    The load-bearing rule: **two or more candidates never resolve to a person**.
    The caller gets ``AMBIGUOUS`` with ``requires_discriminator`` set and must
    come back with a choice token, which requires the operator to read a
    discriminator off the member's own ticket or say their family name out loud.
    A last-four is a narrowing hint; it is not an identity claim, and this
    function is where that distinction is enforced rather than assumed.
    """

    unique: list[LookupCandidate] = []
    seen: set[UUID] = set()
    for candidate in candidates:
        if candidate.registration_id in seen:
            continue
        seen.add(candidate.registration_id)
        unique.append(candidate)

    if not unique:
        return LookupDecision(LookupOutcome.NO_MATCH, (), None, False)
    if len(unique) > MAX_LOOKUP_CANDIDATES:
        # No candidate payload at all: an enumerating client learns only that
        # the fragment is common, which it could have guessed.
        return LookupDecision(LookupOutcome.TOO_MANY, (), None, True)
    if len(unique) == 1:
        return LookupDecision(
            LookupOutcome.SINGLE_CANDIDATE, tuple(unique), unique[0].registration_id, False
        )
    return LookupDecision(LookupOutcome.AMBIGUOUS, tuple(unique), None, True)


def mask_name_initial(display_name: str) -> str:
    """Return the first character of a name and nothing else.

    Works for CJK family names (one character is the family name) and for Latin
    names (one character is an initial). An empty or whitespace-only name masks
    to ``"?"`` rather than to an empty string, so the operator sees a stable
    slot instead of a layout that shifts between candidates.
    """

    cleaned = (display_name or "").strip()
    if not cleaned:
        return "?"
    return cleaned[0] + "*"


def registration_number_suffix(registration_number: str, *, length: int = 4) -> str:
    """Tail of the registration number, which the member is holding on screen.

    Only the tail: a full registration number is an addressable identifier that
    other endpoints accept, so echoing it into a pre-authentication lookup
    response would hand an attacker a working handle.
    """

    if length < 2 or length > 6:
        raise CheckinRuleError(
            "CHECKIN_SUFFIX_LENGTH_INVALID",
            "Registration-number suffix length must be between 2 and 6.",
            details={"length": length},
        )
    cleaned = (registration_number or "").strip()
    if not cleaned:
        return "?" * length
    return cleaned[-length:]


def choice_token(*, lookup_id: UUID, registration_id: UUID, issued_at: datetime, key: bytes) -> str:
    """Opaque, unguessable handle for one candidate inside one lookup.

    The token is an HMAC, not an encoding: there is no registration id inside it
    to extract. The service resolves it by recomputing the token for each
    candidate of the stored lookup row and comparing in constant time, so a
    token is useless outside the lookup it was minted for, and useless after
    that lookup expires.
    """

    _require_aware(issued_at, "issued_at")
    if not key:
        raise CheckinRuleError(
            "CHECKIN_TOKEN_KEY_MISSING", "A signing key is required to mint a choice token."
        )
    message = f"choice|{lookup_id}|{registration_id}|{int(issued_at.timestamp())}"
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()[:32]


def match_choice_token(
    token: str,
    candidates: Sequence[LookupCandidate],
    *,
    lookup_id: UUID,
    issued_at: datetime,
    key: bytes,
) -> LookupCandidate:
    """Resolve a choice token back to its candidate, in constant time."""

    supplied = (token or "").strip()
    if not supplied:
        raise CheckinRuleError("CHECKIN_CHOICE_TOKEN_REQUIRED", "A choice token is required.")
    matched: LookupCandidate | None = None
    for candidate in candidates:
        expected = choice_token(
            lookup_id=lookup_id,
            registration_id=candidate.registration_id,
            issued_at=issued_at,
            key=key,
        )
        # No early break: every candidate is compared so the loop's duration
        # does not reveal the position of the match.
        if hmac.compare_digest(expected, supplied):
            matched = candidate
    if matched is None:
        raise CheckinRuleError(
            "CHECKIN_CHOICE_TOKEN_INVALID",
            "That choice is not valid for this lookup; search again.",
        )
    return matched


def is_lookup_expired(issued_at: datetime, *, now: datetime, ttl_seconds: int) -> bool:
    """A lookup result set is short-lived; stale choices are not honoured."""

    _require_aware(issued_at, "issued_at")
    _require_aware(now, "now")
    if ttl_seconds <= 0:
        raise CheckinRuleError(
            "CHECKIN_TTL_INVALID", "Lookup TTL must be positive.", details={"ttl": ttl_seconds}
        )
    return now >= issued_at + timedelta(seconds=ttl_seconds)


#: Keys that must never appear in a candidate payload. Enforced rather than
#: documented, because "we always remember to strip it" is not a control.
FORBIDDEN_CANDIDATE_KEYS: frozenset[str] = frozenset(
    {
        "user_id",
        "registration_id",
        "display_name",
        "full_name",
        "phone",
        "phone_number",
        "value_hmac",
        "last_four_hmac",
        "email",
        "registration_number",
        "id_card",
        "form_response_encrypted",
    }
)


def candidate_choice_payload(
    candidate: LookupCandidate,
    *,
    token: str,
    suffix_length: int = 4,
) -> dict[str, object]:
    """Everything the operator screen may show about one ambiguous candidate.

    A masked initial plus a registration-number suffix is enough for a human
    standing in front of another human to disambiguate ("is your family name
    Zhang? does your ticket end 4417?"), and is not enough for anyone else to
    learn who is on the guest list.
    """

    return {
        "choice_token": token,
        "name_initial": mask_name_initial(candidate.display_name),
        "registration_suffix": registration_number_suffix(
            candidate.registration_number, length=suffix_length
        ),
        "ticket_label": candidate.ticket_label,
        "attendance_status": candidate.attendance_status,
    }


def ensure_choice_payload_safe(payload: Mapping[str, object]) -> None:
    """Guard against a future edit re-introducing personal data into a lookup.

    Checks structure, not intent: forbidden keys, anything that looks like a run
    of six or more digits (a phone fragment or a whole registration number), and
    any name field longer than a masked initial.
    """

    for key in payload:
        if key in FORBIDDEN_CANDIDATE_KEYS:
            raise CheckinRuleError(
                "CHECKIN_CANDIDATE_PAYLOAD_UNSAFE",
                f"Candidate payloads must not carry {key}.",
                details={"key": key},
            )
    for key, value in payload.items():
        if not isinstance(value, str):
            continue
        digits = "".join(char for char in value if char.isdigit())
        if key != "choice_token" and len(digits) >= 6:
            raise CheckinRuleError(
                "CHECKIN_CANDIDATE_PAYLOAD_UNSAFE",
                f"Candidate field {key} carries too many digits to be a masked value.",
                details={"key": key, "digits": len(digits)},
            )
        if key == "name_initial" and len(value) > 2:
            raise CheckinRuleError(
                "CHECKIN_CANDIDATE_PAYLOAD_UNSAFE",
                "name_initial must be a masked initial, not a name.",
                details={"length": len(value)},
            )


def build_lookup_response(
    decision: LookupDecision,
    *,
    lookup_id: UUID,
    issued_at: datetime,
    key: bytes,
    suffix_length: int = 4,
) -> dict[str, object]:
    """Assemble the whole operator-facing lookup response, safely.

    ``SINGLE_CANDIDATE`` still returns a choice token rather than a
    registration id: the confirm step is the same code path whether or not the
    search happened to be unambiguous, so there is no "fast path" that skips
    the human confirmation.
    """

    items: list[dict[str, object]] = []
    for candidate in decision.candidates:
        payload = candidate_choice_payload(
            candidate,
            token=choice_token(
                lookup_id=lookup_id,
                registration_id=candidate.registration_id,
                issued_at=issued_at,
                key=key,
            ),
            suffix_length=suffix_length,
        )
        ensure_choice_payload_safe(payload)
        items.append(payload)
    return {
        "lookup_id": str(lookup_id),
        "outcome": decision.outcome.value,
        "requires_discriminator": decision.requires_discriminator,
        "candidate_count": len(items),
        "candidates": items,
    }


# ---------------------------------------------------------------------------
# CHK-002 - the confirm step (misoperation resistance)
# ---------------------------------------------------------------------------


def confirmation_token(
    *,
    lookup_id: UUID,
    registration_id: UUID,
    operator_id: UUID,
    issued_at: datetime,
    key: bytes,
) -> str:
    """Mint the short-lived token that the confirm button carries.

    Bound to the operator as well as to the registration: a token torn off one
    device cannot be replayed from another, which is the realistic onsite
    failure (a shared tablet left unlocked), not a cryptographic attack.
    """

    _require_aware(issued_at, "issued_at")
    if not key:
        raise CheckinRuleError(
            "CHECKIN_TOKEN_KEY_MISSING", "A signing key is required to mint a confirmation token."
        )
    message = f"confirm|{lookup_id}|{registration_id}|{operator_id}|{int(issued_at.timestamp())}"
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()[:32]


def verify_confirmation_token(
    token: str,
    *,
    lookup_id: UUID,
    registration_id: UUID,
    operator_id: UUID,
    issued_at: datetime,
    now: datetime,
    ttl_seconds: int,
    key: bytes,
) -> None:
    """Reject a confirmation that is forged, replayed from another operator, or stale."""

    _require_aware(now, "now")
    expected = confirmation_token(
        lookup_id=lookup_id,
        registration_id=registration_id,
        operator_id=operator_id,
        issued_at=issued_at,
        key=key,
    )
    if not hmac.compare_digest(expected, (token or "").strip()):
        raise CheckinRuleError(
            "CHECKIN_CONFIRMATION_INVALID",
            "This confirmation does not match the pending check-in; scan again.",
        )
    if is_lookup_expired(issued_at, now=now, ttl_seconds=ttl_seconds):
        raise CheckinRuleError(
            "CHECKIN_CONFIRMATION_EXPIRED",
            "This confirmation expired; scan again.",
            details={"ttl_seconds": ttl_seconds},
        )


# ---------------------------------------------------------------------------
# CHK-002 - scan decisions (idempotency)
# ---------------------------------------------------------------------------


class ScanOutcome(StrEnum):
    CHECKED_IN = "checked_in"
    #: A repeat scan of somebody already checked in. A **success**, not an
    #: error: the queue does not stop because a phone re-fired a QR code.
    DUPLICATE_NOOP = "duplicate_noop"
    #: Somebody whose check-in an operator revoked earlier is scanning again.
    #: Allowed, but recorded with its own action so the revoke/re-admit pair is
    #: visible in the audit trail.
    REINSTATED = "reinstated"


@dataclass(frozen=True)
class ScanDecision:
    outcome: ScanOutcome
    #: False for a duplicate: the row is already in the target state, so the
    #: service must not write, must not bump ``version``, and must not emit a
    #: second check-in event.
    writes_attendance: bool
    effective_checked_in_at: datetime
    audit_action: str
    message_code: str


def decide_scan(
    *,
    registration_status: str,
    attendance_status: str,
    checked_in_at: datetime | None,
    now: datetime,
) -> ScanDecision:
    """Decide what a scan of this registration means, idempotently.

    Rules, in order:

    1. Only a ``confirmed`` registration can be checked in. Terminal statuses
       (cancelled/rejected/expired) and payment-pending statuses get distinct
       codes so the operator knows whether to send the member to the desk or to
       a payment link.
    2. Already checked in: return success with the **original** timestamp. This
       is the rule the requirement calls out - a duplicate scan is a no-op
       success. Returning 409 here trains operators to ignore red screens.
    3. Previously revoked: allowed, flagged as a reinstatement.
    4. Otherwise: a fresh check-in at ``now``.
    """

    _require_aware(now, "now")
    if registration_status in TERMINAL_REGISTRATION_STATUSES:
        raise CheckinRuleError(
            "CHECKIN_REGISTRATION_NOT_ACTIVE",
            f"Registration is {registration_status} and cannot be checked in.",
            details={"registration_status": registration_status},
        )
    if registration_status not in CHECKIN_ELIGIBLE_REGISTRATION_STATUSES:
        raise CheckinRuleError(
            "CHECKIN_REGISTRATION_NOT_CONFIRMED",
            f"Registration is {registration_status}; only a confirmed registration checks in.",
            details={"registration_status": registration_status},
        )

    if attendance_status == AttendanceStatus.CHECKED_IN:
        if checked_in_at is None:
            # Defensive: the pair is inconsistent, so treat the scan as the
            # authoritative moment rather than inventing a past timestamp.
            return ScanDecision(
                ScanOutcome.DUPLICATE_NOOP, False, now, "duplicate_scan", "CHECKIN_ALREADY_DONE"
            )
        return ScanDecision(
            ScanOutcome.DUPLICATE_NOOP,
            False,
            _require_aware(checked_in_at, "checked_in_at"),
            "duplicate_scan",
            "CHECKIN_ALREADY_DONE",
        )
    if attendance_status == AttendanceStatus.CHECKIN_REVOKED:
        return ScanDecision(ScanOutcome.REINSTATED, True, now, "reinstate", "CHECKIN_REINSTATED")
    if attendance_status in (AttendanceStatus.NOT_CHECKED_IN, AttendanceStatus.NO_SHOW):
        return ScanDecision(ScanOutcome.CHECKED_IN, True, now, "check_in", "CHECKIN_RECORDED")
    raise CheckinRuleError(
        "CHECKIN_ATTENDANCE_STATUS_UNKNOWN",
        f"Unknown attendance status: {attendance_status}.",
        details={"attendance_status": attendance_status},
    )


def scan_dedupe_key(*, registration_id: UUID, device_reference: str, request_id: str) -> str:
    """Stable key for at-most-once processing of a retried scan.

    A scanner that loses its response and retries sends the same request id; the
    service stores this key uniquely so the retry lands on the existing event
    instead of writing a second one.
    """

    reference = (device_reference or "unknown-device").strip()
    request = (request_id or "").strip()
    if not request:
        raise CheckinRuleError(
            "CHECKIN_REQUEST_ID_REQUIRED", "A request id is required to de-duplicate a scan."
        )
    return f"{registration_id}:{reference}:{request}"


# ---------------------------------------------------------------------------
# CHK-002 - undo window
# ---------------------------------------------------------------------------


def require_reason(reason: str | None, *, code: str, minimum_length: int = 4) -> str:
    """An override or an undo is an administrative act and must be explained."""

    cleaned = (reason or "").strip()
    if len(cleaned) < minimum_length:
        raise CheckinRuleError(
            code,
            f"A written reason of at least {minimum_length} characters is required.",
            details={"minimum_length": minimum_length},
        )
    return cleaned


def ensure_undo_allowed(
    *,
    attendance_status: str,
    checked_in_at: datetime | None,
    now: datetime,
    undo_window_minutes: int,
    reason: str | None,
) -> str:
    """Guard the undo path and return the cleaned reason.

    The window exists because an undo hours later is not a mis-tap correction,
    it is a change to the attendance record that post-event candidate freezing
    depends on; that goes through the audited revoke path with its own
    permission, not through the operator's undo button.
    """

    _require_aware(now, "now")
    if undo_window_minutes <= 0:
        raise CheckinRuleError(
            "CHECKIN_UNDO_DISABLED",
            "The undo window is disabled for this deployment.",
            details={"undo_window_minutes": undo_window_minutes},
        )
    if attendance_status != AttendanceStatus.CHECKED_IN or checked_in_at is None:
        raise CheckinRuleError(
            "CHECKIN_UNDO_NOT_CHECKED_IN",
            "There is no check-in to undo.",
            details={"attendance_status": attendance_status},
        )
    cleaned = require_reason(reason, code="CHECKIN_UNDO_REASON_REQUIRED")
    deadline = _require_aware(checked_in_at, "checked_in_at") + timedelta(
        minutes=undo_window_minutes
    )
    if now > deadline:
        raise CheckinRuleError(
            "CHECKIN_UNDO_WINDOW_EXPIRED",
            "The undo window has passed; use the audited revoke path instead.",
            details={"undo_window_minutes": undo_window_minutes, "deadline": deadline.isoformat()},
        )
    return cleaned


# ---------------------------------------------------------------------------
# CHK-002 - per-operator rate limiting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    observed: int
    remaining: int
    retry_after_seconds: int


def evaluate_rate_limit(
    recent_events: Iterable[datetime],
    *,
    now: datetime,
    window_seconds: int,
    max_events: int,
) -> RateLimitDecision:
    """Sliding-window limit on one operator's scans.

    The threat is not an attacker, it is a barcode scanner wedged against a
    lanyard firing hundreds of reads a minute, or a queue app retrying in a
    tight loop. Both look identical from the server, and both are stopped the
    same way. Because :func:`decide_scan` makes repeats idempotent, hitting this
    limit costs the operator nothing but a moment.
    """

    _require_aware(now, "now")
    if window_seconds <= 0 or max_events <= 0:
        raise CheckinRuleError(
            "CHECKIN_RATE_LIMIT_CONFIG_INVALID",
            "Rate-limit window and maximum must both be positive.",
            details={"window_seconds": window_seconds, "max_events": max_events},
        )
    window_start = now - timedelta(seconds=window_seconds)
    in_window = sorted(
        _require_aware(event, "recent_event")
        for event in recent_events
        if _require_aware(event, "recent_event") > window_start
    )
    observed = len(in_window)
    if observed < max_events:
        return RateLimitDecision(True, observed, max_events - observed, 0)
    # The limit frees up when the oldest event in the window falls out of it.
    oldest = in_window[0]
    retry_after = max(
        1, math.ceil((oldest + timedelta(seconds=window_seconds) - now).total_seconds())
    )
    return RateLimitDecision(False, observed, 0, retry_after)


# ---------------------------------------------------------------------------
# CHK-002 - check-in window policy and override
# ---------------------------------------------------------------------------


class WindowState(StrEnum):
    TOO_EARLY = "too_early"
    EARLY_GRACE = "early_grace"
    IN_WINDOW = "in_window"
    LATE_GRACE = "late_grace"
    TOO_LATE = "too_late"


#: The two states that need an override permission plus a reason.
OUT_OF_WINDOW_STATES: frozenset[WindowState] = frozenset(
    {WindowState.TOO_EARLY, WindowState.TOO_LATE}
)


@dataclass(frozen=True)
class WindowPolicy:
    """Configured grace either side of the session (from ``get_settings()``)."""

    early_minutes: int = 60
    late_minutes: int = 30

    def __post_init__(self) -> None:
        if self.early_minutes < 0 or self.late_minutes < 0:
            raise CheckinRuleError(
                "CHECKIN_WINDOW_POLICY_INVALID",
                "Window grace minutes cannot be negative.",
                details={"early": self.early_minutes, "late": self.late_minutes},
            )


def classify_checkin_window(
    *,
    now: datetime,
    session_start_at: datetime,
    session_end_at: datetime,
    policy: WindowPolicy,
) -> WindowState:
    """Place ``now`` relative to the session and its configured grace."""

    _require_aware(now, "now")
    _require_aware(session_start_at, "session_start_at")
    _require_aware(session_end_at, "session_end_at")
    if session_end_at <= session_start_at:
        raise CheckinRuleError(
            "CHECKIN_SESSION_WINDOW_INVALID",
            "Session end must be after session start.",
            details={"start": session_start_at.isoformat(), "end": session_end_at.isoformat()},
        )
    if session_start_at <= now <= session_end_at:
        return WindowState.IN_WINDOW
    if now < session_start_at:
        if now >= session_start_at - timedelta(minutes=policy.early_minutes):
            return WindowState.EARLY_GRACE
        return WindowState.TOO_EARLY
    if now <= session_end_at + timedelta(minutes=policy.late_minutes):
        return WindowState.LATE_GRACE
    return WindowState.TOO_LATE


@dataclass(frozen=True)
class WindowDecision:
    state: WindowState
    requires_override: bool
    override_used: bool
    override_reason: str | None


def ensure_checkin_window(
    state: WindowState,
    *,
    has_override_permission: bool,
    override_reason: str | None = None,
) -> WindowDecision:
    """Enforce the out-of-window policy.

    Inside the window or its configured grace, nothing is required. Outside it,
    **both** an override permission and a written reason are required - the
    permission alone is not enough, because "the operator had the permission"
    is not an answer to "why was this person admitted 90 minutes late". The
    returned decision is what the service writes to the audit row.
    """

    if state not in OUT_OF_WINDOW_STATES:
        return WindowDecision(state, False, False, None)
    if not has_override_permission:
        code = (
            "CHECKIN_WINDOW_TOO_EARLY"
            if state is WindowState.TOO_EARLY
            else "CHECKIN_WINDOW_TOO_LATE"
        )
        raise CheckinRuleError(
            code,
            "Check-in is outside the permitted window; an override permission is required.",
            details={"state": state.value},
        )
    reason = require_reason(override_reason, code="CHECKIN_OVERRIDE_REASON_REQUIRED")
    return WindowDecision(state, True, True, reason)


# ---------------------------------------------------------------------------
# CHK-002 - audit payloads
# ---------------------------------------------------------------------------


def build_audit_metadata(
    *,
    outcome: ScanOutcome,
    window: WindowDecision,
    method: str,
    device_reference: str,
    lookup_last_four_masked: str | None = None,
) -> dict[str, object]:
    """Metadata for one check-in event, with nothing identifying in it.

    Note what is absent: no phone digits (only the already-masked bullet form),
    no name, no registration number. An audit row is read by more people than a
    registration row is, so it carries the least data that still answers "what
    happened and why".
    """

    metadata: dict[str, object] = {
        "outcome": outcome.value,
        "method": method,
        "device_reference": (device_reference or "unknown-device").strip(),
        "window_state": window.state.value,
        "override_used": window.override_used,
    }
    if window.override_reason:
        metadata["override_reason"] = window.override_reason
    if lookup_last_four_masked:
        if any(char.isdigit() for char in lookup_last_four_masked[:-LAST_FOUR_LENGTH]):
            raise CheckinRuleError(
                "CHECKIN_AUDIT_METADATA_UNSAFE",
                "Audit metadata may only carry the masked last-four form.",
            )
        metadata["searched_fragment"] = lookup_last_four_masked
    return metadata
