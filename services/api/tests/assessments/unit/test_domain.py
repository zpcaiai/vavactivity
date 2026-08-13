"""Pure-domain tests for the paid assessment framework (B17)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from vav.modules.assessments.domain import (
    AdviceBlock,
    AssessmentQuestionSpec,
    AssessmentRuleError,
    AssessmentVersionSpec,
    AttemptAction,
    AttemptStatus,
    ContentSource,
    EntitlementState,
    EntitlementStatus,
    LicenseRecord,
    ProductStatus,
    ReportAction,
    ReportStatus,
    VersionStatus,
    assemble_report_payload,
    attempt_idempotency_key,
    build_purchase_intent,
    catalogue_view,
    ensure_entitlement_usable,
    ensure_license_recorded,
    ensure_refund_window_open,
    ensure_report_readable,
    ensure_version_matches_entitlement,
    ensure_version_publishable,
    plan_revocation,
    purchase_idempotency_key,
    report_idempotency_key,
    score_attempt,
    scores_fingerprint,
    validate_attempt_answers,
    validate_attempt_transition,
    validate_purchase_transition,
    validate_version_transition,
)

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _uid(value: int) -> UUID:
    return UUID(int=value)


MEMBER = _uid(1)
OTHER = _uid(2)
ADMIN = _uid(9)
PRODUCT = _uid(100)
VERSION_1 = _uid(201)
VERSION_2 = _uid(202)
ENTITLEMENT = _uid(300)
ATTEMPT = _uid(400)


def _license(**overrides: object) -> LicenseRecord:
    kwargs: dict[str, object] = {
        "content_source": ContentSource.LICENSED_THIRD_PARTY,
        "license_reference": "CONTRACT-2026-0042",
        "license_verified_at": NOW - timedelta(days=1),
        "license_verified_by": ADMIN,
        "licensor_name": "Example Licensor Ltd",
    }
    kwargs.update(overrides)
    return LicenseRecord(**kwargs)  # type: ignore[arg-type]


def _question(index: int, dimension: str, **overrides: object) -> AssessmentQuestionSpec:
    kwargs: dict[str, object] = {
        "question_id": _uid(5000 + index),
        "question_code": f"q{index}",
        "dimension_code": dimension,
        "weight": 1,
        "scale_min": 1,
        "scale_max": 5,
        "reverse_scored": False,
        "position": index,
    }
    kwargs.update(overrides)
    return AssessmentQuestionSpec(**kwargs)  # type: ignore[arg-type]


def _version(**overrides: object) -> AssessmentVersionSpec:
    kwargs: dict[str, object] = {
        "version_id": VERSION_1,
        "product_id": PRODUCT,
        "semantic_version": "1.0.0",
        "algorithm_version": "generic-v1",
        "license": _license(),
        "price_minor_units": 4900,
        "currency": "CNY",
        "questions": (_question(1, "alpha"), _question(2, "alpha"), _question(3, "beta")),
    }
    kwargs.update(overrides)
    return AssessmentVersionSpec(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ASSESS-001 licensing gate
# ---------------------------------------------------------------------------


def test_publishing_a_version_without_a_license_reference_is_rejected() -> None:
    """The rule the whole framework exists for (ASSESS-001)."""

    with pytest.raises(AssessmentRuleError) as excinfo:
        ensure_version_publishable(_version(license=_license(license_reference=None)), now=NOW)
    assert excinfo.value.code == "ASSESSMENT_LICENSE_REFERENCE_REQUIRED"
    with pytest.raises(AssessmentRuleError) as blank:
        ensure_version_publishable(_version(license=_license(license_reference="   ")), now=NOW)
    assert blank.value.code == "ASSESSMENT_LICENSE_REFERENCE_REQUIRED"


def test_even_administrator_authored_content_needs_a_recorded_reference() -> None:
    with pytest.raises(AssessmentRuleError) as excinfo:
        ensure_version_publishable(
            _version(
                license=_license(
                    content_source=ContentSource.ADMINISTRATOR_AUTHORED,
                    license_reference=None,
                    licensor_name=None,
                )
            ),
            now=NOW,
        )
    assert excinfo.value.code == "ASSESSMENT_LICENSE_REFERENCE_REQUIRED"
    # With a reference it publishes fine, and no licensor is needed in-house.
    ensure_version_publishable(
        _version(
            license=_license(
                content_source=ContentSource.ADMINISTRATOR_AUTHORED,
                license_reference="INTERNAL-AUTHORSHIP-77",
                licensor_name=None,
            )
        ),
        now=NOW,
    )


def test_an_unverified_reference_is_not_enough() -> None:
    with pytest.raises(AssessmentRuleError) as missing_time:
        ensure_license_recorded(_license(license_verified_at=None), now=NOW)
    assert missing_time.value.code == "ASSESSMENT_LICENSE_NOT_VERIFIED"
    with pytest.raises(AssessmentRuleError) as missing_admin:
        ensure_license_recorded(_license(license_verified_by=None), now=NOW)
    assert missing_admin.value.code == "ASSESSMENT_LICENSE_NOT_VERIFIED"


def test_a_verification_timestamp_in_the_future_is_refused() -> None:
    with pytest.raises(AssessmentRuleError) as excinfo:
        ensure_license_recorded(_license(license_verified_at=NOW + timedelta(days=1)), now=NOW)
    assert excinfo.value.code == "ASSESSMENT_LICENSE_VERIFIED_IN_FUTURE"


def test_third_party_content_must_name_its_licensor() -> None:
    with pytest.raises(AssessmentRuleError) as excinfo:
        ensure_license_recorded(_license(licensor_name=" "), now=NOW)
    assert excinfo.value.code == "ASSESSMENT_LICENSOR_REQUIRED"


def test_license_record_completeness_helper() -> None:
    assert _license().is_complete() is True
    assert _license(license_reference=None).is_complete() is False
    assert _license(license_verified_by=None).is_complete() is False


def test_an_empty_or_free_version_cannot_be_published() -> None:
    with pytest.raises(AssessmentRuleError) as empty:
        ensure_version_publishable(_version(questions=()), now=NOW)
    assert empty.value.code == "ASSESSMENT_VERSION_EMPTY"
    with pytest.raises(AssessmentRuleError) as price:
        ensure_version_publishable(_version(price_minor_units=0), now=NOW)
    assert price.value.code == "ASSESSMENT_PRICE_REQUIRED"


def test_published_versions_are_immutable_and_only_retire() -> None:
    validate_version_transition("draft", "published")
    validate_version_transition("published", "retired")
    with pytest.raises(AssessmentRuleError) as excinfo:
        validate_version_transition("published", "draft")
    assert excinfo.value.code == "ASSESSMENT_VERSION_TRANSITION_INVALID"


def test_version_spec_validates_prices_currency_and_codes() -> None:
    with pytest.raises(AssessmentRuleError) as duplicate:
        _version(questions=(_question(1, "alpha"), _question(1, "beta")))
    assert duplicate.value.code == "ASSESSMENT_QUESTION_CODE_DUPLICATE"
    with pytest.raises(AssessmentRuleError) as currency:
        _version(currency="rmb")
    assert currency.value.code == "ASSESSMENT_CURRENCY_INVALID"
    with pytest.raises(AssessmentRuleError) as negative:
        _version(price_minor_units=-1)
    assert negative.value.code == "ASSESSMENT_PRICE_INVALID"
    with pytest.raises(AssessmentRuleError) as dimension:
        _question(1, "  ")
    assert dimension.value.code == "ASSESSMENT_QUESTION_DIMENSION_REQUIRED"


def test_members_never_see_unpublished_versions_in_the_catalogue() -> None:
    rows = [
        {"id": str(VERSION_1), "status": "published"},
        {"id": str(VERSION_2), "status": "draft"},
    ]
    assert len(catalogue_view(rows)) == 1
    assert len(catalogue_view(rows, include_unpublished=True)) == 2


# ---------------------------------------------------------------------------
# ASSESS-001 purchase pins exactly one version
# ---------------------------------------------------------------------------


def test_a_purchase_pins_the_exact_version_bought() -> None:
    intent = build_purchase_intent(
        _version(),
        user_id=MEMBER,
        order_id="ORD-1",
        version_status=VersionStatus.PUBLISHED.value,
        product_status=ProductStatus.ACTIVE.value,
        quoted_price_minor_units=4900,
    )
    assert intent.version_id == VERSION_1
    assert intent.semantic_version == "1.0.0"
    assert intent.algorithm_version == "generic-v1"
    assert intent.attempts_granted == 1
    assert intent.idempotency_key == purchase_idempotency_key(MEMBER, "ORD-1")


def test_publishing_a_newer_version_never_drifts_an_existing_entitlement() -> None:
    """No 'latest version' drift after purchase (ASSESS-001)."""

    ensure_version_matches_entitlement(
        entitlement_version_id=VERSION_1, requested_version_id=VERSION_1
    )
    with pytest.raises(AssessmentRuleError) as excinfo:
        ensure_version_matches_entitlement(
            entitlement_version_id=VERSION_1, requested_version_id=VERSION_2
        )
    assert excinfo.value.code == "ASSESSMENT_VERSION_DRIFT"
    assert excinfo.value.details["entitled_version_id"] == str(VERSION_1)


def test_only_published_versions_of_active_products_can_be_bought() -> None:
    with pytest.raises(AssessmentRuleError) as draft:
        build_purchase_intent(
            _version(),
            user_id=MEMBER,
            order_id="ORD-1",
            version_status=VersionStatus.DRAFT.value,
            product_status=ProductStatus.ACTIVE.value,
            quoted_price_minor_units=4900,
        )
    assert draft.value.code == "ASSESSMENT_VERSION_NOT_PURCHASABLE"
    with pytest.raises(AssessmentRuleError) as retired:
        build_purchase_intent(
            _version(),
            user_id=MEMBER,
            order_id="ORD-1",
            version_status=VersionStatus.PUBLISHED.value,
            product_status=ProductStatus.RETIRED.value,
            quoted_price_minor_units=4900,
        )
    assert retired.value.code == "ASSESSMENT_PRODUCT_NOT_ACTIVE"


def test_a_stale_quoted_price_is_refused() -> None:
    with pytest.raises(AssessmentRuleError) as excinfo:
        build_purchase_intent(
            _version(),
            user_id=MEMBER,
            order_id="ORD-1",
            version_status=VersionStatus.PUBLISHED.value,
            product_status=ProductStatus.ACTIVE.value,
            quoted_price_minor_units=100,
        )
    assert excinfo.value.code == "ASSESSMENT_PRICE_MISMATCH"


def test_purchase_key_is_per_order_so_a_replayed_callback_is_safe() -> None:
    assert purchase_idempotency_key(MEMBER, "ORD-1") == purchase_idempotency_key(MEMBER, "ORD-1")
    assert purchase_idempotency_key(MEMBER, "ORD-1") != purchase_idempotency_key(MEMBER, "ORD-2")
    assert attempt_idempotency_key(ENTITLEMENT, 1) != attempt_idempotency_key(ENTITLEMENT, 2)


def test_purchase_state_machine() -> None:
    validate_purchase_transition("pending", "paid")
    validate_purchase_transition("paid", "refunded")
    with pytest.raises(AssessmentRuleError) as excinfo:
        validate_purchase_transition("refunded", "paid")
    assert excinfo.value.code == "ASSESSMENT_PURCHASE_TRANSITION_INVALID"


# ---------------------------------------------------------------------------
# ASSESS-001 entitlement usability
# ---------------------------------------------------------------------------


def _entitlement(**overrides: object) -> EntitlementState:
    kwargs: dict[str, object] = {
        "entitlement_id": ENTITLEMENT,
        "user_id": MEMBER,
        "version_id": VERSION_1,
        "status": EntitlementStatus.ACTIVE,
        "attempts_granted": 1,
        "attempts_consumed": 0,
        "expires_at": None,
    }
    kwargs.update(overrides)
    return EntitlementState(**kwargs)  # type: ignore[arg-type]


def test_an_active_unused_entitlement_is_usable() -> None:
    ensure_entitlement_usable(_entitlement(), now=NOW)
    assert _entitlement().attempts_remaining == 1


def test_revoked_expired_and_exhausted_entitlements_are_refused() -> None:
    with pytest.raises(AssessmentRuleError) as revoked:
        ensure_entitlement_usable(_entitlement(status=EntitlementStatus.REVOKED), now=NOW)
    assert revoked.value.code == "ASSESSMENT_ENTITLEMENT_REVOKED"
    with pytest.raises(AssessmentRuleError) as expired:
        ensure_entitlement_usable(_entitlement(expires_at=NOW - timedelta(seconds=1)), now=NOW)
    assert expired.value.code == "ASSESSMENT_ENTITLEMENT_EXPIRED"
    with pytest.raises(AssessmentRuleError) as exhausted:
        ensure_entitlement_usable(_entitlement(attempts_consumed=1), now=NOW)
    assert exhausted.value.code == "ASSESSMENT_ENTITLEMENT_EXHAUSTED"


def test_naive_expiry_is_rejected_rather_than_assumed_utc() -> None:
    with pytest.raises(AssessmentRuleError) as excinfo:
        ensure_entitlement_usable(_entitlement(expires_at=datetime(2026, 8, 1, 0, 0)), now=NOW)
    assert excinfo.value.code == "ASSESSMENT_NAIVE_DATETIME"


# ---------------------------------------------------------------------------
# ASSESS-001 attempts and scoring
# ---------------------------------------------------------------------------


def test_attempt_state_machine_allows_voiding_from_every_live_state() -> None:
    validate_attempt_transition("in_progress", "submitted")
    validate_attempt_transition("submitted", "scored")
    validate_attempt_transition("in_progress", "voided")
    validate_attempt_transition("scored", "voided")
    with pytest.raises(AssessmentRuleError) as excinfo:
        validate_attempt_transition("voided", "in_progress")
    assert excinfo.value.code == "ASSESSMENT_ATTEMPT_TRANSITION_INVALID"


def test_answers_are_validated_against_the_purchased_version() -> None:
    version = _version()
    complete = {"q1": 3, "q2": 4, "q3": 5}
    assert validate_attempt_answers(version, complete) == complete
    with pytest.raises(AssessmentRuleError) as unknown:
        validate_attempt_answers(version, {**complete, "q9": 1})
    assert unknown.value.code == "ASSESSMENT_ANSWER_QUESTION_UNKNOWN"
    with pytest.raises(AssessmentRuleError) as missing:
        validate_attempt_answers(version, {"q1": 3})
    assert missing.value.code == "ASSESSMENT_ANSWER_MISSING"
    with pytest.raises(AssessmentRuleError) as out_of_range:
        validate_attempt_answers(version, {**complete, "q1": 99})
    assert out_of_range.value.code == "ASSESSMENT_ANSWER_OUT_OF_RANGE"
    assert validate_attempt_answers(version, {"q1": 3}, partial=True) == {"q1": 3}


def test_scoring_is_reproducible_and_uses_the_versions_own_dimensions() -> None:
    version = _version()
    answers = {"q1": 5, "q2": 5, "q3": 1}
    first = score_attempt(version, answers)
    second = score_attempt(version, dict(reversed(list(answers.items()))))
    assert first == second
    assert scores_fingerprint(first) == scores_fingerprint(second)
    assert [item.dimension_code for item in first.dimensions] == ["alpha", "beta"]
    assert first.dimensions[0].normalized == Decimal("100.00")
    assert first.dimensions[1].normalized == Decimal("0.00")


def test_reverse_scored_items_are_mirrored() -> None:
    version = _version(questions=(_question(1, "alpha", reverse_scored=True), _question(3, "beta")))
    scores = score_attempt(version, {"q1": 5, "q3": 5})
    assert scores.dimensions[0].normalized == Decimal("0.00")
    assert scores.dimensions[1].normalized == Decimal("100.00")


def test_report_payload_separates_scores_from_ai_advice() -> None:
    scores = score_attempt(_version(), {"q1": 3, "q2": 3, "q3": 3})
    advice = AdviceBlock(body="narrative", model_code="m1", prompt_version="p1", generated_at=NOW)
    payload = assemble_report_payload(scores=scores, advice=advice, generated_at=NOW)
    assert set(payload) == {"scores", "advice"}
    assert payload["scores"]["deterministic"] is True
    assert "body" not in payload["scores"]
    assert payload["advice"]["is_ai_generated"] is True
    plain = assemble_report_payload(scores=scores, advice=None, generated_at=NOW)
    assert plain["advice"] is None
    assert plain["scores"]["fingerprint"] == scores_fingerprint(scores)


def test_report_key_is_stable_per_attempt_and_algorithm_version() -> None:
    assert report_idempotency_key(ATTEMPT, "generic-v1") == report_idempotency_key(
        ATTEMPT, "generic-v1"
    )
    assert report_idempotency_key(ATTEMPT, "generic-v1") != report_idempotency_key(
        ATTEMPT, "generic-v2"
    )


# ---------------------------------------------------------------------------
# ASSESS-001 refund and revocation
# ---------------------------------------------------------------------------


def test_refund_before_any_attempt_revokes_the_entitlement_and_touches_nothing_else() -> None:
    plan = plan_revocation(trigger="member_request", attempt_status=None, report_status=None)
    assert plan.entitlement_status is EntitlementStatus.REVOKED
    assert plan.attempt_action is AttemptAction.NONE
    assert plan.report_action is ReportAction.NONE
    assert plan.refund_allowed is True
    assert plan.reason_code == "REFUND_BEFORE_DELIVERY"


def test_refund_voids_an_in_progress_attempt() -> None:
    plan = plan_revocation(
        trigger="member_request",
        attempt_status=AttemptStatus.IN_PROGRESS.value,
        report_status=None,
    )
    assert plan.attempt_action is AttemptAction.VOID
    assert plan.refund_allowed is True


def test_a_finished_attempt_is_retained_sealed_not_deleted() -> None:
    plan = plan_revocation(
        trigger="payment_reversal",
        attempt_status=AttemptStatus.SCORED.value,
        report_status=None,
    )
    assert plan.attempt_action is AttemptAction.RETAIN_SEALED


def test_a_delivered_report_blocks_a_plain_member_refund() -> None:
    plan = plan_revocation(
        trigger="member_request",
        attempt_status=AttemptStatus.SCORED.value,
        report_status=ReportStatus.GENERATED.value,
    )
    assert plan.refund_allowed is False
    assert plan.reason_code == "REPORT_ALREADY_DELIVERED"
    # The report row is still retained; only access goes away.
    assert plan.report_action is ReportAction.REVOKE_ACCESS
    assert plan.entitlement_status is EntitlementStatus.REVOKED


def test_a_delivered_report_can_still_be_refunded_by_override_or_force() -> None:
    goodwill = plan_revocation(
        trigger="admin_goodwill",
        attempt_status=AttemptStatus.SCORED.value,
        report_status=ReportStatus.GENERATED.value,
        admin_override=True,
        reason="support escalation 4471",
    )
    assert goodwill.refund_allowed is True
    assert goodwill.reason_code == "REFUND_GOODWILL_OVERRIDE"
    reversal = plan_revocation(
        trigger="payment_reversal",
        attempt_status=AttemptStatus.SCORED.value,
        report_status=ReportStatus.GENERATED.value,
    )
    assert reversal.refund_allowed is True
    withdrawn = plan_revocation(
        trigger="license_withdrawn",
        attempt_status=AttemptStatus.SCORED.value,
        report_status=ReportStatus.GENERATED.value,
    )
    assert withdrawn.refund_allowed is True
    assert withdrawn.report_action is ReportAction.REVOKE_ACCESS


def test_a_goodwill_override_on_a_delivered_report_needs_a_written_reason() -> None:
    with pytest.raises(AssessmentRuleError) as excinfo:
        plan_revocation(
            trigger="admin_goodwill",
            attempt_status=AttemptStatus.SCORED.value,
            report_status=ReportStatus.GENERATED.value,
            admin_override=True,
            reason="x",
        )
    assert excinfo.value.code == "ASSESSMENT_REFUND_REASON_REQUIRED"


def test_unknown_refund_trigger_is_refused() -> None:
    with pytest.raises(AssessmentRuleError) as excinfo:
        plan_revocation(trigger="because", attempt_status=None, report_status=None)
    assert excinfo.value.code == "ASSESSMENT_REFUND_TRIGGER_UNKNOWN"


def test_self_service_refund_window_is_time_boxed() -> None:
    ensure_refund_window_open(purchased_at=NOW - timedelta(hours=10), now=NOW, window_hours=72)
    with pytest.raises(AssessmentRuleError) as closed:
        ensure_refund_window_open(purchased_at=NOW - timedelta(hours=100), now=NOW, window_hours=72)
    assert closed.value.code == "ASSESSMENT_REFUND_WINDOW_CLOSED"
    with pytest.raises(AssessmentRuleError) as disabled:
        ensure_refund_window_open(purchased_at=NOW, now=NOW, window_hours=0)
    assert disabled.value.code == "ASSESSMENT_REFUND_WINDOW_CLOSED"


# ---------------------------------------------------------------------------
# ASSESS-001 report access
# ---------------------------------------------------------------------------


def test_a_report_is_readable_only_by_its_owner_while_still_granted() -> None:
    ensure_report_readable(
        viewer_id=MEMBER,
        owner_id=MEMBER,
        report_status=ReportStatus.GENERATED.value,
        entitlement_status=EntitlementStatus.ACTIVE.value,
    )
    with pytest.raises(AssessmentRuleError) as other:
        ensure_report_readable(
            viewer_id=OTHER,
            owner_id=MEMBER,
            report_status=ReportStatus.GENERATED.value,
            entitlement_status=EntitlementStatus.ACTIVE.value,
        )
    assert other.value.code == "ASSESSMENT_REPORT_FORBIDDEN"
    with pytest.raises(AssessmentRuleError) as revoked_report:
        ensure_report_readable(
            viewer_id=MEMBER,
            owner_id=MEMBER,
            report_status=ReportStatus.REVOKED.value,
            entitlement_status=EntitlementStatus.ACTIVE.value,
        )
    assert revoked_report.value.code == "ASSESSMENT_REPORT_REVOKED"
    with pytest.raises(AssessmentRuleError) as revoked_entitlement:
        ensure_report_readable(
            viewer_id=MEMBER,
            owner_id=MEMBER,
            report_status=ReportStatus.GENERATED.value,
            entitlement_status=EntitlementStatus.REVOKED.value,
        )
    assert revoked_entitlement.value.code == "ASSESSMENT_ENTITLEMENT_REVOKED"
