"""Pure experience policies shared by runtime services and offline gates."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from vav.common.exceptions import VavError

SENSITIVE_CONTEXT_MARKERS = {
    "phone",
    "email",
    "address",
    "evidence",
    "message",
    "reflection",
    "contact",
    "payment",
    "price",
    "secret",
    "token",
    "password",
}

TERMINAL_ROUTE_TYPES = {"status"}


def validate_identifier_context(context: dict[str, Any], allowed_keys: set[str]) -> None:
    unknown = set(context) - allowed_keys
    if unknown:
        raise VavError(
            "HANDOFF_CONTEXT_SCHEMA_INVALID",
            "Handoff context contains fields outside the declared identifier schema.",
            status_code=422,
            details=[{"unknown_fields": sorted(unknown)}],
        )
    for key, value in context.items():
        normalized = key.casefold().replace("-", "_")
        if any(marker in normalized for marker in SENSITIVE_CONTEXT_MARKERS):
            raise VavError(
                "HANDOFF_SENSITIVE_CONTEXT_FORBIDDEN",
                "Sensitive raw values are forbidden in handoff context.",
                status_code=422,
            )
        if isinstance(value, dict | list) or not isinstance(value, str) or len(value) > 128:
            raise VavError(
                "HANDOFF_IDENTIFIER_CONTEXT_REQUIRED",
                "Handoff context accepts bounded identifiers only.",
                status_code=422,
            )


def minimize_feedback_context(context: dict[str, Any]) -> dict[str, str | int | bool]:
    minimized: dict[str, str | int | bool] = {}
    for key, value in context.items():
        normalized = key.casefold().replace("-", "_")
        if any(marker in normalized for marker in SENSITIVE_CONTEXT_MARKERS):
            continue
        if isinstance(value, bool | int):
            minimized[key[:64]] = value
        elif isinstance(value, str):
            minimized[key[:64]] = value[:128]
    return minimized


def support_queue(category: str) -> str:
    return {
        "safety": "trust-safety",
        "privacy": "privacy-rights",
        "payment_dispute": "finance-disputes",
    }.get(category, "member-support")


@dataclass(frozen=True)
class RouteEligibility:
    eligible: bool
    reason_code: str | None
    fallback_route_code: str | None


def evaluate_route(
    route: dict[str, Any],
    *,
    authenticated: bool,
    permissions: set[str],
    capabilities: set[str],
    enabled_features: set[str],
    restriction_codes: set[str],
) -> RouteEligibility:
    fallback = route.get("fallback_route_code")
    if route.get("authentication_required") and not authenticated:
        return RouteEligibility(False, "authentication_required", fallback or "user.login")
    missing_permissions = set(route.get("permission_codes") or []) - permissions
    if missing_permissions:
        return RouteEligibility(False, "permission_required", fallback)
    missing_capabilities = set(route.get("capability_codes") or []) - capabilities
    if missing_capabilities:
        return RouteEligibility(False, "capability_required", fallback)
    feature = route.get("feature_flag")
    if feature and feature not in enabled_features:
        return RouteEligibility(False, "feature_disabled", fallback)
    policy = route.get("prerequisite_policy") or {}
    if set(policy.get("denied_restrictions", [])) & restriction_codes:
        if route.get("route_code") in {"user.safety", "user.privacy", "user.account"}:
            return RouteEligibility(True, None, fallback)
        return RouteEligibility(False, "safety_restriction", fallback or "user.safety")
    return RouteEligibility(True, None, fallback)


def scan_route_graph(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code = {str(route["route_code"]): route for route in routes}
    edges: dict[str, set[str]] = defaultdict(set)
    findings: list[dict[str, Any]] = []
    for code, route in by_code.items():
        for field in ("fallback_route_code",):
            target = route.get(field)
            if target:
                if target not in by_code:
                    findings.append(
                        {
                            "type": "broken_link",
                            "route_code": code,
                            "target": target,
                            "severity": "critical" if route.get("critical") else "high",
                        }
                    )
                else:
                    edges[code].add(str(target))
        help_code = route.get("help_context_code")
        if route.get("critical") and not help_code:
            findings.append({"type": "missing_help", "route_code": code, "severity": "critical"})

    roots = {code for code in by_code if code in {"user.home", "admin.dashboard"}}
    roots.update(
        code for code, route in by_code.items() if not route.get("authentication_required")
    )
    for code, route in by_code.items():
        if route.get("fallback_route_code"):
            edges[str(route["fallback_route_code"])].add(code)
    reached: set[str] = set()
    queue: deque[str] = deque(roots)
    while queue:
        current = queue.popleft()
        if current in reached:
            continue
        reached.add(current)
        queue.extend(edges[current] - reached)
    for code, route in by_code.items():
        if route.get("critical") and code not in reached:
            findings.append(
                {"type": "unreachable_route", "route_code": code, "severity": "critical"}
            )
        if (
            route.get("critical")
            and code not in roots
            and not edges.get(code)
            and route.get("route_type") not in TERMINAL_ROUTE_TYPES
        ):
            findings.append(
                {"type": "no_recovery_path", "route_code": code, "severity": "critical"}
            )

    for start in by_code:
        seen: set[str] = set()
        redirect_target: str | None = start
        while redirect_target and redirect_target in by_code:
            if redirect_target in seen:
                findings.append(
                    {"type": "redirect_loop", "route_code": start, "severity": "critical"}
                )
                break
            seen.add(redirect_target)
            route = by_code[redirect_target]
            if route.get("route_type") != "redirect":
                break
            target_value = route.get("fallback_route_code")
            redirect_target = str(target_value) if target_value else None
    unique = {(item["type"], item["route_code"]): item for item in findings}
    return sorted(
        unique.values(), key=lambda item: (item["severity"], item["type"], item["route_code"])
    )


def closure_checks(route: dict[str, Any]) -> dict[str, bool]:
    return {
        "discoverable_entry": bool(route.get("ia_node_code")),
        "real_action": route.get("route_type", "page") in {"page", "action", "status"},
        "visible_status": bool(route.get("page_code")),
        "next_step": bool(route.get("fallback_route_code"))
        or route.get("route_code") in {"user.home", "admin.dashboard"},
        "return_path": bool(route.get("fallback_route_code"))
        or route.get("route_code") in {"user.home", "admin.dashboard"},
        "recovery": bool(route.get("fallback_route_code"))
        or route.get("route_code") in {"user.home", "admin.dashboard"},
        "help": bool(route.get("help_context_code")),
        "authorization_declared": isinstance(route.get("permission_codes"), list),
    }
