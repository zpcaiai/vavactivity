"""Deterministic gap and orphan detectors."""

from __future__ import annotations

from vav.modules.quality.domain import (
    ApiArtifact,
    ArtifactInventory,
    CapabilityArtifact,
    CapabilityType,
    DeadLetterArtifact,
    EventArtifact,
    GapType,
    PageArtifact,
    PermissionArtifact,
    QualityCriticality,
    QualityRequirementStatus,
    RequirementArtifact,
    StateMachineArtifact,
    TableArtifact,
    critical_findings,
    detect_all_gaps,
    detect_missing_admin_capabilities,
    detect_missing_audit,
    detect_missing_erasure_paths,
    detect_missing_exception_paths,
    detect_missing_metrics,
    detect_missing_notifications,
    detect_missing_permissions,
    detect_mock_only_pages,
    detect_orphan_apis,
    detect_orphan_events,
    detect_orphan_pages,
    detect_orphan_permissions,
    detect_orphan_tables,
    detect_unconsumed_events,
    detect_unimplemented_requirements,
    detect_unreachable_terminal_states,
    detect_unresolved_dead_letters,
    detect_untested_states,
)


def test_orphan_page_requires_navigation_or_inbound_reference() -> None:
    linked = PageArtifact(
        code="PAGE-ADMIN-ORDERS",
        application="admin-web",
        route_path="/admin/orders",
        has_navigation_entry=True,
        query_apis=("API-ORDERS-LIST",),
    )
    orphan = PageArtifact(
        code="PAGE-ADMIN-LEGACY",
        application="admin-web",
        route_path="/admin/legacy",
        criticality=QualityCriticality.CRITICAL,
        query_apis=("API-ORDERS-LIST",),
    )
    findings = detect_orphan_pages([linked, orphan])
    assert [item.subject for item in findings] == ["PAGE-ADMIN-LEGACY"]
    assert findings[0].gap_type is GapType.ORPHAN_PAGE
    assert findings[0].severity is QualityCriticality.CRITICAL
    assert findings[0].gap_code == "GAP-ORPHAN-PAGE-PAGE-ADMIN-LEGACY"


def test_mock_only_page_is_detected() -> None:
    page = PageArtifact(
        code="PAGE-USER-WALLET",
        application="user-web",
        route_path="/wallet",
        has_navigation_entry=True,
    )
    assert (
        detect_mock_only_pages([page])[0].detection_rule_code == "RULE-MOCK-ONLY-PAGE"
    )


def test_orphan_api_requires_caller_or_declared_purpose() -> None:
    called = ApiArtifact(
        code="API-ORDERS-LIST",
        method="GET",
        path="/api/v1/orders",
        module="commerce",
        callers=("PAGE-ADMIN-ORDERS",),
    )
    internal = ApiArtifact(
        code="API-INTERNAL-REPLAY",
        method="POST",
        path="/internal/replay",
        module="commerce",
        internal_purpose="operator replay runbook",
    )
    orphan = ApiArtifact(
        code="API-ORDERS-LEGACY",
        method="GET",
        path="/api/v1/orders/legacy",
        module="commerce",
    )
    findings = detect_orphan_apis([called, internal, orphan])
    assert [item.subject for item in findings] == ["API-ORDERS-LEGACY"]


def test_sensitive_api_without_permission_is_blocker() -> None:
    api = ApiArtifact(
        code="API-CONTACT-REVEAL",
        method="POST",
        path="/api/v1/contact/reveal",
        module="matchmaking_interactions",
        is_command=True,
        sensitive=True,
    )
    finding = detect_missing_permissions([api])[0]
    assert finding.gap_type is GapType.MISSING_PERMISSION
    assert finding.severity is QualityCriticality.BLOCKER


def test_explicitly_public_api_needs_no_permission() -> None:
    api = ApiArtifact(
        code="API-HEALTH",
        method="GET",
        path="/health",
        module="system",
        is_public=True,
    )
    assert detect_missing_permissions([api]) == ()


def test_unaudited_write_api_is_detected() -> None:
    api = ApiArtifact(
        code="API-USER-SUSPEND",
        method="POST",
        path="/api/v1/admin/users/suspend",
        module="identity",
        criticality=QualityCriticality.CRITICAL,
        is_command=True,
        permissions=("users.suspend",),
    )
    assert detect_missing_audit([api])[0].gap_type is GapType.MISSING_AUDIT


def test_event_without_consumer_or_audit_purpose_is_orphan() -> None:
    consumed = EventArtifact(
        code="commerce.order.paid.v1",
        publishers=("commerce",),
        consumers=("memberships",),
        inbox_deduplicated=True,
    )
    audit_only = EventArtifact(
        code="safety.audit.recorded.v1", publishers=("trust_safety",), audit_only=True
    )
    orphan = EventArtifact(code="courses.lesson.viewed.v1", publishers=("courses",))
    assert [
        item.subject for item in detect_orphan_events([consumed, audit_only, orphan])
    ] == ["courses.lesson.viewed.v1"]


def test_consumer_without_inbox_deduplication_is_detected() -> None:
    event = EventArtifact(
        code="commerce.order.paid.v1",
        publishers=("commerce",),
        consumers=("memberships",),
    )
    finding = detect_unconsumed_events([event])[0]
    assert finding.detection_rule_code == "RULE-CONSUMER-WITHOUT-INBOX"


def test_unreferenced_permission_is_orphan() -> None:
    used = PermissionArtifact(code="quality.gates.execute", referencing_routes=("R1",))
    unused = PermissionArtifact(code="quality.legacy.read")
    assert [item.subject for item in detect_orphan_permissions([used, unused])] == [
        "quality.legacy.read"
    ]


def test_table_without_owner_and_retention_produces_two_findings() -> None:
    table = TableArtifact(code="quality_scratch", module="quality")
    kinds = {item.gap_type for item in detect_orphan_tables([table])}
    assert kinds == {GapType.ORPHAN_TABLE, GapType.MISSING_RETENTION_POLICY}


def test_personal_data_without_erasure_path_is_blocker() -> None:
    table = TableArtifact(
        code="dating_profiles",
        module="matchmaking_profiles",
        has_repository=True,
        retention_policy="P7Y",
        data_owner="matchmaking",
        holds_personal_data=True,
    )
    finding = detect_missing_erasure_paths([table])[0]
    assert finding.severity is QualityCriticality.BLOCKER
    assert finding.gap_type is GapType.MISSING_ERASURE_PATH


def test_untested_states_are_reported_individually() -> None:
    machine = StateMachineArtifact(
        code="SM-ORDER",
        module="commerce",
        criticality=QualityCriticality.BLOCKER,
        states=("pending", "paid", "refunded", "expired"),
        tested_states=("pending", "paid"),
        terminal_states=("refunded", "expired"),
    )
    subjects = {item.subject for item in detect_untested_states([machine])}
    assert subjects == {"SM-ORDER-refunded", "SM-ORDER-expired"}


def test_state_machine_without_terminal_state_is_blocker() -> None:
    machine = StateMachineArtifact(
        code="SM-INTRODUCTION",
        module="matchmaking_interactions",
        states=("draft", "sent"),
        tested_states=("draft", "sent"),
    )
    finding = detect_unreachable_terminal_states([machine])[0]
    assert finding.severity is QualityCriticality.BLOCKER


def test_user_action_without_admin_counterpart_is_detected() -> None:
    capability = CapabilityArtifact(
        code="CAP-ACTIVITY-CHECKIN",
        capability_type=CapabilityType.USER_ACTION,
        criticality=QualityCriticality.CRITICAL,
    )
    assert detect_missing_admin_capabilities([capability])[0].gap_type is (
        GapType.MISSING_ADMIN_CAPABILITY
    )


def test_critical_capability_without_exception_scenario_is_detected() -> None:
    capability = CapabilityArtifact(
        code="CAP-COMMERCE-CHECKOUT",
        capability_type=CapabilityType.USER_ACTION,
        criticality=QualityCriticality.BLOCKER,
        admin_capabilities=("CAP-COMMERCE-REFUND",),
    )
    assert (
        detect_missing_exception_paths([capability])[0].severity
        is QualityCriticality.BLOCKER
    )


def test_async_capability_without_metric_is_detected() -> None:
    capability = CapabilityArtifact(
        code="CAP-RECOMMENDATION-BATCH-GENERATE",
        capability_type=CapabilityType.SCHEDULED_JOB,
        criticality=QualityCriticality.CRITICAL,
    )
    assert detect_missing_metrics([capability])[0].gap_type is GapType.MISSING_METRIC


def test_critical_user_capability_without_notification_is_detected() -> None:
    capability = CapabilityArtifact(
        code="CAP-MEMBERSHIP-UPGRADE",
        capability_type=CapabilityType.USER_ACTION,
        criticality=QualityCriticality.BLOCKER,
        admin_capabilities=("CAP-MEMBERSHIP-ADJUST",),
        exception_scenarios=("EXC-MEMBERSHIP-PAYMENT-FAILED",),
    )
    assert (
        detect_missing_notifications([capability])[0].gap_type
        is GapType.MISSING_NOTIFICATION
    )


def test_open_dead_letters_are_reported() -> None:
    queues = [
        DeadLetterArtifact(queue="commerce.webhook", open_count=0),
        DeadLetterArtifact(
            queue="privacy.erasure",
            open_count=3,
            criticality=QualityCriticality.BLOCKER,
        ),
    ]
    findings = detect_unresolved_dead_letters(queues)
    assert [item.subject for item in findings] == ["privacy.erasure"]
    assert findings[0].severity is QualityCriticality.BLOCKER


def test_implemented_but_unverified_requirement_is_separated() -> None:
    requirements = [
        RequirementArtifact(
            code="REQ-VAV-COMMERCE-001",
            criticality=QualityCriticality.BLOCKER,
            status=QualityRequirementStatus.IMPLEMENTED,
            capabilities=("CAP-COMMERCE-CHECKOUT",),
        ),
        RequirementArtifact(
            code="REQ-VAV-COMMERCE-002",
            criticality=QualityCriticality.BLOCKER,
            status=QualityRequirementStatus.APPROVED,
        ),
    ]
    findings = {
        item.subject: item.gap_type
        for item in detect_unimplemented_requirements(requirements)
    }
    assert findings["REQ-VAV-COMMERCE-001"] is GapType.UNVERIFIED_REQUIREMENT
    assert findings["REQ-VAV-COMMERCE-002"] is GapType.UNIMPLEMENTED_REQUIREMENT


def test_detect_all_gaps_is_deterministic_and_deduplicated() -> None:
    inventory = ArtifactInventory(
        requirements=(
            RequirementArtifact(
                code="REQ-VAV-QUALITY-001",
                criticality=QualityCriticality.BLOCKER,
                status=QualityRequirementStatus.APPROVED,
            ),
        ),
        pages=(PageArtifact(code="PAGE-X", application="admin-web", route_path="/x"),),
        apis=(
            ApiArtifact(
                code="API-X",
                method="POST",
                path="/x",
                module="quality",
                is_command=True,
            ),
        ),
        events=(
            EventArtifact(code="quality.gap.detected.v1", publishers=("quality",)),
        ),
        permissions=(PermissionArtifact(code="quality.unused"),),
        tables=(TableArtifact(code="quality_tmp", module="quality"),),
        state_machines=(
            StateMachineArtifact(code="SM-GATE", module="quality", states=("pending",)),
        ),
        capabilities=(
            CapabilityArtifact(
                code="CAP-QUALITY-EVALUATE",
                capability_type=CapabilityType.USER_ACTION,
                criticality=QualityCriticality.BLOCKER,
            ),
        ),
        dead_letters=(DeadLetterArtifact(queue="quality.sync", open_count=1),),
    )
    first = detect_all_gaps(inventory)
    second = detect_all_gaps(inventory)
    assert first == second
    assert len({item.gap_code for item in first}) == len(first)
    assert list(first) == sorted(first, key=lambda item: item.gap_code)
    assert critical_findings(first)
    kinds = {item.gap_type for item in first}
    for expected in (
        GapType.ORPHAN_PAGE,
        GapType.ORPHAN_API,
        GapType.ORPHAN_EVENT,
        GapType.ORPHAN_PERMISSION,
        GapType.ORPHAN_TABLE,
        GapType.MISSING_AUDIT,
        GapType.MISSING_PERMISSION,
        GapType.MISSING_ADMIN_CAPABILITY,
        GapType.MISSING_EXCEPTION_PATH,
        GapType.MISSING_TEST,
        GapType.MISSING_EVIDENCE,
        GapType.UNTESTED_STATE,
        GapType.UNRESOLVED_DEAD_LETTER,
        GapType.UNIMPLEMENTED_REQUIREMENT,
    ):
        assert expected in kinds, expected


def test_clean_inventory_produces_no_gaps() -> None:
    inventory = ArtifactInventory(
        requirements=(
            RequirementArtifact(
                code="REQ-VAV-QUALITY-001",
                criticality=QualityCriticality.BLOCKER,
                status=QualityRequirementStatus.VERIFIED,
                capabilities=("CAP-QUALITY-EVALUATE",),
                tests=("tests/quality/gates/test_go_no_go_decision.py",),
                evidence=("EVID-QUALITY-001",),
                owner_team="quality_engineering",
            ),
        ),
        pages=(
            PageArtifact(
                code="PAGE-ADMIN-QUALITY",
                application="admin-web",
                route_path="/admin/quality/dashboard",
                has_navigation_entry=True,
                query_apis=("API-QUALITY-DASHBOARD",),
                required_permissions=("quality.analytics.read",),
            ),
        ),
        apis=(
            ApiArtifact(
                code="API-QUALITY-DASHBOARD",
                method="GET",
                path="/api/v1/admin/quality/dashboard",
                module="quality",
                callers=("PAGE-ADMIN-QUALITY",),
                permissions=("quality.analytics.read",),
            ),
        ),
        events=(
            EventArtifact(
                code="quality.gate.evaluated.v1",
                publishers=("quality",),
                consumers=("system",),
                inbox_deduplicated=True,
            ),
        ),
        permissions=(
            PermissionArtifact(
                code="quality.analytics.read",
                referencing_routes=("API-QUALITY-DASHBOARD",),
            ),
        ),
        tables=(
            TableArtifact(
                code="quality_gate_runs",
                module="quality",
                has_repository=True,
                retention_policy="P3Y",
                data_owner="quality_engineering",
            ),
        ),
        state_machines=(
            StateMachineArtifact(
                code="SM-GATE-RUN",
                module="quality",
                states=("pending", "passed", "failed"),
                tested_states=("pending", "passed", "failed"),
                terminal_states=("passed", "failed"),
            ),
        ),
        capabilities=(
            CapabilityArtifact(
                code="CAP-QUALITY-EVALUATE",
                capability_type=CapabilityType.ADMIN_ACTION,
                criticality=QualityCriticality.BLOCKER,
                exception_scenarios=("EXC-QUALITY-EVIDENCE-MISSING",),
                metrics=("quality_gate_runs_total",),
                tests=("tests/quality/gates/test_go_no_go_decision.py",),
                audited=True,
            ),
        ),
        dead_letters=(DeadLetterArtifact(queue="quality.sync", open_count=0),),
    )
    assert detect_all_gaps(inventory) == ()
