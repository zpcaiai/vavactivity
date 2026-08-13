#!/usr/bin/env python3
"""Audit every role decision and bind permissions to executable API routes."""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
API_SOURCE = ROOT / "services" / "api" / "src"
ADMIN_WEB_SOURCE = ROOT.parent / "vavactivityWeb" / "apps" / "admin-web" / "src"
if str(API_SOURCE) not in sys.path:
    sys.path.insert(0, str(API_SOURCE))

os.environ.setdefault("APP_ENV", "test")

from fastapi.routing import APIRoute  # noqa: E402

from vav.common.exceptions import VavError  # noqa: E402
from vav.main import app  # noqa: E402
from vav.modules.identity.dependencies import AuthenticatedPrincipal  # noqa: E402
from vav.modules.identity.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS  # noqa: E402

PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
FRONTEND_PERMISSION_PATTERN = re.compile(
    r"""(?:permission\s*:\s*|hasPermission\(\s*|v-permission\s*=\s*)["']"""
    r"""([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)["']"""
)
PUBLIC_ADMIN_ROUTES = {
    ("POST", "/admin/auth/login"),
    ("POST", "/admin/auth/refresh"),
    ("POST", "/admin/admins/invitations/accept"),
}


def _effective_routes(routes: list[Any]) -> list[Any]:
    result: list[Any] = []
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            result.extend(_effective_routes(original_router.routes))
        else:
            result.append(route)
    return result


def _dependency_details(dependency: Any) -> tuple[set[str], set[str]]:
    permissions: set[str] = set()
    dependency_names: set[str] = set()
    for child in dependency.dependencies:
        call = child.call
        if call is not None:
            dependency_names.add(getattr(call, "__name__", call.__class__.__name__))
            code = getattr(call, "__code__", None)
            closure = getattr(call, "__closure__", None) or ()
            if code is not None:
                closed = dict(
                    zip(code.co_freevars, (cell.cell_contents for cell in closure))
                )
                permission = closed.get("permission")
                if isinstance(permission, str):
                    permissions.add(permission)
        child_permissions, child_names = _dependency_details(child)
        permissions.update(child_permissions)
        dependency_names.update(child_names)
    return permissions, dependency_names


def _strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if PERMISSION_PATTERN.fullmatch(value) else set()
    if isinstance(value, dict):
        result: set[str] = set()
        for item in value.values():
            result.update(_strings(item))
        return result
    if isinstance(value, (set, frozenset, list, tuple)):
        result = set()
        for item in value:
            result.update(_strings(item))
        return result
    return set()


def _literal_permissions(node: ast.AST) -> set[str]:
    return {
        value.value
        for value in ast.walk(node)
        if isinstance(value, ast.Constant)
        and isinstance(value.value, str)
        and PERMISSION_PATTERN.fullmatch(value.value)
    }


def _endpoint_permissions(endpoint: Any) -> set[str]:
    """Collect literal and module-mapping permissions used inside an endpoint."""

    result: set[str] = set()
    try:
        source = inspect.getsource(endpoint)
        tree = ast.parse(source)
    except (OSError, TypeError, IndentationError, SyntaxError):
        return result

    relevant_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.endswith("PERMISSIONS"):
            relevant_names.add(node.id)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is not None and any(
                isinstance(target, ast.Name) and "permission" in target.id.casefold()
                for target in targets
            ):
                # Endpoints often choose a permission from a local state/action
                # mapping before calling principal.require(variable).
                result.update(_literal_permissions(value))
        if not isinstance(node, ast.Call):
            continue
        function_name = ""
        if isinstance(node.func, ast.Name):
            function_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            function_name = node.func.attr
        if function_name not in {
            "require",
            "require_permission",
            "_require_permission",
        }:
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                if PERMISSION_PATTERN.fullmatch(argument.value):
                    result.add(argument.value)

    globals_ = getattr(endpoint, "__globals__", {})
    for name in relevant_names:
        result.update(_strings(globals_.get(name)))
    return result


def _source_permission_references() -> set[str]:
    result: set[str] = set()
    source_root = API_SOURCE / "vav"
    for path in source_root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = ""
            if isinstance(node.func, ast.Name):
                function_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                function_name = node.func.attr
            if function_name not in {
                "require",
                "require_permission",
                "_require_permission",
            }:
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    if PERMISSION_PATTERN.fullmatch(argument.value):
                        result.add(argument.value)
    return result


def _frontend_permission_references() -> set[str]:
    result: set[str] = set()
    if not ADMIN_WEB_SOURCE.is_dir():
        return result
    for path in ADMIN_WEB_SOURCE.rglob("*"):
        if path.suffix not in {".ts", ".vue"}:
            continue
        result.update(
            FRONTEND_PERMISSION_PATTERN.findall(path.read_text(encoding="utf-8"))
        )
    return result


def _exercise_role_decisions() -> tuple[int, int, list[str]]:
    allowed = 0
    denied = 0
    failures: list[str] = []
    for role, granted in ROLE_PERMISSIONS.items():
        principal = AuthenticatedPrincipal(
            user=cast(Any, object()),
            session=cast(Any, object()),
            audience="role-function-audit",
            permissions=frozenset(granted),
        )
        for permission in ALL_PERMISSIONS:
            if permission in granted:
                try:
                    principal.require(permission)
                    allowed += 1
                except VavError as exc:
                    failures.append(
                        f"{role}: expected allow for {permission}, got {exc.code}"
                    )
            else:
                try:
                    principal.require(permission)
                except VavError as exc:
                    denied += 1
                    if exc.code != "PERMISSION_DENIED" or exc.status_code != 403:
                        failures.append(
                            f"{role}: wrong denial for {permission}: {exc.code}/{exc.status_code}"
                        )
                else:
                    failures.append(f"{role}: expected denial for {permission}")
    return allowed, denied, failures


def build_report() -> dict[str, Any]:
    route_bindings: dict[str, list[dict[str, str]]] = defaultdict(list)
    route_rows: list[dict[str, Any]] = []
    unprotected_admin_routes: list[str] = []

    for route in _effective_routes(app.routes):
        if not isinstance(route, APIRoute):
            continue
        direct_permissions, dependency_names = _dependency_details(route.dependant)
        endpoint_permissions = _endpoint_permissions(route.endpoint)
        permissions = direct_permissions | endpoint_permissions
        methods = sorted(route.methods)
        mode = "permission"
        if not permissions:
            if "require_admin_principal" in dependency_names:
                mode = "admin_authenticated"
            elif "require_authenticated_user" in dependency_names:
                mode = "user_authenticated"
            elif all((method, route.path) in PUBLIC_ADMIN_ROUTES for method in methods):
                mode = "public_auth_flow"
            else:
                mode = "public"
        if route.path.startswith("/admin/") and mode == "public":
            unprotected_admin_routes.extend(
                f"{method} {route.path}" for method in methods
            )
        for permission in sorted(permissions):
            for method in methods:
                route_bindings[permission].append(
                    {"method": method, "path": route.path}
                )
        route_rows.append(
            {
                "methods": methods,
                "path": route.path,
                "permission_mode": mode,
                "permissions": sorted(permissions),
            }
        )

    source_references = _source_permission_references()
    frontend_references = _frontend_permission_references()
    referenced_permissions = (
        set(route_bindings) | source_references | frontend_references
    )
    assigned_permissions = set().union(*ROLE_PERMISSIONS.values())
    route_bound_permissions = set(route_bindings)
    policy_only_permissions = ALL_PERMISSIONS - route_bound_permissions
    unknown_references = sorted(referenced_permissions - ALL_PERMISSIONS)
    unknown_assignments = sorted(assigned_permissions - ALL_PERMISSIONS)
    allowed, denied, decision_failures = _exercise_role_decisions()

    roles: list[dict[str, Any]] = []
    for role, granted in ROLE_PERMISSIONS.items():
        policy_only_grants = granted & policy_only_permissions
        routes = {
            f"{binding['method']} {binding['path']}"
            for permission in granted
            for binding in route_bindings.get(permission, [])
        }
        roles.append(
            {
                "role": role,
                "permission_count": len(granted),
                "denied_permission_count": len(ALL_PERMISSIONS - granted),
                "policy_only_permission_count": len(policy_only_grants),
                "bound_route_operation_count": len(routes),
                "permissions": sorted(granted),
                "policy_only_permissions": sorted(policy_only_grants),
            }
        )

    findings = {
        "unknown_permission_references": unknown_references,
        "unknown_role_assignments": unknown_assignments,
        "unprotected_admin_routes": sorted(unprotected_admin_routes),
        "decision_failures": decision_failures,
    }
    status = "PASS" if not any(findings.values()) else "FAIL"
    return {
        "status": status,
        "scope": "local_role_function_contract",
        "production_certification": False,
        "functional_coverage_complete": not policy_only_permissions,
        "summary": {
            "role_count": len(ROLE_PERMISSIONS),
            "permission_count": len(ALL_PERMISSIONS),
            "admin_web_permission_reference_count": len(frontend_references),
            "route_bound_permission_count": len(route_bound_permissions),
            "policy_only_permission_count": len(policy_only_permissions),
            "route_operation_count": sum(len(row["methods"]) for row in route_rows),
            "permission_bound_route_operation_count": sum(
                len(v) for v in route_bindings.values()
            ),
            "allow_decisions_executed": allowed,
            "deny_decisions_executed": denied,
            "total_decisions_executed": allowed + denied,
        },
        "findings": findings,
        "permission_coverage": {
            "route_bound": sorted(route_bound_permissions),
            "policy_only": sorted(policy_only_permissions),
        },
        "roles": roles,
        "routes": route_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "testing" / "role-function-matrix.json",
    )
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], **report["summary"]}, indent=2))
    print(args.output)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
