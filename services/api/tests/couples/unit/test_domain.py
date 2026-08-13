"""Pure-domain tests for couple binding and SCOPE assessments (B16)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from vav.modules.couples.domain import (
    SCOPE_DIMENSION_ORDER,
    UNBOUND_STATUS,
    AdviceBlock,
    AssessmentState,
    CoupleRuleError,
    FreeBenefitState,
    InvitationStatus,
    ParticipantState,
    RelationshipKind,
    RelationshipState,
    ScopeDimension,
    ScopeQuestionSpec,
    ScopeVersionSpec,
    assemble_report_payload,
    compute_alignment,
    consume_free_scope_benefit,
    decide_binding,
    decide_free_scope_grant,
    ensure_raw_answers_readable,
    ensure_report_ready,
    ensure_scope_relationship_active,
    ensure_version_publishable,
    evaluate_report_readiness,
    free_scope_benefit_key,
    invitation_expires_at,
    is_invitation_expired,
    pair_key,
    pair_members,
    partner_progress_view,
    plan_unbind,
    report_idempotency_key,
    score_scope,
    scores_fingerprint,
    validate_assessment_transition,
    validate_invitation_creation,
    validate_invitation_transition,
    validate_scope_answers,
)

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _uid(value: int) -> UUID:
    return UUID(int=value)


ALICE = _uid(1)
BOB = _uid(2)
CAROL = _uid(3)
REL_1 = _uid(1001)
REL_2 = _uid(1002)


# ---------------------------------------------------------------------------
# COUPLE-001 pair key
# ---------------------------------------------------------------------------


def test_pair_key_is_order_independent_and_reversible() -> None:
    assert pair_key(ALICE, BOB) == pair_key(BOB, ALICE)
    assert pair_key(ALICE, BOB) != pair_key(ALICE, CAROL)
    assert pair_members(pair_key(BOB, ALICE)) == (ALICE, BOB)


def test_pair_key_refuses_a_self_pair() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        pair_key(ALICE, ALICE)
    assert excinfo.value.code == "COUPLE_SELF_PAIR_FORBIDDEN"


def test_malformed_pair_key_is_rejected() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        pair_members("not-a-pair")
    assert excinfo.value.code == "COUPLE_PAIR_KEY_MALFORMED"


# ---------------------------------------------------------------------------
# COUPLE-001 invitation lifecycle
# ---------------------------------------------------------------------------


def test_invitation_creation_returns_pair_key_and_kind() -> None:
    key, kind = validate_invitation_creation(
        inviter_id=ALICE,
        invitee_id=BOB,
        relationship_kind="dating",
        inviter_active_relationship_id=None,
        invitee_active_relationship_id=None,
        has_pending_invitation_for_pair=False,
    )
    assert key == pair_key(ALICE, BOB)
    assert kind is RelationshipKind.DATING


def test_invitation_creation_blocks_when_either_side_is_already_bound() -> None:
    with pytest.raises(CoupleRuleError) as inviter:
        validate_invitation_creation(
            inviter_id=ALICE,
            invitee_id=BOB,
            relationship_kind="dating",
            inviter_active_relationship_id=REL_1,
            invitee_active_relationship_id=None,
            has_pending_invitation_for_pair=False,
        )
    assert inviter.value.code == "COUPLE_RELATIONSHIP_CONFLICT"
    with pytest.raises(CoupleRuleError) as invitee:
        validate_invitation_creation(
            inviter_id=ALICE,
            invitee_id=BOB,
            relationship_kind="dating",
            inviter_active_relationship_id=None,
            invitee_active_relationship_id=REL_2,
            has_pending_invitation_for_pair=False,
        )
    assert invitee.value.details["role"] == "invitee"


def test_duplicate_pending_invitation_and_blocked_pair_are_refused() -> None:
    with pytest.raises(CoupleRuleError) as duplicate:
        validate_invitation_creation(
            inviter_id=ALICE,
            invitee_id=BOB,
            relationship_kind="dating",
            inviter_active_relationship_id=None,
            invitee_active_relationship_id=None,
            has_pending_invitation_for_pair=True,
        )
    assert duplicate.value.code == "COUPLE_INVITATION_DUPLICATE"
    with pytest.raises(CoupleRuleError) as blocked:
        validate_invitation_creation(
            inviter_id=ALICE,
            invitee_id=BOB,
            relationship_kind="dating",
            inviter_active_relationship_id=None,
            invitee_active_relationship_id=None,
            has_pending_invitation_for_pair=False,
            blocked=True,
        )
    assert blocked.value.code == "COUPLE_INVITATION_BLOCKED"


def test_unknown_relationship_kind_is_refused() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        validate_invitation_creation(
            inviter_id=ALICE,
            invitee_id=BOB,
            relationship_kind="situationship",
            inviter_active_relationship_id=None,
            invitee_active_relationship_id=None,
            has_pending_invitation_for_pair=False,
        )
    assert excinfo.value.code == "COUPLE_RELATIONSHIP_KIND_UNKNOWN"


def test_answered_invitations_are_terminal() -> None:
    validate_invitation_transition("pending", "accepted")
    validate_invitation_transition("pending", "rejected")
    validate_invitation_transition("pending", "cancelled")
    validate_invitation_transition("pending", "expired")
    with pytest.raises(CoupleRuleError) as excinfo:
        validate_invitation_transition("rejected", "accepted")
    assert excinfo.value.code == "COUPLE_INVITATION_TRANSITION_INVALID"


def test_invitation_expiry_arithmetic() -> None:
    expires = invitation_expires_at(created_at=NOW, ttl_hours=72)
    assert expires == NOW + timedelta(hours=72)
    assert not is_invitation_expired(expires_at=expires, now=NOW)
    assert is_invitation_expired(expires_at=expires, now=expires)
    with pytest.raises(CoupleRuleError) as excinfo:
        invitation_expires_at(created_at=NOW, ttl_hours=0)
    assert excinfo.value.code == "COUPLE_INVITATION_TTL_INVALID"


def _accept(**overrides: object) -> object:
    kwargs: dict[str, object] = {
        "inviter_id": ALICE,
        "invitee_id": BOB,
        "acceptor_id": BOB,
        "invitation_status": InvitationStatus.PENDING.value,
        "relationship_kind": "dating",
        "relationship_id": REL_1,
        "acceptor_active_relationship_id": None,
        "inviter_active_relationship_id": None,
        "expires_at": NOW + timedelta(hours=1),
        "now": NOW,
    }
    kwargs.update(overrides)
    return decide_binding(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# COUPLE-001 two-sided binding
# ---------------------------------------------------------------------------


def test_binding_requires_the_invitee_to_accept() -> None:
    plan = _accept()
    assert plan.pair_key == pair_key(ALICE, BOB)
    assert plan.relationship_kind is RelationshipKind.DATING
    assert {item.user_id for item in plan.status_plans} == {ALICE, BOB}
    assert all(item.source == "couple_binding" for item in plan.status_plans)
    assert all(item.status == "dating" for item in plan.status_plans)
    assert all(item.couple_relationship_id == REL_1 for item in plan.status_plans)


def test_inviter_cannot_accept_their_own_invitation() -> None:
    """No unilateral binding, ever (COUPLE-001)."""

    with pytest.raises(CoupleRuleError) as excinfo:
        _accept(acceptor_id=ALICE)
    assert excinfo.value.code == "COUPLE_UNILATERAL_BINDING_FORBIDDEN"


def test_a_third_party_cannot_accept_an_invitation() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        _accept(acceptor_id=CAROL)
    assert excinfo.value.code == "COUPLE_INVITATION_ACTOR_INVALID"


def test_expired_invitation_cannot_be_accepted() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        _accept(expires_at=NOW - timedelta(seconds=1))
    assert excinfo.value.code == "COUPLE_INVITATION_EXPIRED"


def test_already_answered_invitation_cannot_be_accepted_again() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        _accept(invitation_status=InvitationStatus.ACCEPTED.value)
    assert excinfo.value.code == "COUPLE_INVITATION_TRANSITION_INVALID"


def test_a_member_already_bound_cannot_accept_a_second_invitation() -> None:
    """The relationship-conflict case, re-checked at accept time."""

    with pytest.raises(CoupleRuleError) as excinfo:
        _accept(acceptor_active_relationship_id=REL_2)
    assert excinfo.value.code == "COUPLE_RELATIONSHIP_CONFLICT"
    assert excinfo.value.details["role"] == "invitee"
    with pytest.raises(CoupleRuleError) as inviter:
        _accept(inviter_active_relationship_id=REL_2)
    assert inviter.value.details["role"] == "inviter"


def test_married_binding_writes_the_married_status() -> None:
    plan = _accept(relationship_kind="married")
    assert all(item.status == "married" for item in plan.status_plans)


# ---------------------------------------------------------------------------
# COUPLE-001 unbind
# ---------------------------------------------------------------------------


def test_unbind_releases_both_members_to_undisclosed_not_single() -> None:
    plan = plan_unbind(
        relationship_state=RelationshipState.ACTIVE.value,
        members=[ALICE, BOB],
        actor_id=BOB,
        actor_kind="member",
        reason="ended",
        key=pair_key(ALICE, BOB),
    )
    assert plan.members == (ALICE, BOB)
    assert {item.status for item in plan.status_plans} == {UNBOUND_STATUS}
    assert all(item.couple_relationship_id is None for item in plan.status_plans)
    assert all(item.source == "admin" for item in plan.status_plans)
    assert plan.event_type == "unbound"


def test_only_a_member_of_the_binding_may_unbind_it() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        plan_unbind(
            relationship_state=RelationshipState.ACTIVE.value,
            members=[ALICE, BOB],
            actor_id=CAROL,
            actor_kind="member",
            reason=None,
            key=pair_key(ALICE, BOB),
        )
    assert excinfo.value.code == "COUPLE_UNBIND_ACTOR_INVALID"


def test_administrative_unbind_requires_a_reason() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        plan_unbind(
            relationship_state=RelationshipState.ACTIVE.value,
            members=[ALICE, BOB],
            actor_id=CAROL,
            actor_kind="admin",
            reason="x",
            key=pair_key(ALICE, BOB),
        )
    assert excinfo.value.code == "COUPLE_UNBIND_REASON_REQUIRED"
    plan = plan_unbind(
        relationship_state=RelationshipState.ACTIVE.value,
        members=[ALICE, BOB],
        actor_id=CAROL,
        actor_kind="admin",
        reason="fraud investigation",
        key=pair_key(ALICE, BOB),
    )
    assert plan.event_type == "admin_unbound"


def test_an_already_unbound_relationship_cannot_be_unbound_twice() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        plan_unbind(
            relationship_state=RelationshipState.UNBOUND.value,
            members=[ALICE, BOB],
            actor_id=ALICE,
            actor_kind="member",
            reason=None,
            key=pair_key(ALICE, BOB),
        )
    assert excinfo.value.code == "COUPLE_RELATIONSHIP_NOT_ACTIVE"


# ---------------------------------------------------------------------------
# SCOPE-001 free benefit survives unbind and rebind
# ---------------------------------------------------------------------------


def test_a_fresh_pair_gets_exactly_one_free_scope_assessment() -> None:
    state = FreeBenefitState(pair_key=pair_key(ALICE, BOB))
    decision = decide_free_scope_grant(state)
    assert decision.remaining_after == 0
    assert decision.idempotency_key == free_scope_benefit_key(pair_key(ALICE, BOB))
    consumed = consume_free_scope_benefit(state)
    assert consumed.consumed == 1
    assert consumed.remaining == 0


def test_unbind_then_rebind_does_not_regenerate_the_consumed_free_benefit() -> None:
    """The single most important rule in B16 (SCOPE-001).

    The pair binds, uses the free assessment, unbinds, and binds again as a new
    relationship row. Because the benefit is keyed on the *pair*, the second
    relationship finds the same already-consumed ledger and gets nothing free.
    """

    key = pair_key(ALICE, BOB)
    state = consume_free_scope_benefit(FreeBenefitState(pair_key=key))

    # Unbind: relationship REL_1 ends. Nothing about the benefit changes.
    plan_unbind(
        relationship_state=RelationshipState.ACTIVE.value,
        members=[ALICE, BOB],
        actor_id=ALICE,
        actor_kind="member",
        reason="break",
        key=key,
    )
    assert state.consumed == 1

    # Rebind as a brand-new relationship row, with the roles swapped so the
    # inviter/invitee ordering cannot be used to mint a second benefit either.
    rebound = decide_binding(
        inviter_id=BOB,
        invitee_id=ALICE,
        acceptor_id=ALICE,
        invitation_status=InvitationStatus.PENDING.value,
        relationship_kind="engaged",
        relationship_id=REL_2,
        acceptor_active_relationship_id=None,
        inviter_active_relationship_id=None,
        expires_at=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert rebound.pair_key == key  # same pair, different relationship row
    with pytest.raises(CoupleRuleError) as excinfo:
        decide_free_scope_grant(state)
    assert excinfo.value.code == "SCOPE_FREE_BENEFIT_CONSUMED"
    assert excinfo.value.details["pair_key"] == key
    with pytest.raises(CoupleRuleError):
        consume_free_scope_benefit(state)


def test_free_benefit_state_cannot_be_overdrawn_or_negative() -> None:
    with pytest.raises(CoupleRuleError) as overdrawn:
        FreeBenefitState(pair_key="k", granted=1, consumed=2)
    assert overdrawn.value.code == "SCOPE_FREE_BENEFIT_INVALID"
    with pytest.raises(CoupleRuleError):
        FreeBenefitState(pair_key="k", granted=-1)


# ---------------------------------------------------------------------------
# SCOPE-001 versioned question bank
# ---------------------------------------------------------------------------


def _question(index: int, dimension: ScopeDimension, **overrides: object) -> ScopeQuestionSpec:
    kwargs: dict[str, object] = {
        "question_id": _uid(5000 + index),
        "question_code": f"q{index}",
        "dimension": dimension,
        "weight": 1,
        "scale_min": 1,
        "scale_max": 5,
        "reverse_scored": False,
        "position": index,
    }
    kwargs.update(overrides)
    return ScopeQuestionSpec(**kwargs)  # type: ignore[arg-type]


def _version(**overrides: object) -> ScopeVersionSpec:
    questions = tuple(
        _question(index, dimension)
        for index, dimension in enumerate(SCOPE_DIMENSION_ORDER, start=1)
    )
    kwargs: dict[str, object] = {
        "version_code": "scope_core",
        "semantic_version": "1.0.0",
        "algorithm_version": "scope-v1",
        "questions": questions,
    }
    kwargs.update(overrides)
    return ScopeVersionSpec(**kwargs)  # type: ignore[arg-type]


def test_the_shipped_empty_question_bank_cannot_be_published() -> None:
    """DEC-001: no copyrighted questionnaire content ships with the platform."""

    with pytest.raises(CoupleRuleError) as excinfo:
        ensure_version_publishable(_version(questions=()))
    assert excinfo.value.code == "SCOPE_VERSION_EMPTY"


def test_all_five_dimensions_are_required_before_publication() -> None:
    partial = _version(
        questions=(
            _question(1, ScopeDimension.SUPPORT),
            _question(2, ScopeDimension.COMMUNICATION),
        )
    )
    with pytest.raises(CoupleRuleError) as excinfo:
        ensure_version_publishable(partial)
    assert excinfo.value.code == "SCOPE_VERSION_DIMENSION_MISSING"
    assert "outlook" in excinfo.value.details["missing_dimensions"]
    ensure_version_publishable(_version())


def test_duplicate_question_codes_and_bad_scales_are_rejected() -> None:
    with pytest.raises(CoupleRuleError) as duplicate:
        ScopeVersionSpec(
            version_code="v",
            semantic_version="1.0.0",
            algorithm_version="a",
            questions=(
                _question(1, ScopeDimension.SUPPORT),
                _question(1, ScopeDimension.OUTLOOK),
            ),
        )
    assert duplicate.value.code == "SCOPE_QUESTION_CODE_DUPLICATE"
    with pytest.raises(CoupleRuleError) as scale:
        _question(1, ScopeDimension.SUPPORT, scale_min=5, scale_max=5)
    assert scale.value.code == "SCOPE_QUESTION_SCALE_INVALID"
    with pytest.raises(CoupleRuleError) as weight:
        _question(1, ScopeDimension.SUPPORT, weight=0)
    assert weight.value.code == "SCOPE_QUESTION_WEIGHT_INVALID"


def test_answer_validation_rejects_unknown_out_of_range_and_missing() -> None:
    version = _version()
    complete = {f"q{index}": 3 for index in range(1, 6)}
    assert validate_scope_answers(version, complete) == complete
    with pytest.raises(CoupleRuleError) as unknown:
        validate_scope_answers(version, {**complete, "q99": 3})
    assert unknown.value.code == "SCOPE_ANSWER_QUESTION_UNKNOWN"
    with pytest.raises(CoupleRuleError) as out_of_range:
        validate_scope_answers(version, {**complete, "q1": 9})
    assert out_of_range.value.code == "SCOPE_ANSWER_OUT_OF_RANGE"
    with pytest.raises(CoupleRuleError) as missing:
        validate_scope_answers(version, {"q1": 3})
    assert missing.value.code == "SCOPE_ANSWER_MISSING"
    # A draft autosave tolerates gaps but still checks shape.
    assert validate_scope_answers(version, {"q1": 3}, partial=True) == {"q1": 3}
    with pytest.raises(CoupleRuleError) as boolean:
        validate_scope_answers(version, {"q1": True}, partial=True)
    assert boolean.value.code == "SCOPE_ANSWER_TYPE_INVALID"


# ---------------------------------------------------------------------------
# SCOPE-001 sealed answers
# ---------------------------------------------------------------------------


def test_a_partner_can_never_read_the_other_partners_raw_answers() -> None:
    """The seal (SCOPE-001): raw answers are readable only by their author."""

    ensure_raw_answers_readable(viewer_id=ALICE, owner_id=ALICE)
    with pytest.raises(CoupleRuleError) as partner:
        ensure_raw_answers_readable(viewer_id=BOB, owner_id=ALICE)
    assert partner.value.code == "SCOPE_ANSWERS_SEALED"
    assert partner.value.details["owner_id"] == str(ALICE)
    # An administrator is not an exception either.
    with pytest.raises(CoupleRuleError):
        ensure_raw_answers_readable(viewer_id=CAROL, owner_id=ALICE)


def test_the_partner_progress_view_exposes_progress_and_nothing_else() -> None:
    view = partner_progress_view(
        user_id=ALICE, status=ParticipantState.SUBMITTED.value, submitted_at=NOW
    )
    assert view == {
        "user_id": str(ALICE),
        "status": "submitted",
        "submitted_at": NOW,
        "answers_visible": False,
    }
    assert "answers" not in view


# ---------------------------------------------------------------------------
# SCOPE-001 completion barrier
# ---------------------------------------------------------------------------


def test_no_report_until_both_partners_submit() -> None:
    readiness = evaluate_report_readiness(
        expected_members=[ALICE, BOB],
        states={ALICE: ParticipantState.SUBMITTED.value},
    )
    assert readiness.ready is False
    assert readiness.waiting_on == (BOB,)
    assert readiness.reason_code == "AWAITING_PARTNER_SUBMISSION"
    with pytest.raises(CoupleRuleError) as excinfo:
        ensure_report_ready(readiness)
    assert excinfo.value.code == "SCOPE_REPORT_BARRIER"


def test_both_submitted_opens_the_barrier() -> None:
    readiness = evaluate_report_readiness(
        expected_members=[BOB, ALICE],
        states={
            ALICE: ParticipantState.SUBMITTED.value,
            BOB: ParticipantState.SUBMITTED.value,
        },
    )
    assert readiness.ready is True
    assert readiness.waiting_on == ()
    ensure_report_ready(readiness)


def test_a_submission_from_outside_the_relationship_is_refused() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        evaluate_report_readiness(
            expected_members=[ALICE, BOB],
            states={CAROL: ParticipantState.SUBMITTED.value},
        )
    assert excinfo.value.code == "SCOPE_PARTICIPANT_NOT_IN_RELATIONSHIP"


def test_a_scope_assessment_always_has_exactly_two_participants() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        evaluate_report_readiness(expected_members=[ALICE], states={})
    assert excinfo.value.code == "SCOPE_PARTICIPANTS_INVALID"


def test_assessment_state_machine_is_forward_only() -> None:
    validate_assessment_transition("collecting", "completed")
    validate_assessment_transition("completed", "report_ready")
    with pytest.raises(CoupleRuleError) as excinfo:
        validate_assessment_transition("report_ready", "collecting")
    assert excinfo.value.code == "SCOPE_ASSESSMENT_TRANSITION_INVALID"
    assert AssessmentState.CANCELLED.value == "cancelled"


def test_scope_requires_an_active_binding() -> None:
    ensure_scope_relationship_active(RelationshipState.ACTIVE.value)
    with pytest.raises(CoupleRuleError) as excinfo:
        ensure_scope_relationship_active(RelationshipState.UNBOUND.value)
    assert excinfo.value.code == "COUPLE_RELATIONSHIP_NOT_ACTIVE"


# ---------------------------------------------------------------------------
# SCOPE-001 deterministic scoring
# ---------------------------------------------------------------------------


def test_scoring_is_five_dimensional_and_normalized_to_0_100() -> None:
    version = _version()
    top = score_scope(version, {f"q{index}": 5 for index in range(1, 6)})
    bottom = score_scope(version, {f"q{index}": 1 for index in range(1, 6)})
    middle = score_scope(version, {f"q{index}": 3 for index in range(1, 6)})
    assert len(top.dimensions) == 5
    assert [score.dimension for score in top.dimensions] == list(SCOPE_DIMENSION_ORDER)
    assert top.composite == Decimal("100.00")
    assert bottom.composite == Decimal("0.00")
    assert middle.composite == Decimal("50.00")


def test_same_answers_and_version_reproduce_identical_scores_and_fingerprint() -> None:
    version = _version()
    answers = {"q1": 5, "q2": 2, "q3": 4, "q4": 1, "q5": 3}
    first = score_scope(version, answers)
    second = score_scope(version, dict(reversed(list(answers.items()))))
    assert first == second
    assert scores_fingerprint(first) == scores_fingerprint(second)
    assert first.algorithm_version == "scope-v1"


def test_a_different_algorithm_version_changes_the_fingerprint() -> None:
    answers = {"q1": 5, "q2": 2, "q3": 4, "q4": 1, "q5": 3}
    first = score_scope(_version(), answers)
    second = score_scope(_version(algorithm_version="scope-v2"), answers)
    assert first.by_dimension() == second.by_dimension()
    assert scores_fingerprint(first) != scores_fingerprint(second)


def test_reverse_scored_questions_are_mirrored_on_their_own_scale() -> None:
    questions = list(_version().questions)
    questions[0] = _question(1, ScopeDimension.SUPPORT, reverse_scored=True)
    version = _version(questions=tuple(questions))
    scores = score_scope(version, {f"q{index}": 5 for index in range(1, 6)})
    assert scores.by_dimension()["support"] == Decimal("0.00")
    assert scores.by_dimension()["communication"] == Decimal("100.00")


def test_weights_shift_a_dimension_score_predictably() -> None:
    questions = (
        _question(1, ScopeDimension.SUPPORT, weight=3),
        _question(6, ScopeDimension.SUPPORT, question_code="q6", weight=1),
        _question(2, ScopeDimension.COMMUNICATION),
        _question(3, ScopeDimension.OUTLOOK),
        _question(4, ScopeDimension.PARTNERSHIP),
        _question(5, ScopeDimension.EXPECTATIONS),
    )
    version = _version(questions=questions)
    answers = {"q1": 5, "q6": 1, "q2": 3, "q3": 3, "q4": 3, "q5": 3}
    scores = score_scope(version, answers)
    # raw = 3*5 + 1*1 = 16, min = 4, max = 20 -> (16-4)/16 * 100 = 75.00
    assert scores.by_dimension()["support"] == Decimal("75.00")


def test_scoring_an_unpublishable_version_is_refused() -> None:
    with pytest.raises(CoupleRuleError) as excinfo:
        score_scope(_version(questions=()), {})
    assert excinfo.value.code == "SCOPE_VERSION_EMPTY"


def test_alignment_is_a_distance_not_a_disclosure() -> None:
    version = _version()
    first = score_scope(version, {f"q{index}": 5 for index in range(1, 6)})
    second = score_scope(version, {f"q{index}": 3 for index in range(1, 6)})
    alignment = compute_alignment(first, second)
    assert len(alignment) == 5
    assert alignment[0].gap == Decimal("50.00")
    assert alignment[0].alignment == Decimal("50.00")


def test_alignment_across_algorithm_versions_is_refused() -> None:
    answers = {f"q{index}": 3 for index in range(1, 6)}
    first = score_scope(_version(), answers)
    second = score_scope(_version(algorithm_version="scope-v2"), answers)
    with pytest.raises(CoupleRuleError) as excinfo:
        compute_alignment(first, second)
    assert excinfo.value.code == "SCOPE_ALGORITHM_VERSION_MISMATCH"


# ---------------------------------------------------------------------------
# SCOPE-001 report assembly and AI advice separation
# ---------------------------------------------------------------------------


def test_ai_advice_is_stored_separately_from_the_deterministic_scores() -> None:
    version = _version()
    scores = {
        ALICE: score_scope(version, {f"q{index}": 4 for index in range(1, 6)}),
        BOB: score_scope(version, {f"q{index}": 2 for index in range(1, 6)}),
    }
    alignment = compute_alignment(scores[ALICE], scores[BOB])
    advice = AdviceBlock(
        body="model narrative",
        model_code="advice-model-1",
        prompt_version="p1",
        generated_at=NOW,
    )
    payload = assemble_report_payload(
        scores=scores, alignment=alignment, advice=advice, generated_at=NOW
    )
    assert set(payload) == {"scores", "advice", "advice_status"}
    assert payload["scores"]["deterministic"] is True
    assert "body" not in payload["scores"]
    assert "advice" not in payload["scores"]
    assert payload["advice"]["is_ai_generated"] is True
    assert payload["advice"]["body"] == "model narrative"
    assert payload["advice_status"] == "generated"


def test_a_report_without_advice_still_carries_the_full_scores() -> None:
    version = _version()
    scores = {ALICE: score_scope(version, {f"q{index}": 4 for index in range(1, 6)})}
    payload = assemble_report_payload(scores=scores, alignment=(), advice=None, generated_at=NOW)
    assert payload["advice"] is None
    assert payload["advice_status"] == "absent"
    assert payload["scores"]["members"][0]["fingerprint"]
    assert len(payload["scores"]["members"][0]["dimensions"]) == 5


def test_advice_blocks_must_be_non_empty_and_timezone_aware() -> None:
    with pytest.raises(CoupleRuleError) as empty:
        AdviceBlock(body="  ", model_code="m", prompt_version="p", generated_at=NOW)
    assert empty.value.code == "SCOPE_ADVICE_EMPTY"
    with pytest.raises(CoupleRuleError) as naive:
        AdviceBlock(
            body="ok",
            model_code="m",
            prompt_version="p",
            generated_at=datetime(2026, 8, 12, 12, 0),
        )
    assert naive.value.code == "COUPLE_NAIVE_DATETIME"


def test_report_key_is_stable_per_assessment_and_algorithm_version() -> None:
    assert report_idempotency_key(REL_1, "scope-v1") == report_idempotency_key(REL_1, "scope-v1")
    assert report_idempotency_key(REL_1, "scope-v1") != report_idempotency_key(REL_1, "scope-v2")
