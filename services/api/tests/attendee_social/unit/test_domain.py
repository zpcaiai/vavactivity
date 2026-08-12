"""Pure-domain tests for attendee preview and the follow graph (ATT-001 / SOC-001).

These tests deliberately touch no database, no settings and no network, so they
run on any machine including one without PostgreSQL or Redis. They exist mostly
to pin the *safe defaults*: an attendee who never answered the consent prompt
must be invisible, and a follow must never behave like a like.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from vav.modules.attendee_social.domain import (
    CONFIRMED_REGISTRATION_STATUSES,
    DEFAULT_PREVIEW_CONSENT_STATE,
    FOLLOWED_USER_REGISTERED_PREFERENCE_KEY,
    INTRO_LINE_MAX_LENGTH,
    PREVIEW_PROJECTION_FIELDS,
    AttendeeRecord,
    AttendeeSocialRuleError,
    FollowAction,
    FollowState,
    NotificationSuppression,
    PreviewConsentState,
    PreviewExclusionReason,
    RelationKind,
    apply_block_to_follows,
    apply_consent_decision,
    assert_minimum_projection,
    build_followed_user_registered_payload,
    build_preview,
    decide_followed_user_registered,
    evaluate_preview_visibility,
    followed_user_registered_dedupe_key,
    is_preview_visible,
    plan_follow,
    plan_unfollow,
    project_attendee,
    relation_implies,
    relation_semantics,
    validate_consent_transition,
)

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _uid(value: int) -> UUID:
    return UUID(int=value)


def _record(
    index: int,
    *,
    registration_status: str = "confirmed",
    payment_state: str = "paid",
    consent_state: str = PreviewConsentState.GRANTED.value,
    attendance_status: str = "not_checked_in",
    is_staff: bool = False,
    is_suspended: bool = False,
    display_name: str | None = None,
    avatar_url: str | None = "https://cdn.example.com/a.jpg",
    intro_line: str | None = "loves hiking",
) -> AttendeeRecord:
    return AttendeeRecord(
        user_id=_uid(index),
        registration_id=_uid(1000 + index),
        registration_status=registration_status,
        payment_state=payment_state,
        consent_state=consent_state,
        attendance_status=attendance_status,
        is_staff=is_staff,
        is_suspended=is_suspended,
        display_name=f"member-{index:02d}" if display_name is None else display_name,
        avatar_url=avatar_url,
        intro_line=intro_line,
    )


# ---------------------------------------------------------------------------
# ATT-001 / DEC-002 the safe default is opt-in
# ---------------------------------------------------------------------------


def test_the_default_consent_state_is_not_asked() -> None:
    assert DEFAULT_PREVIEW_CONSENT_STATE is PreviewConsentState.NOT_ASKED
    assert AttendeeRecord(
        user_id=_uid(1),
        registration_id=_uid(2),
        registration_status="confirmed",
        payment_state="paid",
    ).consent_state == PreviewConsentState.NOT_ASKED.value


def test_a_member_who_never_answered_is_not_shown() -> None:
    """The whole point of DEC-002: silence is a refusal, not permission."""

    decision = evaluate_preview_visibility(
        _record(1, consent_state=PreviewConsentState.NOT_ASKED.value)
    )
    assert decision.visible is False
    assert decision.exclusion_reason is PreviewExclusionReason.NO_CONSENT


def test_a_declined_member_is_not_shown() -> None:
    assert is_preview_visible(_record(1, consent_state="declined")) is False


def test_a_withdrawn_member_is_not_shown_and_is_reported_distinctly() -> None:
    decision = evaluate_preview_visibility(_record(1, consent_state="withdrawn"))
    assert decision.visible is False
    assert decision.exclusion_reason is PreviewExclusionReason.CONSENT_WITHDRAWN


def test_an_explicitly_consented_confirmed_paid_attendee_is_shown() -> None:
    decision = evaluate_preview_visibility(_record(1))
    assert decision.visible is True
    assert decision.exclusion_reason is None


# ---------------------------------------------------------------------------
# ATT-001 registration, payment and staff exclusions
# ---------------------------------------------------------------------------


def test_only_confirmed_registrations_can_be_previewed() -> None:
    assert CONFIRMED_REGISTRATION_STATUSES == frozenset({"confirmed"})


@pytest.mark.parametrize(
    "status", ["waitlisted", "cancelled", "pending_payment", "rejected", "expired"]
)
def test_a_non_confirmed_registration_is_excluded(status: str) -> None:
    decision = evaluate_preview_visibility(_record(1, registration_status=status))
    assert decision.exclusion_reason is PreviewExclusionReason.NOT_CONFIRMED


@pytest.mark.parametrize("payment", ["unpaid", "pending", "refunded", "failed"])
def test_an_unsettled_registration_is_excluded(payment: str) -> None:
    decision = evaluate_preview_visibility(_record(1, payment_state=payment))
    assert decision.exclusion_reason is PreviewExclusionReason.NOT_SETTLED


def test_a_free_event_counts_as_settled() -> None:
    assert is_preview_visible(_record(1, payment_state="not_required")) is True


def test_staff_are_excluded_before_every_other_rule() -> None:
    decision = evaluate_preview_visibility(
        _record(1, is_staff=True, registration_status="cancelled", payment_state="unpaid")
    )
    assert decision.exclusion_reason is PreviewExclusionReason.STAFF


def test_a_suspended_account_is_hidden_even_with_consent() -> None:
    decision = evaluate_preview_visibility(_record(1, is_suspended=True))
    assert decision.exclusion_reason is PreviewExclusionReason.SUSPENDED


def test_absent_attendees_are_only_dropped_when_the_caller_asks() -> None:
    """Before the event everybody is legitimately ``not_checked_in``."""

    record = _record(1, attendance_status="no_show")
    assert is_preview_visible(record) is True
    assert is_preview_visible(record, exclude_absent=True) is False
    assert is_preview_visible(_record(1), exclude_absent=True) is True


# ---------------------------------------------------------------------------
# ATT-001 minimum-field projection
# ---------------------------------------------------------------------------


def test_the_projection_carries_only_the_minimum_fields() -> None:
    payload = project_attendee(_record(1))
    assert set(payload) == PREVIEW_PROJECTION_FIELDS
    assert set(payload) == {"user_id", "display_name", "avatar_url", "intro_line"}
    assert_minimum_projection(payload)


def test_no_hidden_profile_field_can_be_serialized() -> None:
    payload = dict(project_attendee(_record(1)))
    payload["gender_code"] = "female"
    with pytest.raises(AttendeeSocialRuleError) as excinfo:
        assert_minimum_projection(payload)
    assert excinfo.value.code == "PREVIEW_PROJECTION_LEAK"
    assert excinfo.value.details["fields"] == ["gender_code"]


def test_a_blank_display_name_falls_back_to_a_pseudonymous_handle() -> None:
    payload = project_attendee(_record(1, display_name="   "))
    assert payload["display_name"].startswith("member-")


def test_the_intro_line_is_truncated_and_optional() -> None:
    payload = project_attendee(_record(1, intro_line="x" * 200))
    assert len(payload["intro_line"]) == INTRO_LINE_MAX_LENGTH
    assert project_attendee(_record(1, intro_line="   "))["intro_line"] is None
    assert project_attendee(_record(1), include_intro=False)["intro_line"] is None


def test_a_blank_avatar_becomes_none_rather_than_an_empty_string() -> None:
    assert project_attendee(_record(1, avatar_url="  "))["avatar_url"] is None


# ---------------------------------------------------------------------------
# ATT-001 the assembled preview
# ---------------------------------------------------------------------------


def test_the_preview_shows_only_consented_attendees_and_counts_the_rest() -> None:
    records = [
        _record(1),
        _record(2),
        _record(3, consent_state="not_asked"),
        _record(4, consent_state="withdrawn"),
        _record(5, registration_status="waitlisted"),
        _record(6, is_staff=True),
    ]
    summary = build_preview(records)
    assert len(summary.items) == 2
    assert {item["user_id"] for item in summary.items} == {str(_uid(1)), str(_uid(2))}
    # Waitlisted and staff are not "withheld"; they were never candidates.
    assert summary.withheld_count == 2
    assert summary.total_considered == 6


def test_the_preview_is_deterministically_ordered_and_limited() -> None:
    records = [_record(index) for index in range(1, 8)]
    summary = build_preview(records, limit=3)
    assert [item["display_name"] for item in summary.items] == [
        "member-01",
        "member-02",
        "member-03",
    ]
    assert summary.additional_visible_count == 4
    assert build_preview(list(reversed(records)), limit=3).items == summary.items


def test_an_invalid_preview_limit_is_rejected() -> None:
    with pytest.raises(AttendeeSocialRuleError) as excinfo:
        build_preview([_record(1)], limit=0)
    assert excinfo.value.code == "PREVIEW_LIMIT_INVALID"
    with pytest.raises(AttendeeSocialRuleError):
        build_preview([_record(1)], limit=999)


def test_every_preview_item_passes_the_projection_guard() -> None:
    for item in build_preview([_record(1), _record(2)]).items:
        assert_minimum_projection(item)


# ---------------------------------------------------------------------------
# ATT-001 consent lifecycle
# ---------------------------------------------------------------------------


def test_granting_consent_records_a_timestamp_and_an_audit_action() -> None:
    change = apply_consent_decision(
        current_state="not_asked", target_state="granted", now=NOW
    )
    assert change.state is PreviewConsentState.GRANTED
    assert change.granted_at == NOW
    assert change.removes_future_display is False
    assert change.audit_action == "attendee_preview.consent.granted.member"


def test_withdrawal_removes_future_display_and_is_audited() -> None:
    change = apply_consent_decision(
        current_state="granted", target_state="withdrawn", now=NOW
    )
    assert change.removes_future_display is True
    assert change.withdrawn_at == NOW
    assert change.audit_action == "attendee_preview.consent.withdrawn.member"


def test_a_withdrawn_member_may_opt_back_in() -> None:
    change = apply_consent_decision(
        current_state="withdrawn", target_state="granted", now=NOW
    )
    assert change.state is PreviewConsentState.GRANTED


def test_granted_cannot_be_downgraded_to_declined_only_withdrawn() -> None:
    with pytest.raises(AttendeeSocialRuleError) as excinfo:
        validate_consent_transition("granted", "declined")
    assert excinfo.value.code == "CONSENT_TRANSITION_INVALID"


def test_repeating_the_same_consent_state_is_reported_not_silently_applied() -> None:
    with pytest.raises(AttendeeSocialRuleError) as excinfo:
        validate_consent_transition("granted", "granted")
    assert excinfo.value.code == "CONSENT_ALREADY_IN_STATE"


def test_an_unknown_consent_state_is_rejected() -> None:
    with pytest.raises(AttendeeSocialRuleError) as excinfo:
        validate_consent_transition("granted", "maybe")
    assert excinfo.value.code == "CONSENT_STATE_UNKNOWN"


def test_consent_requires_an_aware_timestamp() -> None:
    with pytest.raises(AttendeeSocialRuleError) as excinfo:
        apply_consent_decision(
            current_state="not_asked", target_state="granted", now=datetime(2026, 8, 12)
        )
    assert excinfo.value.code == "CONSENT_NAIVE_DATETIME"


# ---------------------------------------------------------------------------
# SOC-001 follow is not like and not want-to-meet
# ---------------------------------------------------------------------------


def test_the_three_relations_are_distinct_values() -> None:
    assert len({RelationKind.LIKE, RelationKind.FOLLOW, RelationKind.WANT_TO_MEET}) == 3
    assert RelationKind.FOLLOW != RelationKind.LIKE
    assert RelationKind.FOLLOW != RelationKind.WANT_TO_MEET


def test_the_three_relations_live_in_three_different_tables() -> None:
    tables = {
        relation_semantics(kind).table_name
        for kind in (RelationKind.LIKE, RelationKind.FOLLOW, RelationKind.WANT_TO_MEET)
    }
    assert len(tables) == 3


def test_a_follow_never_implies_a_like() -> None:
    assert relation_implies(RelationKind.FOLLOW, RelationKind.LIKE) is False
    assert relation_implies(RelationKind.LIKE, RelationKind.FOLLOW) is False
    assert relation_implies(RelationKind.FOLLOW, RelationKind.FOLLOW) is True


def test_a_like_is_private_until_reciprocated_but_a_follow_is_not() -> None:
    like = relation_semantics(RelationKind.LIKE)
    follow = relation_semantics(RelationKind.FOLLOW)
    assert like.visible_to_target is False
    assert like.requires_reciprocity_to_reveal is True
    assert follow.visible_to_target is True
    assert follow.requires_reciprocity_to_reveal is False
    assert follow.is_event_scoped is False
    assert like.is_event_scoped is True


def test_an_unknown_relation_kind_is_rejected() -> None:
    with pytest.raises(AttendeeSocialRuleError) as excinfo:
        relation_semantics("crush")
    assert excinfo.value.code == "RELATION_KIND_UNKNOWN"


# ---------------------------------------------------------------------------
# SOC-001 follow graph mechanics
# ---------------------------------------------------------------------------


def test_a_new_follow_is_created_and_notifies_once() -> None:
    plan = plan_follow(follower_id=_uid(1), followee_id=_uid(2), current_state=None)
    assert plan.action is FollowAction.CREATED
    assert plan.state is FollowState.ACTIVE
    assert plan.should_notify_target is True


def test_following_twice_is_an_idempotent_no_op() -> None:
    plan = plan_follow(follower_id=_uid(1), followee_id=_uid(2), current_state="active")
    assert plan.action is FollowAction.UNCHANGED
    assert plan.should_notify_target is False


def test_re_following_after_an_unfollow_does_not_re_notify() -> None:
    """Otherwise unfollow/follow becomes a way to repeatedly ping someone."""

    plan = plan_follow(follower_id=_uid(1), followee_id=_uid(2), current_state="unfollowed")
    assert plan.action is FollowAction.REACTIVATED
    assert plan.should_notify_target is False


def test_self_follow_is_rejected() -> None:
    with pytest.raises(AttendeeSocialRuleError) as excinfo:
        plan_follow(follower_id=_uid(1), followee_id=_uid(1), current_state=None)
    assert excinfo.value.code == "FOLLOW_SELF_NOT_ALLOWED"


def test_a_block_in_either_direction_gives_the_same_opaque_error() -> None:
    with pytest.raises(AttendeeSocialRuleError) as first:
        plan_follow(
            follower_id=_uid(1),
            followee_id=_uid(2),
            current_state=None,
            followee_blocks_follower=True,
        )
    with pytest.raises(AttendeeSocialRuleError) as second:
        plan_follow(
            follower_id=_uid(1),
            followee_id=_uid(2),
            current_state=None,
            follower_blocks_followee=True,
        )
    assert first.value.code == second.value.code == "FOLLOW_BLOCKED"
    assert first.value.message == second.value.message


def test_the_following_limit_is_enforced() -> None:
    with pytest.raises(AttendeeSocialRuleError) as excinfo:
        plan_follow(
            follower_id=_uid(1),
            followee_id=_uid(2),
            current_state=None,
            following_count=10,
            max_following=10,
        )
    assert excinfo.value.code == "FOLLOW_LIMIT_REACHED"


def test_unfollowing_is_idempotent() -> None:
    assert plan_unfollow(current_state="active").action is FollowAction.REMOVED
    assert plan_unfollow(current_state=None).action is FollowAction.UNCHANGED
    assert plan_unfollow(current_state="unfollowed").action is FollowAction.UNCHANGED


def test_a_block_severs_follows_in_both_directions() -> None:
    edges = [
        (_uid(1), _uid(2), "active"),
        (_uid(2), _uid(1), "active"),
        (_uid(1), _uid(3), "active"),
        (_uid(3), _uid(1), "unfollowed"),
    ]
    severed = apply_block_to_follows(blocker_id=_uid(1), blocked_id=_uid(2), edges=edges)
    assert set(severed) == {(_uid(1), _uid(2)), (_uid(2), _uid(1))}


# ---------------------------------------------------------------------------
# SOC-001 followed_user_registered notification
# ---------------------------------------------------------------------------


def _decision(**overrides: object):
    kwargs: dict = {
        "recipient_id": _uid(1),
        "actor_id": _uid(2),
        "activity_id": _uid(9),
        "follow_state": "active",
        "blocked_either_way": False,
        "preference_enabled": True,
        "actor_registration_is_public": True,
        "event_is_public": True,
    }
    kwargs.update(overrides)
    return decide_followed_user_registered(**kwargs)  # type: ignore[arg-type]


def test_a_follower_is_notified_when_everything_allows_it() -> None:
    decision = _decision()
    assert decision.should_send is True
    assert decision.suppression is NotificationSuppression.NONE
    assert decision.dedupe_key is not None


def test_a_block_suppresses_the_notification() -> None:
    decision = _decision(blocked_either_way=True)
    assert decision.should_send is False
    assert decision.suppression is NotificationSuppression.BLOCKED


def test_a_disabled_notification_preference_suppresses_delivery() -> None:
    assert _decision(preference_enabled=False).suppression is (
        NotificationSuppression.PREFERENCE_OFF
    )


def test_a_non_follower_is_never_notified() -> None:
    assert _decision(follow_state="unfollowed").suppression is (
        NotificationSuppression.NOT_FOLLOWING
    )
    assert _decision(follow_state=None).should_send is False


def test_a_private_registration_is_not_broadcast_to_followers() -> None:
    assert _decision(actor_registration_is_public=False).suppression is (
        NotificationSuppression.REGISTRATION_NOT_VISIBLE
    )
    assert _decision(event_is_public=False).suppression is (
        NotificationSuppression.EVENT_NOT_PUBLIC
    )


def test_a_member_is_never_notified_about_themselves() -> None:
    assert _decision(recipient_id=_uid(2)).suppression is NotificationSuppression.SELF


def test_delivery_is_idempotent_through_a_stable_dedupe_key() -> None:
    key = followed_user_registered_dedupe_key(
        recipient_id=_uid(1), actor_id=_uid(2), activity_id=_uid(9)
    )
    assert key == followed_user_registered_dedupe_key(
        recipient_id=_uid(1), actor_id=_uid(2), activity_id=_uid(9)
    )
    assert key != followed_user_registered_dedupe_key(
        recipient_id=_uid(1), actor_id=_uid(2), activity_id=_uid(10)
    )
    replay = _decision(already_delivered=True)
    assert replay.should_send is False
    assert replay.suppression is NotificationSuppression.ALREADY_DELIVERED
    assert replay.dedupe_key == key


def test_the_outbox_payload_carries_codes_and_ids_only() -> None:
    payload = build_followed_user_registered_payload(
        recipient_id=_uid(1), actor_id=_uid(2), activity_id=_uid(9), occurred_at=NOW
    )
    assert payload["notification_code"] == FOLLOWED_USER_REGISTERED_PREFERENCE_KEY
    assert set(payload) == {
        "notification_code",
        "recipient_id",
        "actor_id",
        "activity_id",
        "occurred_at",
        "dedupe_key",
    }
    # No display names, no avatars, no event title: resolved at render time.
    assert all(not isinstance(value, dict) for value in payload.values())


def test_the_notification_payload_requires_an_aware_timestamp() -> None:
    with pytest.raises(AttendeeSocialRuleError) as excinfo:
        build_followed_user_registered_payload(
            recipient_id=_uid(1),
            actor_id=_uid(2),
            activity_id=_uid(9),
            occurred_at=datetime(2026, 8, 12),
        )
    assert excinfo.value.code == "NOTIFICATION_NAIVE_DATETIME"
