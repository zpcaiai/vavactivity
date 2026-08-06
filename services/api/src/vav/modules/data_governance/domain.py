"""Pure data-integrity policies."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

IDENTITY_FORBIDDEN = {"email", "phone", "display_name", "provider_id", "order_number"}
RULE_OPERATORS = {
    "not_null",
    "reference_exists",
    "greater_or_equal",
    "unique",
    "max_lag_seconds",
    "matches_pattern",
    "in_set",
}
CLASSIFICATION = {"public": 0, "internal": 1, "restricted": 2, "highly_restricted": 3}


def validate_asset(asset: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if bool(asset.get("truth")) == bool(asset.get("projection")):
        findings.append("source_projection_ownership_ambiguous")
    if asset.get("projection") and not asset.get("rebuildable"):
        findings.append("projection_not_rebuildable")
    if str(asset.get("identifier", "")).casefold() in IDENTITY_FORBIDDEN:
        findings.append("noncanonical_identifier")
    for required in ("module", "classification", "retention", "erasure", "identifier"):
        if not asset.get(required):
            findings.append(f"missing_{required}")
    return findings


def contract_diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_required = set(old.get("required") or [])
    new_required = set(new.get("required") or [])
    removed = sorted(old_required - new_required)
    newly_required = sorted(new_required - old_required)
    old_sensitive = set(old.get("sensitive") or [])
    new_sensitive = set(new.get("sensitive") or [])
    declassified = sorted(old_sensitive - new_sensitive)
    reasons = []
    if removed:
        reasons.append("required_fields_removed")
    if newly_required:
        reasons.append("new_required_fields")
    if declassified:
        reasons.append("sensitive_fields_declassified")
    return {
        "changes": {
            "removed": removed,
            "newly_required": newly_required,
            "declassified": declassified,
        },
        "compatibility_status": "breaking" if reasons else "compatible",
        "breaking_reasons": reasons,
    }


def validate_lineage(
    assets: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[dict[str, str]]:
    by_code = {item["code"]: item for item in assets}
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    findings: list[dict[str, str]] = []
    for edge in edges:
        source, target = edge["source"], edge["target"]
        if source not in by_code or target not in by_code:
            findings.append({"code": "unknown_asset", "asset": f"{source}->{target}"})
            continue
        incoming[target].append(edge)
        outgoing[source].append(edge)
        if CLASSIFICATION[by_code[source]["classification"]] > CLASSIFICATION[
            by_code[target]["classification"]
        ] and edge["transform"] not in {"mask", "anonymize", "filter"}:
            findings.append({"code": "undeclared_sensitive_flow", "asset": target})
        if (
            by_code[target]["projection"]
            and not edge.get("erasure")
            and edge["transform"] != "anonymize"
            and by_code[source]["classification"] in {"restricted", "highly_restricted"}
        ):
            findings.append({"code": "missing_erasure_propagation", "asset": target})
    for asset in assets:
        if asset["projection"] and not incoming[asset["code"]]:
            findings.append({"code": "projection_missing_upstream", "asset": asset["code"]})
    for root in (asset["code"] for asset in assets if asset["truth"]):
        seen: set[str] = set()
        queue: deque[str] = deque([root])
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(edge["target"] for edge in outgoing[current])
        if by_code[root]["classification"] in {"restricted", "highly_restricted"} and not any(
            by_code[node]["projection"] for node in seen - {root}
        ):
            findings.append({"code": "critical_asset_missing_downstream", "asset": root})
    return sorted(findings, key=lambda item: (item["code"], item["asset"]))


def validate_rule(rule: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if rule.get("operator") not in RULE_OPERATORS:
        findings.append("unsupported_operator")
    serialized = str(rule).casefold()
    if any(marker in serialized for marker in ("select ", "update ", "delete ", ";", "--")):
        findings.append("imperative_sql_forbidden")
    if rule.get("threshold", 0) < 0:
        findings.append("negative_threshold")
    return findings


def event_disposition(current_version: int, received_version: int) -> str:
    if received_version <= current_version:
        return "rejected_old"
    if received_version == current_version + 1:
        return "accepted"
    return "buffered_future"


def erasure_action(asset: dict[str, Any]) -> str:
    if asset["type"] == "cache":
        return "invalidate_cache"
    if asset["type"] == "search_index":
        return "remove_search"
    if asset["type"] == "vector_index":
        return "remove_vector"
    if asset["type"] == "object_collection":
        return "remove_object"
    if asset["type"] == "file_export":
        return "remove_export"
    if asset["projection"]:
        return "remove_projection"
    if "anonymize" in asset["erasure"] or "minimize" in asset["erasure"]:
        return "anonymize"
    return "delete"


def minimize_evidence(value: dict[str, Any]) -> dict[str, str | int | bool]:
    safe: dict[str, str | int | bool] = {}
    for key, item in value.items():
        if any(
            marker in key.casefold()
            for marker in ("email", "phone", "name", "payload", "content", "token", "secret")
        ):
            continue
        if isinstance(item, bool | int):
            safe[key[:64]] = item
        elif isinstance(item, str):
            safe[key[:64]] = item[:128]
    return safe
