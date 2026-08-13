"""Pure-domain tests for onsite check-in operations (CHK-002).

These tests deliberately touch no database, no settings and no network, so they
run on any machine including one without PostgreSQL or Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from vav.modules.checkin_operations.domain import (
    LAST_FOUR_LENGTH,
    MAX_LOOKUP_CANDIDATES,
    AttendanceStatus,
    CheckinRuleError,
    LookupCandidate,
    LookupOutcome,
    ScanOutcome,
    WindowPolicy,
    WindowState,
    build_audit_metadata,
    build_lookup_response,
    candidate_choice_payload,
    choice_token,
    classify_checkin_window,
    confirmation_token,
    decide_lookup_outcome,
    decide_scan,
    ensure_checkin_window,
    ensure_choice_payload_safe,
    ensure_last_four,
    ensure_undo_allowed,
    evaluate_rate_limit,
    is_lookup_expired,
    last_four_hmac,
    last_four_of,
    mask_name_initial,
    mask_phone_fragment,
    match_choice_token,
    normalize_phone_digits,
    registration_number_suffix,
    require_reason,
    scan_dedupe_key,
    verify_confirmation_token,
)

NOW = datetime(2026, 8, 12, 19, 0, tzinfo=UTC)
KEY = b"unit-test-deployment-salt-not-a-real-key"
OTHER_KEY = b"a-different-deployment-salt-entirely-xxx"
LOOKUP_ID = UUID(int=7)


def _uid(value: int) -> UUID:
    return UUID(int=value)


def _candidate(
    index: int,
    *,
    name: str = "Zhang Wei",
    number: str = "REG-2026-0001",
    attendance: str = "not_checked_in",
) -> LookupCandidate:
    return LookupCandidate(
        registration_id=_uid(index),
        user_id=_uid(1000 + index),
        registration_number=number,
        display_name=name,
        registration_status="confirmed",
        attendance_status=attendance,
        ticket_label="Standard",
    )


# ---------------------------------------------------------------------------
# Phone normalization and the last-four key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw", ["138 0013 8000", "+86-138-0013-8000", "(138) 0013 8000", "13800138000"]
)
def test_operator_typed_punctuation_is_stripped(raw: str) -> None:
    assert normalize_phone_digits(raw).endswith("0138000")


def test_letters_in_a_phone_field_are_refused_rather_than_guessed_at() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        normalize_phone_digits("138OO138000")
    assert excinfo.value.code == "CHECKIN_PHONE_INPUT_INVALID"


def test_a_too_short_number_is_refused() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        normalize_phone_digits("1234")
    assert excinfo.value.code == "CHECKIN_PHONE_INPUT_TOO_SHORT"


def test_last_four_is_derived_from_the_tail_of_the_number() -> None:
    assert last_four_of("+86 138-0013-8417") == "8417"
    assert len("8417") == LAST_FOUR_LENGTH


@pytest.mark.parametrize("value", ["841", "84177", "84a7", " 84 7", ""])
def test_only_exactly_four_digits_are_an_acceptable_lookup_input(value: str) -> None:
    """A longer fragment would turn the lookup into a phone-number oracle."""

    with pytest.raises(CheckinRuleError) as excinfo:
        ensure_last_four(value)
    assert excinfo.value.code == "CHECKIN_LAST_FOUR_INVALID"


def test_last_four_hmac_is_stable_and_deployment_scoped() -> None:
    first = last_four_hmac("8417", key=KEY)
    assert first == last_four_hmac("8417", key=KEY)
    assert first != last_four_hmac("8417", key=OTHER_KEY)
    assert first != last_four_hmac("8418", key=KEY)


def test_last_four_hmac_carries_its_salt_version_for_rotation() -> None:
    assert last_four_hmac("8417", key=KEY, salt_version="v1").startswith("v1:")
    assert last_four_hmac("8417", key=KEY, salt_version="v2") != last_four_hmac(
        "8417", key=KEY, salt_version="v1"
    )


def test_hashing_with_an_empty_key_is_refused() -> None:
    """An unsalted four-digit HMAC is a rainbow table, so this must never happen."""

    with pytest.raises(CheckinRuleError) as excinfo:
        last_four_hmac("8417", key=b"")
    assert excinfo.value.code == "CHECKIN_LAST_FOUR_KEY_MISSING"


def test_the_hmac_never_contains_the_digits_it_covers() -> None:
    assert "8417" not in last_four_hmac("8417", key=KEY)


def test_masked_fragment_does_not_imply_a_known_full_number() -> None:
    assert mask_phone_fragment("8417") == "••••8417"


# ---------------------------------------------------------------------------
# The load-bearing rule: last four alone never resolves an identity
# ---------------------------------------------------------------------------


def test_last_four_alone_never_resolves_an_identity_when_candidates_are_ambiguous() -> None:
    """Two people sharing a last-four is normal at scale, not an edge case.

    The decision must be AMBIGUOUS with no resolved registration, and it must
    demand a discriminator the operator gets from the person in front of them.
    """

    decision = decide_lookup_outcome([_candidate(1), _candidate(2)])
    assert decision.outcome is LookupOutcome.AMBIGUOUS
    assert decision.resolved_registration_id is None
    assert decision.requires_discriminator is True
    assert len(decision.candidates) == 2


def test_a_single_match_resolves_but_still_requires_confirmation() -> None:
    decision = decide_lookup_outcome([_candidate(1)])
    assert decision.outcome is LookupOutcome.SINGLE_CANDIDATE
    assert decision.resolved_registration_id == _uid(1)
    assert decision.requires_discriminator is False


def test_no_match_returns_nothing_at_all() -> None:
    decision = decide_lookup_outcome([])
    assert decision.outcome is LookupOutcome.NO_MATCH
    assert decision.candidates == ()
    assert decision.resolved_registration_id is None


def test_an_enumerating_search_gets_a_count_and_no_candidates() -> None:
    candidates = [_candidate(index) for index in range(1, MAX_LOOKUP_CANDIDATES + 2)]
    decision = decide_lookup_outcome(candidates)
    assert decision.outcome is LookupOutcome.TOO_MANY
    assert decision.candidates == ()
    assert decision.resolved_registration_id is None


def test_duplicate_rows_for_one_registration_do_not_fake_ambiguity() -> None:
    """A member with two verified numbers must not look like two people."""

    decision = decide_lookup_outcome([_candidate(1), _candidate(1)])
    assert decision.outcome is LookupOutcome.SINGLE_CANDIDATE


# ---------------------------------------------------------------------------
# Discriminators and opaque choice tokens
# ---------------------------------------------------------------------------


def test_the_discriminator_is_itself_non_identifying() -> None:
    payload = candidate_choice_payload(_candidate(1, name="Zhang Wei"), token="a" * 32)
    assert payload["name_initial"] == "Z*"
    assert payload["registration_suffix"] == "0001"
    assert "display_name" not in payload
    assert "user_id" not in payload
    assert "registration_number" not in payload


def test_an_empty_name_masks_to_a_stable_slot() -> None:
    assert mask_name_initial("") == "?"
    assert mask_name_initial("   ") == "?"
    assert mask_name_initial("张伟") == "张*"


def test_registration_suffix_never_returns_the_whole_number() -> None:
    assert registration_number_suffix("REG-2026-004417") == "4417"
    with pytest.raises(CheckinRuleError) as excinfo:
        registration_number_suffix("REG-2026-004417", length=12)
    assert excinfo.value.code == "CHECKIN_SUFFIX_LENGTH_INVALID"


def test_choice_tokens_are_opaque_and_scoped_to_one_lookup() -> None:
    token = choice_token(lookup_id=LOOKUP_ID, registration_id=_uid(1), issued_at=NOW, key=KEY)
    assert str(_uid(1)) not in token
    assert token != choice_token(
        lookup_id=UUID(int=8), registration_id=_uid(1), issued_at=NOW, key=KEY
    )
    assert token != choice_token(
        lookup_id=LOOKUP_ID, registration_id=_uid(2), issued_at=NOW, key=KEY
    )


def test_a_choice_token_resolves_to_exactly_its_candidate() -> None:
    candidates = [_candidate(1), _candidate(2)]
    token = choice_token(lookup_id=LOOKUP_ID, registration_id=_uid(2), issued_at=NOW, key=KEY)
    matched = match_choice_token(token, candidates, lookup_id=LOOKUP_ID, issued_at=NOW, key=KEY)
    assert matched.registration_id == _uid(2)


def test_a_token_from_another_lookup_or_another_key_is_rejected() -> None:
    candidates = [_candidate(1)]
    foreign = choice_token(lookup_id=UUID(int=99), registration_id=_uid(1), issued_at=NOW, key=KEY)
    with pytest.raises(CheckinRuleError) as excinfo:
        match_choice_token(foreign, candidates, lookup_id=LOOKUP_ID, issued_at=NOW, key=KEY)
    assert excinfo.value.code == "CHECKIN_CHOICE_TOKEN_INVALID"

    wrong_key = choice_token(
        lookup_id=LOOKUP_ID, registration_id=_uid(1), issued_at=NOW, key=OTHER_KEY
    )
    with pytest.raises(CheckinRuleError):
        match_choice_token(wrong_key, candidates, lookup_id=LOOKUP_ID, issued_at=NOW, key=KEY)


def test_an_empty_choice_token_is_its_own_error() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        match_choice_token("", [_candidate(1)], lookup_id=LOOKUP_ID, issued_at=NOW, key=KEY)
    assert excinfo.value.code == "CHECKIN_CHOICE_TOKEN_REQUIRED"


def test_the_payload_guard_refuses_personal_data() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        ensure_choice_payload_safe({"choice_token": "a" * 32, "user_id": str(uuid4())})
    assert excinfo.value.code == "CHECKIN_CANDIDATE_PAYLOAD_UNSAFE"


def test_the_payload_guard_refuses_a_long_digit_run() -> None:
    """A registration number or phone fragment smuggled into a label."""

    with pytest.raises(CheckinRuleError):
        ensure_choice_payload_safe({"ticket_label": "VIP 13800138000"})


def test_the_payload_guard_refuses_an_unmasked_name() -> None:
    with pytest.raises(CheckinRuleError):
        ensure_choice_payload_safe({"name_initial": "Zhang Wei"})


def test_a_whole_lookup_response_carries_only_masked_candidates() -> None:
    decision = decide_lookup_outcome([_candidate(1), _candidate(2, number="REG-2026-0002")])
    response = build_lookup_response(decision, lookup_id=LOOKUP_ID, issued_at=NOW, key=KEY)
    assert response["outcome"] == "ambiguous"
    assert response["requires_discriminator"] is True
    assert response["candidate_count"] == 2
    serialized = repr(response)
    assert "Zhang Wei" not in serialized
    assert "REG-2026-0001" not in serialized
    for item in response["candidates"]:
        assert set(item) == {
            "choice_token",
            "name_initial",
            "registration_suffix",
            "ticket_label",
            "attendance_status",
        }


def test_a_lookup_expires_on_the_clock_not_on_a_sweeper() -> None:
    assert not is_lookup_expired(NOW, now=NOW + timedelta(seconds=59), ttl_seconds=60)
    assert is_lookup_expired(NOW, now=NOW + timedelta(seconds=60), ttl_seconds=60)
    with pytest.raises(CheckinRuleError) as excinfo:
        is_lookup_expired(NOW, now=NOW, ttl_seconds=0)
    assert excinfo.value.code == "CHECKIN_TTL_INVALID"


def test_naive_datetimes_are_rejected_rather_than_assumed_utc() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        is_lookup_expired(datetime(2026, 8, 12, 19, 0), now=NOW, ttl_seconds=60)
    assert excinfo.value.code == "CHECKIN_NAIVE_DATETIME"


# ---------------------------------------------------------------------------
# Confirmation tokens
# ---------------------------------------------------------------------------


def test_a_confirmation_token_is_bound_to_its_operator() -> None:
    token = confirmation_token(
        lookup_id=LOOKUP_ID,
        registration_id=_uid(1),
        operator_id=_uid(50),
        issued_at=NOW,
        key=KEY,
    )
    verify_confirmation_token(
        token,
        lookup_id=LOOKUP_ID,
        registration_id=_uid(1),
        operator_id=_uid(50),
        issued_at=NOW,
        now=NOW + timedelta(seconds=10),
        ttl_seconds=120,
        key=KEY,
    )
    with pytest.raises(CheckinRuleError) as excinfo:
        verify_confirmation_token(
            token,
            lookup_id=LOOKUP_ID,
            registration_id=_uid(1),
            operator_id=_uid(51),
            issued_at=NOW,
            now=NOW + timedelta(seconds=10),
            ttl_seconds=120,
            key=KEY,
        )
    assert excinfo.value.code == "CHECKIN_CONFIRMATION_INVALID"


def test_a_stale_confirmation_is_refused_even_though_it_is_authentic() -> None:
    token = confirmation_token(
        lookup_id=LOOKUP_ID,
        registration_id=_uid(1),
        operator_id=_uid(50),
        issued_at=NOW,
        key=KEY,
    )
    with pytest.raises(CheckinRuleError) as excinfo:
        verify_confirmation_token(
            token,
            lookup_id=LOOKUP_ID,
            registration_id=_uid(1),
            operator_id=_uid(50),
            issued_at=NOW,
            now=NOW + timedelta(seconds=121),
            ttl_seconds=120,
            key=KEY,
        )
    assert excinfo.value.code == "CHECKIN_CONFIRMATION_EXPIRED"


# ---------------------------------------------------------------------------
# Scan idempotency
# ---------------------------------------------------------------------------


def test_duplicate_scan_is_an_idempotent_success_not_an_error() -> None:
    """The requirement, stated as a test.

    A second scan of somebody already checked in must succeed, must not write,
    and must report the *original* timestamp. Returning 409 here trains
    operators to ignore red screens on a busy door.
    """

    first_at = NOW - timedelta(minutes=5)
    decision = decide_scan(
        registration_status="confirmed",
        attendance_status=AttendanceStatus.CHECKED_IN,
        checked_in_at=first_at,
        now=NOW,
    )
    assert decision.outcome is ScanOutcome.DUPLICATE_NOOP
    assert decision.writes_attendance is False
    assert decision.effective_checked_in_at == first_at
    assert decision.message_code == "CHECKIN_ALREADY_DONE"


def test_repeated_scans_converge_on_one_state() -> None:
    decisions = [
        decide_scan(
            registration_status="confirmed",
            attendance_status=AttendanceStatus.CHECKED_IN,
            checked_in_at=NOW - timedelta(minutes=5),
            now=NOW + timedelta(seconds=offset),
        )
        for offset in range(0, 30, 10)
    ]
    assert {decision.outcome for decision in decisions} == {ScanOutcome.DUPLICATE_NOOP}
    assert not any(decision.writes_attendance for decision in decisions)


def test_a_first_scan_writes_attendance_at_now() -> None:
    decision = decide_scan(
        registration_status="confirmed",
        attendance_status=AttendanceStatus.NOT_CHECKED_IN,
        checked_in_at=None,
        now=NOW,
    )
    assert decision.outcome is ScanOutcome.CHECKED_IN
    assert decision.writes_attendance is True
    assert decision.effective_checked_in_at == NOW
    assert decision.audit_action == "check_in"


def test_a_no_show_who_turns_up_is_simply_checked_in() -> None:
    decision = decide_scan(
        registration_status="confirmed",
        attendance_status=AttendanceStatus.NO_SHOW,
        checked_in_at=None,
        now=NOW,
    )
    assert decision.outcome is ScanOutcome.CHECKED_IN


def test_a_revoked_checkin_is_reinstated_under_its_own_action() -> None:
    decision = decide_scan(
        registration_status="confirmed",
        attendance_status=AttendanceStatus.CHECKIN_REVOKED,
        checked_in_at=NOW - timedelta(hours=1),
        now=NOW,
    )
    assert decision.outcome is ScanOutcome.REINSTATED
    assert decision.audit_action == "reinstate"


def test_an_inconsistent_row_does_not_invent_a_past_timestamp() -> None:
    decision = decide_scan(
        registration_status="confirmed",
        attendance_status=AttendanceStatus.CHECKED_IN,
        checked_in_at=None,
        now=NOW,
    )
    assert decision.outcome is ScanOutcome.DUPLICATE_NOOP
    assert decision.effective_checked_in_at == NOW


@pytest.mark.parametrize("status", ["cancelled", "rejected", "expired"])
def test_a_terminal_registration_cannot_be_checked_in(status: str) -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        decide_scan(
            registration_status=status,
            attendance_status=AttendanceStatus.NOT_CHECKED_IN,
            checked_in_at=None,
            now=NOW,
        )
    assert excinfo.value.code == "CHECKIN_REGISTRATION_NOT_ACTIVE"


@pytest.mark.parametrize(
    "status",
    [
        "started",
        "pending_approval",
        "approved_pending_payment",
        "pending_payment",
        "payment_processing",
        "waitlisted",
    ],
)
def test_an_unconfirmed_registration_gets_its_own_refusal_code(status: str) -> None:
    """Distinct from the terminal code: the operator's next action differs."""

    with pytest.raises(CheckinRuleError) as excinfo:
        decide_scan(
            registration_status=status,
            attendance_status=AttendanceStatus.NOT_CHECKED_IN,
            checked_in_at=None,
            now=NOW,
        )
    assert excinfo.value.code == "CHECKIN_REGISTRATION_NOT_CONFIRMED"


def test_a_scan_dedupe_key_is_stable_per_request() -> None:
    key = scan_dedupe_key(registration_id=_uid(1), device_reference="scanner-3", request_id="req-1")
    assert key == scan_dedupe_key(
        registration_id=_uid(1), device_reference="scanner-3", request_id="req-1"
    )
    assert key != scan_dedupe_key(
        registration_id=_uid(1), device_reference="scanner-3", request_id="req-2"
    )
    with pytest.raises(CheckinRuleError) as excinfo:
        scan_dedupe_key(registration_id=_uid(1), device_reference="scanner-3", request_id="")
    assert excinfo.value.code == "CHECKIN_REQUEST_ID_REQUIRED"


# ---------------------------------------------------------------------------
# Undo window
# ---------------------------------------------------------------------------


def test_an_undo_inside_the_window_needs_a_written_reason() -> None:
    reason = ensure_undo_allowed(
        attendance_status=AttendanceStatus.CHECKED_IN,
        checked_in_at=NOW - timedelta(minutes=2),
        now=NOW,
        undo_window_minutes=10,
        reason="  scanned the wrong person  ",
    )
    assert reason == "scanned the wrong person"


@pytest.mark.parametrize("reason", [None, "", "   ", "no"])
def test_an_undo_without_a_reason_is_refused(reason: str | None) -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        ensure_undo_allowed(
            attendance_status=AttendanceStatus.CHECKED_IN,
            checked_in_at=NOW - timedelta(minutes=2),
            now=NOW,
            undo_window_minutes=10,
            reason=reason,
        )
    assert excinfo.value.code == "CHECKIN_UNDO_REASON_REQUIRED"


def test_an_undo_after_the_window_is_sent_to_the_audited_revoke_path() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        ensure_undo_allowed(
            attendance_status=AttendanceStatus.CHECKED_IN,
            checked_in_at=NOW - timedelta(minutes=11),
            now=NOW,
            undo_window_minutes=10,
            reason="mis-tap",
        )
    assert excinfo.value.code == "CHECKIN_UNDO_WINDOW_EXPIRED"


def test_there_is_nothing_to_undo_when_nobody_checked_in() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        ensure_undo_allowed(
            attendance_status=AttendanceStatus.NOT_CHECKED_IN,
            checked_in_at=None,
            now=NOW,
            undo_window_minutes=10,
            reason="mis-tap",
        )
    assert excinfo.value.code == "CHECKIN_UNDO_NOT_CHECKED_IN"


def test_a_zero_window_disables_undo_explicitly() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        ensure_undo_allowed(
            attendance_status=AttendanceStatus.CHECKED_IN,
            checked_in_at=NOW,
            now=NOW,
            undo_window_minutes=0,
            reason="mis-tap",
        )
    assert excinfo.value.code == "CHECKIN_UNDO_DISABLED"


def test_require_reason_trims_and_enforces_a_floor() -> None:
    assert require_reason("  late arrival  ", code="X") == "late arrival"
    with pytest.raises(CheckinRuleError) as excinfo:
        require_reason("ok", code="MY_CODE")
    assert excinfo.value.code == "MY_CODE"


# ---------------------------------------------------------------------------
# Per-operator rate limiting
# ---------------------------------------------------------------------------


def test_a_stuck_scanner_is_rate_limited_with_a_retry_hint() -> None:
    events = [NOW - timedelta(seconds=offset) for offset in range(10)]
    decision = evaluate_rate_limit(events, now=NOW, window_seconds=60, max_events=10)
    assert decision.allowed is False
    assert decision.observed == 10
    assert decision.remaining == 0
    assert 1 <= decision.retry_after_seconds <= 60


def test_events_outside_the_window_do_not_count() -> None:
    old = [NOW - timedelta(seconds=120 + offset) for offset in range(50)]
    decision = evaluate_rate_limit(old, now=NOW, window_seconds=60, max_events=10)
    assert decision.allowed is True
    assert decision.observed == 0
    assert decision.remaining == 10


def test_the_limit_frees_up_as_the_window_slides() -> None:
    events = [NOW - timedelta(seconds=59)] + [NOW - timedelta(seconds=1)] * 9
    blocked = evaluate_rate_limit(events, now=NOW, window_seconds=60, max_events=10)
    assert blocked.allowed is False
    later = evaluate_rate_limit(
        events, now=NOW + timedelta(seconds=2), window_seconds=60, max_events=10
    )
    assert later.allowed is True


def test_a_misconfigured_rate_limit_is_loud() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        evaluate_rate_limit([], now=NOW, window_seconds=0, max_events=10)
    assert excinfo.value.code == "CHECKIN_RATE_LIMIT_CONFIG_INVALID"


# ---------------------------------------------------------------------------
# Check-in window policy and override
# ---------------------------------------------------------------------------

START = datetime(2026, 8, 12, 19, 0, tzinfo=UTC)
END = datetime(2026, 8, 12, 22, 0, tzinfo=UTC)
POLICY = WindowPolicy(early_minutes=60, late_minutes=30)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (START - timedelta(minutes=90), WindowState.TOO_EARLY),
        (START - timedelta(minutes=59), WindowState.EARLY_GRACE),
        (START, WindowState.IN_WINDOW),
        (END, WindowState.IN_WINDOW),
        (END + timedelta(minutes=29), WindowState.LATE_GRACE),
        (END + timedelta(minutes=31), WindowState.TOO_LATE),
    ],
)
def test_the_window_is_classified_from_configured_grace(
    moment: datetime, expected: WindowState
) -> None:
    assert (
        classify_checkin_window(
            now=moment, session_start_at=START, session_end_at=END, policy=POLICY
        )
        is expected
    )


def test_out_of_window_needs_an_override_permission_and_a_reason() -> None:
    """The requirement, stated as a test.

    Both halves matter. Without the permission it is refused outright; with the
    permission but no reason it is still refused, because "the operator had the
    permission" does not answer "why was this person admitted 90 minutes late".
    """

    state = classify_checkin_window(
        now=END + timedelta(minutes=90), session_start_at=START, session_end_at=END, policy=POLICY
    )
    assert state is WindowState.TOO_LATE

    with pytest.raises(CheckinRuleError) as excinfo:
        ensure_checkin_window(state, has_override_permission=False)
    assert excinfo.value.code == "CHECKIN_WINDOW_TOO_LATE"

    with pytest.raises(CheckinRuleError) as excinfo:
        ensure_checkin_window(state, has_override_permission=True, override_reason=None)
    assert excinfo.value.code == "CHECKIN_OVERRIDE_REASON_REQUIRED"

    decision = ensure_checkin_window(
        state, has_override_permission=True, override_reason="member's flight was delayed"
    )
    assert decision.override_used is True
    assert decision.override_reason == "member's flight was delayed"
    assert decision.state is WindowState.TOO_LATE


def test_too_early_and_too_late_have_distinct_refusal_codes() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        ensure_checkin_window(WindowState.TOO_EARLY, has_override_permission=False)
    assert excinfo.value.code == "CHECKIN_WINDOW_TOO_EARLY"


@pytest.mark.parametrize(
    "state", [WindowState.IN_WINDOW, WindowState.EARLY_GRACE, WindowState.LATE_GRACE]
)
def test_inside_the_window_no_override_is_asked_for(state: WindowState) -> None:
    decision = ensure_checkin_window(state, has_override_permission=False)
    assert decision.requires_override is False
    assert decision.override_used is False
    assert decision.override_reason is None


def test_a_session_ending_before_it_starts_is_refused() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        classify_checkin_window(now=NOW, session_start_at=END, session_end_at=START, policy=POLICY)
    assert excinfo.value.code == "CHECKIN_SESSION_WINDOW_INVALID"


def test_a_negative_grace_configuration_is_refused() -> None:
    with pytest.raises(CheckinRuleError) as excinfo:
        WindowPolicy(early_minutes=-1)
    assert excinfo.value.code == "CHECKIN_WINDOW_POLICY_INVALID"


# ---------------------------------------------------------------------------
# Audit metadata
# ---------------------------------------------------------------------------


def test_audit_metadata_records_the_override_and_nothing_identifying() -> None:
    window = ensure_checkin_window(
        WindowState.TOO_LATE, has_override_permission=True, override_reason="delayed flight"
    )
    metadata = build_audit_metadata(
        outcome=ScanOutcome.CHECKED_IN,
        window=window,
        method="manual",
        device_reference="door-tablet-2",
        lookup_last_four_masked=mask_phone_fragment("8417"),
    )
    assert metadata["override_used"] is True
    assert metadata["override_reason"] == "delayed flight"
    assert metadata["window_state"] == "too_late"
    assert metadata["searched_fragment"] == "••••8417"
    assert "display_name" not in metadata
    assert "user_id" not in metadata


def test_audit_metadata_refuses_an_unmasked_fragment() -> None:
    window = ensure_checkin_window(WindowState.IN_WINDOW, has_override_permission=False)
    with pytest.raises(CheckinRuleError) as excinfo:
        build_audit_metadata(
            outcome=ScanOutcome.CHECKED_IN,
            window=window,
            method="manual",
            device_reference="door-tablet-2",
            lookup_last_four_masked="13800138417",
        )
    assert excinfo.value.code == "CHECKIN_AUDIT_METADATA_UNSAFE"


def test_audit_metadata_defaults_an_unknown_device() -> None:
    window = ensure_checkin_window(WindowState.IN_WINDOW, has_override_permission=False)
    metadata = build_audit_metadata(
        outcome=ScanOutcome.DUPLICATE_NOOP, window=window, method="qr", device_reference=""
    )
    assert metadata["device_reference"] == "unknown-device"
    assert metadata["outcome"] == "duplicate_noop"
