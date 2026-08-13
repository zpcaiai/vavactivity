"""Pure attendee-preview and social-graph rules (B14).

No database, network, settings or clock access lives here: every rule takes the
state it needs as an argument (including ``now``), so the safe defaults below
are unit-testable without PostgreSQL.

Requirement coverage:

* ATT-001 attendee preview on the event detail page. Per DEC-002 the safe
  default is **opt-in**: a member who has never answered is not shown. Only
  confirmed, paid-or-eligible, explicitly consented, non-staff registrations
  appear, and only a minimum-field projection is ever serialized.
* SOC-001 a follow graph that is explicitly *not* like and *not* want-to-meet.
  The three relations keep separate storage and separate meaning, and the
  ``followed_user_registered`` notification respects blocks, notification
  preferences and an idempotent delivery key.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

# ---------------------------------------------------------------------------
# Shared errors
# ---------------------------------------------------------------------------


class AttendeeSocialRuleError(Exception):
    """Raised when a caller violates an attendee-preview or follow-graph rule.

    ``code`` is the stable machine identifier clients switch on; ``message`` is
    operator-facing English. Member-facing copy is localized in the frontend
    from ``code``.
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


# ---------------------------------------------------------------------------
# ATT-001 - eligibility for the attendee preview
# ---------------------------------------------------------------------------


class PreviewConsentState(StrEnum):
    """Whether a member agreed to appear in the public attendee preview.

    DEC-002 makes this opt-in. :attr:`NOT_ASKED` - the state of every member who
    has never seen the prompt, and therefore the state of every historical
    registration - must behave exactly like a refusal. Anything else would turn
    a migration into a mass disclosure of who is attending a dating event.
    """

    NOT_ASKED = "not_asked"
    GRANTED = "granted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


#: The safe default for a registration with no consent record at all.
DEFAULT_PREVIEW_CONSENT_STATE = PreviewConsentState.NOT_ASKED

#: The only consent state that permits public display (ATT-001 / DEC-002).
CONSENTED_PREVIEW_STATES: frozenset[PreviewConsentState] = frozenset({PreviewConsentState.GRANTED})


class PaymentState(StrEnum):
    PAID = "paid"
    #: A free event, or a comp/invite where no payment is expected. Treated as
    #: settled: "paid or eligible" in ATT-001 means "owes nothing".
    NOT_REQUIRED = "not_required"
    UNPAID = "unpaid"
    PENDING = "pending"
    REFUNDED = "refunded"
    FAILED = "failed"


#: Payment states that satisfy "paid / eligible".
SETTLED_PAYMENT_STATES: frozenset[PaymentState] = frozenset(
    {PaymentState.PAID, PaymentState.NOT_REQUIRED}
)

#: Mirrors ``vav.modules.activities.domain.RegistrationStatus``: only
#: ``confirmed`` counts. Waitlisted, pending-payment, cancelled, rejected and
#: expired registrations are not attendees.
CONFIRMED_REGISTRATION_STATUSES: frozenset[str] = frozenset({"confirmed"})

#: Attendance states meaning the person did not actually turn up. Mirrors
#: ``vav.modules.activities.domain.AttendanceStatus``. Attendance is a separate
#: column from registration status, so both are consulted.
ABSENT_ATTENDANCE_STATUSES: frozenset[str] = frozenset({"no_show", "checkin_revoked"})


class PreviewExclusionReason(StrEnum):
    """Why a registration is not shown. Recorded for operator diagnostics only:
    the member-facing API returns a count, never a reason per person."""

    STAFF = "staff"
    NOT_CONFIRMED = "not_confirmed"
    NOT_SETTLED = "not_settled"
    NO_CONSENT = "no_consent"
    CONSENT_WITHDRAWN = "consent_withdrawn"
    ABSENT = "absent"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class AttendeeRecord:
    """One registration considered for the event-detail attendee preview."""

    user_id: UUID
    registration_id: UUID
    registration_status: str
    payment_state: str
    consent_state: str = DEFAULT_PREVIEW_CONSENT_STATE.value
    attendance_status: str = "not_checked_in"
    is_staff: bool = False
    is_suspended: bool = False
    display_name: str = ""
    avatar_url: str | None = None
    intro_line: str | None = None


@dataclass(frozen=True)
class PreviewDecision:
    user_id: UUID
    registration_id: UUID
    visible: bool
    exclusion_reason: PreviewExclusionReason | None


def evaluate_preview_visibility(
    record: AttendeeRecord, *, exclude_absent: bool = False
) -> PreviewDecision:
    """Decide whether one registration may appear in the public preview.

    Rules, in priority order:

    1. Staff and operator registrations never appear - the preview is about
       who a member will meet, not who is working.
    2. The registration must be ``confirmed``.
    3. Money must be settled (paid, or nothing owed).
    4. Consent must be an explicit, current ``granted``. ``not_asked``,
       ``declined`` and ``withdrawn`` all fail closed (DEC-002).
    5. A suspended account is hidden regardless of consent.

    ``exclude_absent`` is off by default because the preview is normally read
    *before* the event, when everybody is legitimately ``not_checked_in``. A
    post-event surface passes ``True`` to drop no-shows and revoked check-ins.
    """

    reason: PreviewExclusionReason | None = None
    if record.is_staff:
        reason = PreviewExclusionReason.STAFF
    elif record.registration_status not in CONFIRMED_REGISTRATION_STATUSES:
        reason = PreviewExclusionReason.NOT_CONFIRMED
    elif record.payment_state not in {state.value for state in SETTLED_PAYMENT_STATES}:
        reason = PreviewExclusionReason.NOT_SETTLED
    elif record.consent_state == PreviewConsentState.WITHDRAWN.value:
        reason = PreviewExclusionReason.CONSENT_WITHDRAWN
    elif record.consent_state not in {state.value for state in CONSENTED_PREVIEW_STATES}:
        reason = PreviewExclusionReason.NO_CONSENT
    elif record.is_suspended:
        reason = PreviewExclusionReason.SUSPENDED
    elif exclude_absent and record.attendance_status in ABSENT_ATTENDANCE_STATUSES:
        reason = PreviewExclusionReason.ABSENT
    return PreviewDecision(
        user_id=record.user_id,
        registration_id=record.registration_id,
        visible=reason is None,
        exclusion_reason=reason,
    )


def is_preview_visible(record: AttendeeRecord, *, exclude_absent: bool = False) -> bool:
    return evaluate_preview_visibility(record, exclude_absent=exclude_absent).visible


# ---------------------------------------------------------------------------
# ATT-001 - minimum-field projection
# ---------------------------------------------------------------------------

#: The complete set of fields the preview may serialize. ATT-001 is explicit
#: that nothing else - age, gender, MBTI, occupation, WeChat id, registration
#: id, payment state - may reach the client, even "hidden" behind a flag.
PREVIEW_PROJECTION_FIELDS: frozenset[str] = frozenset(
    {"user_id", "display_name", "avatar_url", "intro_line"}
)

#: Longest one-line intro rendered in the preview. Anything longer is truncated
#: rather than rejected, because the member wrote it for a different surface.
INTRO_LINE_MAX_LENGTH = 60

#: Shown instead of an empty name so the card never renders blank.
DISPLAY_NAME_FALLBACK_PREFIX = "member-"


def preview_display_name(record: AttendeeRecord) -> str:
    """Never return an empty name; fall back to a stable pseudonymous handle."""

    name = (record.display_name or "").strip()
    if name:
        return name[:64]
    return f"{DISPLAY_NAME_FALLBACK_PREFIX}{str(record.user_id)[:8]}"


def project_attendee(record: AttendeeRecord, *, include_intro: bool = True) -> dict[str, object]:
    """Serialize one visible attendee using the minimum-field projection.

    Built by explicit construction rather than by filtering a wider dict, so a
    new column on :class:`AttendeeRecord` cannot leak by default.
    """

    intro = (record.intro_line or "").strip() if include_intro else ""
    return {
        "user_id": str(record.user_id),
        "display_name": preview_display_name(record),
        "avatar_url": (record.avatar_url or "").strip() or None,
        "intro_line": intro[:INTRO_LINE_MAX_LENGTH] if intro else None,
    }


def assert_minimum_projection(payload: Mapping[str, object]) -> None:
    """Fail if a preview payload carries anything beyond the allowed fields."""

    extra = sorted(set(payload) - PREVIEW_PROJECTION_FIELDS)
    if extra:
        raise AttendeeSocialRuleError(
            "PREVIEW_PROJECTION_LEAK",
            "The attendee preview may only expose the minimum field set.",
            details={"fields": extra},
        )


#: Default number of faces rendered on the event detail page.
DEFAULT_PREVIEW_LIMIT = 12
MAX_PREVIEW_LIMIT = 50


@dataclass(frozen=True)
class PreviewSummary:
    items: tuple[dict[str, object], ...]
    #: Consented attendees beyond ``limit``. Safe to publish: it only counts
    #: people who already agreed to be visible.
    additional_visible_count: int
    #: Confirmed attendees who did not consent. Deliberately *not* returned to
    #: members - exposing it would let anyone infer the non-consenting headcount
    #: for a small event.
    withheld_count: int
    total_considered: int


def build_preview(
    records: Iterable[AttendeeRecord],
    *,
    limit: int = DEFAULT_PREVIEW_LIMIT,
    exclude_absent: bool = False,
    include_intro: bool = True,
) -> PreviewSummary:
    """Build the whole preview payload from raw registration records.

    Ordering is by display name then user id, so the same input always produces
    the same page and pagination cannot show a duplicate.
    """

    if not 1 <= limit <= MAX_PREVIEW_LIMIT:
        raise AttendeeSocialRuleError(
            "PREVIEW_LIMIT_INVALID",
            f"The preview limit must be between 1 and {MAX_PREVIEW_LIMIT}.",
            details={"limit": limit},
        )
    materialized = list(records)
    visible: list[AttendeeRecord] = []
    withheld = 0
    for record in materialized:
        decision = evaluate_preview_visibility(record, exclude_absent=exclude_absent)
        if decision.visible:
            visible.append(record)
        elif decision.exclusion_reason in (
            PreviewExclusionReason.NO_CONSENT,
            PreviewExclusionReason.CONSENT_WITHDRAWN,
        ):
            withheld += 1
    visible.sort(key=lambda item: (preview_display_name(item), str(item.user_id)))
    shown = visible[:limit]
    return PreviewSummary(
        items=tuple(project_attendee(item, include_intro=include_intro) for item in shown),
        additional_visible_count=max(0, len(visible) - len(shown)),
        withheld_count=withheld,
        total_considered=len(materialized),
    )


# ---------------------------------------------------------------------------
# ATT-001 - consent lifecycle
# ---------------------------------------------------------------------------

_CONSENT_TRANSITIONS: dict[PreviewConsentState, frozenset[PreviewConsentState]] = {
    PreviewConsentState.NOT_ASKED: frozenset(
        {PreviewConsentState.GRANTED, PreviewConsentState.DECLINED}
    ),
    PreviewConsentState.DECLINED: frozenset({PreviewConsentState.GRANTED}),
    PreviewConsentState.GRANTED: frozenset({PreviewConsentState.WITHDRAWN}),
    # Withdrawal is reversible: a member may change their mind and opt in again.
    PreviewConsentState.WITHDRAWN: frozenset({PreviewConsentState.GRANTED}),
}


def validate_consent_transition(current: str, target: str) -> None:
    """Guard the consent state machine.

    Notably there is no ``granted -> declined`` edge: once consent has been
    given, taking it back is a *withdrawal*, which is a distinct, audited event
    (ATT-001) rather than a silent revision of the original answer.
    """

    try:
        current_state = PreviewConsentState(current)
        target_state = PreviewConsentState(target)
    except ValueError as exc:
        raise AttendeeSocialRuleError(
            "CONSENT_STATE_UNKNOWN", f"Unknown preview consent state: {exc}"
        ) from exc
    if current_state == target_state:
        raise AttendeeSocialRuleError(
            "CONSENT_ALREADY_IN_STATE",
            "The consent record is already in that state.",
            details={"state": current_state.value},
        )
    if target_state not in _CONSENT_TRANSITIONS[current_state]:
        raise AttendeeSocialRuleError(
            "CONSENT_TRANSITION_INVALID",
            f"Cannot move preview consent from {current_state} to {target_state}.",
            details={"current": current_state.value, "target": target_state.value},
        )


@dataclass(frozen=True)
class ConsentChange:
    """The result of a consent decision: the new state plus its audit row."""

    state: PreviewConsentState
    granted_at: datetime | None
    withdrawn_at: datetime | None
    audit_action: str
    #: ``True`` when the change removes the member from future preview renders.
    removes_future_display: bool


def apply_consent_decision(
    *, current_state: str, target_state: str, now: datetime, source: str = "member"
) -> ConsentChange:
    """Apply a consent decision and describe what must be audited.

    Withdrawal removes *future* display only. Nothing retroactively edits a
    screenshot someone already took; what the platform controls is that the next
    render omits them, and that the withdrawal is written to the audit trail
    with a timestamp (ATT-001).
    """

    if now.tzinfo is None:
        raise AttendeeSocialRuleError("CONSENT_NAIVE_DATETIME", "now must be timezone-aware.")
    validate_consent_transition(current_state, target_state)
    state = PreviewConsentState(target_state)
    if state is PreviewConsentState.GRANTED:
        return ConsentChange(
            state=state,
            granted_at=now,
            withdrawn_at=None,
            audit_action=f"attendee_preview.consent.granted.{source}",
            removes_future_display=False,
        )
    if state is PreviewConsentState.WITHDRAWN:
        return ConsentChange(
            state=state,
            granted_at=None,
            withdrawn_at=now,
            audit_action=f"attendee_preview.consent.withdrawn.{source}",
            removes_future_display=True,
        )
    return ConsentChange(
        state=state,
        granted_at=None,
        withdrawn_at=None,
        audit_action=f"attendee_preview.consent.declined.{source}",
        removes_future_display=True,
    )


# ---------------------------------------------------------------------------
# SOC-001 - three distinct relations
# ---------------------------------------------------------------------------


class RelationKind(StrEnum):
    """The three member-to-member relations, kept deliberately separate.

    They are *not* interchangeable and must never be stored in one table with a
    ``kind`` column that code treats as cosmetic:

    * :attr:`LIKE` is the private, event-scoped mutual-selection signal owned by
      the post-event module. It is never visible to the other person unless it
      is reciprocated.
    * :attr:`FOLLOW` is a public, one-directional subscription to someone's
      activity. It says nothing about romantic interest and requires no
      reciprocity.
    * :attr:`WANT_TO_MEET` is an event-scoped intent expressed before an event.
      It is visible to operators for seating and grouping, not to the target.

    Conflating them would let a follow leak as a like, which is the single most
    damaging privacy failure this module can produce (SOC-001).
    """

    LIKE = "like"
    FOLLOW = "follow"
    WANT_TO_MEET = "want_to_meet"


@dataclass(frozen=True)
class RelationSemantics:
    kind: RelationKind
    table_name: str
    is_directional: bool
    #: Whether the *target* can see the relation exists without reciprocating.
    visible_to_target: bool
    requires_reciprocity_to_reveal: bool
    is_event_scoped: bool


RELATION_SEMANTICS: Mapping[RelationKind, RelationSemantics] = {
    RelationKind.LIKE: RelationSemantics(
        kind=RelationKind.LIKE,
        table_name="activity_selection_items",
        is_directional=True,
        visible_to_target=False,
        requires_reciprocity_to_reveal=True,
        is_event_scoped=True,
    ),
    RelationKind.FOLLOW: RelationSemantics(
        kind=RelationKind.FOLLOW,
        table_name="social_follows",
        is_directional=True,
        visible_to_target=True,
        requires_reciprocity_to_reveal=False,
        is_event_scoped=False,
    ),
    RelationKind.WANT_TO_MEET: RelationSemantics(
        kind=RelationKind.WANT_TO_MEET,
        table_name="social_want_to_meet",
        is_directional=True,
        visible_to_target=False,
        requires_reciprocity_to_reveal=False,
        is_event_scoped=True,
    ),
}


def relation_semantics(kind: RelationKind | str) -> RelationSemantics:
    try:
        return RELATION_SEMANTICS[RelationKind(kind)]
    except ValueError as exc:
        raise AttendeeSocialRuleError(
            "RELATION_KIND_UNKNOWN", f"Unknown relation kind: {kind}"
        ) from exc


def relation_implies(source: RelationKind | str, target: RelationKind | str) -> bool:
    """No relation ever implies another one.

    Written as a function rather than left implicit so that a future "just make
    following a like" shortcut has to delete a rule with a comment on it
    (SOC-001).
    """

    return RelationKind(source) is RelationKind(target)


# ---------------------------------------------------------------------------
# SOC-001 - follow graph
# ---------------------------------------------------------------------------


class FollowState(StrEnum):
    ACTIVE = "active"
    UNFOLLOWED = "unfollowed"
    #: Set when either side blocks; the edge is retained so an unblock can be
    #: distinguished from a fresh follow, but it never behaves as active.
    BLOCKED = "blocked"


class FollowAction(StrEnum):
    CREATED = "created"
    REACTIVATED = "reactivated"
    #: The edge is already active. A repeated follow is a no-op, not an error:
    #: mobile clients retry, and a 409 here would be noise.
    UNCHANGED = "unchanged"
    REMOVED = "removed"


@dataclass(frozen=True)
class FollowPlan:
    action: FollowAction
    state: FollowState
    #: ``True`` only for a genuinely new active edge, so counters and the
    #: "started following you" notification fire exactly once.
    should_notify_target: bool


#: A member may follow many people, but not without limit: an unbounded follow
#: list is the raw material for scraping the member directory.
MAX_FOLLOWING = 5000


def plan_follow(
    *,
    follower_id: UUID,
    followee_id: UUID,
    current_state: str | None,
    follower_blocks_followee: bool = False,
    followee_blocks_follower: bool = False,
    following_count: int = 0,
    max_following: int = MAX_FOLLOWING,
) -> FollowPlan:
    """Decide what a follow request does, without touching the database.

    Blocks are checked in both directions and produce the *same* error code, so
    the caller cannot distinguish "they blocked me" from "I blocked them" and
    thereby probe a block list.
    """

    if follower_id == followee_id:
        raise AttendeeSocialRuleError(
            "FOLLOW_SELF_NOT_ALLOWED", "A member cannot follow themselves."
        )
    if follower_blocks_followee or followee_blocks_follower:
        raise AttendeeSocialRuleError("FOLLOW_BLOCKED", "This member cannot be followed.")
    if current_state == FollowState.ACTIVE.value:
        return FollowPlan(
            action=FollowAction.UNCHANGED,
            state=FollowState.ACTIVE,
            should_notify_target=False,
        )
    if following_count >= max_following:
        raise AttendeeSocialRuleError(
            "FOLLOW_LIMIT_REACHED",
            f"A member may follow at most {max_following} people.",
            details={"max_following": max_following},
        )
    if current_state is None:
        return FollowPlan(
            action=FollowAction.CREATED, state=FollowState.ACTIVE, should_notify_target=True
        )
    return FollowPlan(
        action=FollowAction.REACTIVATED,
        state=FollowState.ACTIVE,
        # A re-follow after an unfollow does not re-notify: otherwise unfollow
        # plus follow becomes a way to repeatedly ping someone.
        should_notify_target=False,
    )


def plan_unfollow(*, current_state: str | None) -> FollowPlan:
    """Unfollowing is idempotent: removing a non-existent edge is not an error."""

    if current_state != FollowState.ACTIVE.value:
        return FollowPlan(
            action=FollowAction.UNCHANGED,
            state=FollowState(current_state) if current_state else FollowState.UNFOLLOWED,
            should_notify_target=False,
        )
    return FollowPlan(
        action=FollowAction.REMOVED,
        state=FollowState.UNFOLLOWED,
        should_notify_target=False,
    )


def apply_block_to_follows(
    *, blocker_id: UUID, blocked_id: UUID, edges: Sequence[tuple[UUID, UUID, str]]
) -> list[tuple[UUID, UUID]]:
    """Return the follow edges a new block must deactivate.

    A block severs the relationship in *both* directions. Leaving the blocked
    party following the blocker would keep feeding them the blocker's activity,
    which is precisely what the block is meant to stop.
    """

    pair = {(blocker_id, blocked_id), (blocked_id, blocker_id)}
    return [
        (follower, followee)
        for follower, followee, state in edges
        if (follower, followee) in pair and state == FollowState.ACTIVE.value
    ]


# ---------------------------------------------------------------------------
# SOC-001 - followed_user_registered notification
# ---------------------------------------------------------------------------

#: Topic and preference key for "someone you follow signed up for an event".
FOLLOWED_USER_REGISTERED_TOPIC = "social.followed_user_registered.v1"
FOLLOWED_USER_REGISTERED_PREFERENCE_KEY = "followed_user_registered"


class NotificationSuppression(StrEnum):
    NONE = "none"
    BLOCKED = "blocked"
    PREFERENCE_OFF = "preference_off"
    NOT_FOLLOWING = "not_following"
    SELF = "self"
    #: The followed member's registration is not public, so telling a follower
    #: about it would leak it (ATT-001 consent applies here too).
    REGISTRATION_NOT_VISIBLE = "registration_not_visible"
    EVENT_NOT_PUBLIC = "event_not_public"
    ALREADY_DELIVERED = "already_delivered"


@dataclass(frozen=True)
class NotificationDecision:
    should_send: bool
    suppression: NotificationSuppression
    dedupe_key: str | None


def followed_user_registered_dedupe_key(
    *, recipient_id: UUID, actor_id: UUID, activity_id: UUID
) -> str:
    """Stable delivery key so a retried fan-out job cannot double-send.

    Scoped to the (recipient, actor, activity) triple rather than to a job run,
    because the same registration may be picked up by a backfill, a retry and a
    real-time event and must still produce exactly one notification.
    """

    return f"social.followed_user_registered:{recipient_id}:{actor_id}:{activity_id}"


def decide_followed_user_registered(
    *,
    recipient_id: UUID,
    actor_id: UUID,
    activity_id: UUID,
    follow_state: str | None,
    blocked_either_way: bool,
    preference_enabled: bool,
    actor_registration_is_public: bool,
    event_is_public: bool,
    already_delivered: bool = False,
) -> NotificationDecision:
    """Decide whether to notify one follower that someone they follow signed up.

    Every suppression path returns a reason rather than raising, because this
    runs inside a fan-out loop where one ineligible recipient must not abort the
    batch. The checks are ordered cheapest-and-most-absolute first.
    """

    if recipient_id == actor_id:
        return NotificationDecision(False, NotificationSuppression.SELF, None)
    if blocked_either_way:
        return NotificationDecision(False, NotificationSuppression.BLOCKED, None)
    if follow_state != FollowState.ACTIVE.value:
        return NotificationDecision(False, NotificationSuppression.NOT_FOLLOWING, None)
    if not preference_enabled:
        return NotificationDecision(False, NotificationSuppression.PREFERENCE_OFF, None)
    if not event_is_public:
        return NotificationDecision(False, NotificationSuppression.EVENT_NOT_PUBLIC, None)
    if not actor_registration_is_public:
        return NotificationDecision(False, NotificationSuppression.REGISTRATION_NOT_VISIBLE, None)
    key = followed_user_registered_dedupe_key(
        recipient_id=recipient_id, actor_id=actor_id, activity_id=activity_id
    )
    if already_delivered:
        return NotificationDecision(False, NotificationSuppression.ALREADY_DELIVERED, key)
    return NotificationDecision(True, NotificationSuppression.NONE, key)


def build_followed_user_registered_payload(
    *,
    recipient_id: UUID,
    actor_id: UUID,
    activity_id: UUID,
    occurred_at: datetime,
) -> dict[str, object]:
    """The outbox payload. Codes only - no Chinese copy, no profile fields.

    The consumer resolves display names at render time so a name change (or a
    consent withdrawal) between enqueue and delivery cannot ship stale data.
    """

    if occurred_at.tzinfo is None:
        raise AttendeeSocialRuleError(
            "NOTIFICATION_NAIVE_DATETIME", "occurred_at must be timezone-aware."
        )
    return {
        "notification_code": FOLLOWED_USER_REGISTERED_PREFERENCE_KEY,
        "recipient_id": str(recipient_id),
        "actor_id": str(actor_id),
        "activity_id": str(activity_id),
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "dedupe_key": followed_user_registered_dedupe_key(
            recipient_id=recipient_id, actor_id=actor_id, activity_id=activity_id
        ),
    }
