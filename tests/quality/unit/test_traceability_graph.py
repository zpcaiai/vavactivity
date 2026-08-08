"""Traceability graph algorithms: reachability, direction, cycles and breaks."""

from __future__ import annotations

import pytest

from vav.modules.quality.domain import (
    QualityPolicyError,
    TraceLink,
    TraceNode,
    TraceNodeType,
    analyze_traceability,
    detect_dangling_links,
    detect_trace_cycles,
    traceability_downstream,
    traceability_upstream,
    unreachable_nodes,
)

FULL_CHAIN: tuple[tuple[str, TraceNodeType], ...] = (
    ("REQ-VAV-COMMERCE-001", TraceNodeType.REQUIREMENT),
    ("CAP-COMMERCE-CHECKOUT", TraceNodeType.CAPABILITY),
    ("FLOW-COMMERCE-PURCHASE", TraceNodeType.BUSINESS_FLOW),
    ("API-COMMERCE-CHECKOUT", TraceNodeType.API),
    ("SVC-COMMERCE-CHECKOUT", TraceNodeType.APPLICATION_SERVICE),
    ("SM-ORDER", TraceNodeType.STATE_MACHINE),
    ("TBL-ORDERS", TraceNodeType.DATABASE_TABLE),
    ("EVT-ORDER-PAID", TraceNodeType.EVENT),
    ("PERM-COMMERCE-CHECKOUT", TraceNodeType.PERMISSION),
    ("MET-ORDER-PAID", TraceNodeType.METRIC),
    ("TEST-COMMERCE-CHECKOUT", TraceNodeType.TEST),
    ("EVID-COMMERCE-CHECKOUT", TraceNodeType.EVIDENCE),
)

REQUIRED_TYPES = frozenset(node_type for _, node_type in FULL_CHAIN)


def _nodes() -> list[TraceNode]:
    return [TraceNode(code=code, node_type=node_type) for code, node_type in FULL_CHAIN]


def _links(*, verified: bool = True) -> list[TraceLink]:
    codes = [code for code, _ in FULL_CHAIN]
    relationships = [
        "implements",
        "implements",
        "exposes",
        "invokes",
        "depends_on",
        "persists_to",
        "publishes",
        "requires_permission",
        "observed_by",
        "verified_by",
        "evidenced_by",
    ]
    return [
        TraceLink(
            source=codes[index],
            target=codes[index + 1],
            relationship=relationships[index],
            required=True,
            verified=verified,
        )
        for index in range(len(relationships))
    ]


def test_complete_chain_is_complete() -> None:
    analysis = analyze_traceability(
        _nodes(),
        _links(),
        root_code="REQ-VAV-COMMERCE-001",
        required_types=REQUIRED_TYPES,
    )
    assert analysis.complete is True
    assert analysis.missing_required_targets == ()
    assert len(analysis.reachable) == len(FULL_CHAIN)


def test_unverified_required_link_blocks_completeness() -> None:
    analysis = analyze_traceability(
        _nodes(),
        _links(verified=False),
        root_code="REQ-VAV-COMMERCE-001",
        required_types=REQUIRED_TYPES,
    )
    assert analysis.complete is False
    assert analysis.unverified_links


def test_missing_evidence_node_is_reported_as_missing_type() -> None:
    nodes = [node for node in _nodes() if node.node_type is not TraceNodeType.EVIDENCE]
    links = [link for link in _links() if link.target != "EVID-COMMERCE-CHECKOUT"]
    analysis = analyze_traceability(
        nodes,
        links,
        root_code="REQ-VAV-COMMERCE-001",
        required_types=REQUIRED_TYPES,
    )
    assert "evidence" in analysis.missing_required_targets
    assert analysis.complete is False


def test_downstream_and_upstream_are_bidirectional() -> None:
    links = _links()
    downstream = traceability_downstream(links, root_code="REQ-VAV-COMMERCE-001")
    assert "TBL-ORDERS" in downstream
    assert "EVID-COMMERCE-CHECKOUT" in downstream

    upstream = traceability_upstream(links, root_code="TBL-ORDERS")
    assert "REQ-VAV-COMMERCE-001" in upstream
    assert "EVID-COMMERCE-CHECKOUT" not in upstream


def test_downstream_respects_max_depth() -> None:
    links = _links()
    assert traceability_downstream(
        links, root_code="REQ-VAV-COMMERCE-001", max_depth=1
    ) == ("CAP-COMMERCE-CHECKOUT",)


def test_cycle_detection_finds_self_justifying_loop() -> None:
    links = _links() + [
        TraceLink(
            source="EVID-COMMERCE-CHECKOUT",
            target="REQ-VAV-COMMERCE-001",
            relationship="implements",
        )
    ]
    cycles = detect_trace_cycles(links)
    assert cycles
    assert any("REQ-VAV-COMMERCE-001" in cycle for cycle in cycles)


def test_acyclic_graph_has_no_cycles() -> None:
    assert detect_trace_cycles(_links()) == ()


def test_dangling_link_is_detected() -> None:
    links = _links() + [
        TraceLink(
            source="REQ-VAV-COMMERCE-001",
            target="TEST-DOES-NOT-EXIST",
            relationship="verified_by",
        )
    ]
    assert detect_dangling_links(_nodes(), links) == (
        ("REQ-VAV-COMMERCE-001", "TEST-DOES-NOT-EXIST", "verified_by"),
    )


def test_unreachable_nodes_are_orphan_candidates() -> None:
    nodes = _nodes() + [TraceNode(code="PAGE-ORPHAN", node_type=TraceNodeType.PAGE)]
    assert unreachable_nodes(nodes, _links(), root_codes=["REQ-VAV-COMMERCE-001"]) == (
        "PAGE-ORPHAN",
    )


def test_unknown_relationship_is_rejected() -> None:
    links = [
        TraceLink(
            source="REQ-VAV-COMMERCE-001",
            target="CAP-COMMERCE-CHECKOUT",
            relationship="magically_satisfies",
        )
    ]
    with pytest.raises(QualityPolicyError) as error:
        detect_trace_cycles(links)
    assert error.value.code == "QUALITY_TRACE_RELATIONSHIP_INVALID"


def test_self_link_is_rejected_by_analysis() -> None:
    links = [
        TraceLink(
            source="REQ-VAV-COMMERCE-001",
            target="REQ-VAV-COMMERCE-001",
            relationship="implements",
        )
    ]
    with pytest.raises(QualityPolicyError) as error:
        analyze_traceability(
            _nodes(),
            links,
            root_code="REQ-VAV-COMMERCE-001",
            required_types=frozenset(),
        )
    assert error.value.code == "QUALITY_TRACE_LINK_INVALID"
