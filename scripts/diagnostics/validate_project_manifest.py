#!/usr/bin/env python3
"""Validate the complete Batch 19 project assembly without mutating services."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
API_SOURCE = ROOT / "services" / "api" / "src"
MODULE_ROOT = API_SOURCE / "vav" / "modules"
MIGRATION_ROOT = ROOT / "services" / "api" / "migrations" / "versions"
FRONTEND_PERMISSION_CONTRACT = (
    ROOT / "config" / "frontend" / "admin-route-permissions.json"
)
sys.path.insert(0, str(API_SOURCE))

from vav.core.deployment_config import load_deployment_configuration  # noqa: E402
from vav.modules.identity.permissions import ALL_PERMISSIONS  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"project manifest validation failed: {message}")


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path.relative_to(ROOT)} must contain an object")
    return value


def migration_inventory() -> tuple[dict[str, str | None], dict[int, str]]:
    graph: dict[str, str | None] = {}
    numeric: dict[int, str] = {}
    for path in sorted(MIGRATION_ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        revision_match = re.search(r'^revision[^=]*=\s*"([^"]+)"', source, re.MULTILINE)
        down_match = re.search(
            r'^down_revision[^=]*=\s*(?:"([^"]+)"|None)', source, re.MULTILINE
        )
        require(revision_match is not None, f"{path.name} has no revision metadata")
        require(down_match is not None, f"{path.name} has no down_revision metadata")
        revision = revision_match.group(1)
        number = int(revision.rsplit("_", 1)[-1])
        require(revision not in graph, f"duplicate migration revision {revision}")
        require(number not in numeric, f"duplicate migration number {number}")
        graph[revision] = down_match.group(1)
        numeric[number] = revision
    children = Counter(parent for parent in graph.values() if parent is not None)
    heads = set(graph) - set(children)
    require(len(heads) == 1, f"expected one migration head, found {sorted(heads)}")
    require(
        sorted(numeric) == list(range(1, max(numeric) + 1)),
        "migration numbers must be contiguous",
    )
    for revision, parent in graph.items():
        require(
            parent is None or parent in graph,
            f"{revision} references missing parent {parent}",
        )
    return graph, numeric


def module_inventory(numeric_migrations: dict[int, str]) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    assigned: dict[int, str] = {}
    module_dirs = sorted(
        path
        for path in MODULE_ROOT.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )
    for directory in module_dirs:
        path = directory / "module.yaml"
        require(path.exists(), f"module {directory.name} is missing module.yaml")
        manifest = load_yaml(path)
        module = manifest.get("module", {})
        code = module.get("code")
        require(code == directory.name, f"{directory.name} manifest code mismatch")
        require(
            module.get("owner") and module.get("version"),
            f"{code} owner/version missing",
        )
        manifests[code] = manifest
        for number in manifest.get("database", {}).get("revisions", []):
            require(
                number in numeric_migrations,
                f"{code} references migration {number} which does not exist",
            )
            require(
                number not in assigned,
                f"migration {number} belongs to multiple modules",
            )
            assigned[number] = code
    require(
        set(assigned) == set(numeric_migrations),
        "every migration must belong to exactly one module",
    )
    for code, manifest in manifests.items():
        for dependency in manifest.get("dependencies", {}).get("required", []):
            require(
                dependency in manifests,
                f"{code} references unknown dependency {dependency}",
            )
            require(dependency != code, f"{code} cannot depend on itself")
    return manifests


def validate_events(manifests: dict[str, dict[str, Any]]) -> int:
    registry = load_yaml(ROOT / "config/events/manifest.yaml").get("events", {})
    used: set[str] = set()
    for code, manifest in manifests.items():
        events = manifest.get("events", {})
        for event in events.get("publishes", []) + events.get("consumes", []):
            require(event in registry, f"{code} references unregistered event {event}")
            used.add(event)
        for event in events.get("publishes", []):
            require(
                registry[event].get("owner") == code, f"{event} owner must be {code}"
            )
    require(
        used == set(registry),
        "event registry contains unused or unreferenced definitions",
    )
    return len(registry)


def validate_permissions(manifests: dict[str, dict[str, Any]]) -> int:
    prefixes = [
        prefix
        for manifest in manifests.values()
        for prefix in manifest.get("permissions", {}).get("prefixes", [])
    ]
    uncovered = sorted(
        permission
        for permission in ALL_PERMISSIONS
        if not any(permission.startswith(prefix) for prefix in prefixes)
    )
    require(not uncovered, f"permissions are missing module ownership: {uncovered[:5]}")
    frontend_contract = json.loads(
        FRONTEND_PERMISSION_CONTRACT.read_text(encoding="utf-8")
    )
    require(
        frontend_contract.get("schema_version") == "1.0.0",
        "frontend permission contract version missing",
    )
    source = frontend_contract.get("source", {})
    require(
        source.get("repository") and source.get("path"),
        "frontend permission source identity is incomplete",
    )
    declared = frontend_contract.get("permissions")
    require(
        isinstance(declared, list) and bool(declared),
        "frontend route permissions must be a non-empty list",
    )
    require(
        declared == sorted(set(declared)),
        "frontend route permissions must be sorted and unique",
    )
    route_permissions = set(declared)
    unknown = sorted(route_permissions - ALL_PERMISSIONS)
    require(not unknown, f"admin routes reference unknown permissions: {unknown[:5]}")
    return len(ALL_PERMISSIONS)


def validate_assembly(
    assembly: dict[str, Any], manifests: dict[str, dict[str, Any]]
) -> None:
    declared_modules = assembly.get("modules")
    require(
        isinstance(declared_modules, list) and bool(declared_modules),
        "production module inventory is missing",
    )
    require(
        declared_modules == sorted(set(declared_modules)),
        "production module inventory must be sorted and unique",
    )
    require(
        set(declared_modules) == set(manifests),
        "production module inventory does not match module manifests",
    )
    applications = assembly.get("applications", {})
    require(set(applications) == {"user-web", "admin-web"}, "web applications missing")
    for name, application in applications.items():
        require(
            application.get("repository") == "zpcaiai/vavactivityWeb",
            f"{name} must reference the split frontend repository",
        )
        require(
            application.get("checkout_env") == "VAV_WEB_ROOT",
            f"{name} must declare the split checkout environment",
        )
        require(application.get("path"), f"{name} path missing")


def validate_environment_files() -> int:
    names = [
        "development.yaml",
        "test.yaml",
        "ci.yaml",
        "staging.yaml",
        "production.template.yaml",
        "dr.yaml",
    ]
    environments = {
        load_deployment_configuration(ROOT / "config/env" / name).environment
        for name in names
    }
    require(
        environments == {"development", "test", "ci", "staging", "production", "dr"},
        "environment matrix is incomplete",
    )
    return len(environments)


def validate_openapi() -> tuple[int, int]:
    contract = json.loads(
        (ROOT / "packages/contracts/openapi.json").read_text(encoding="utf-8")
    )
    paths = contract.get("paths", {})
    operation_ids = [
        operation.get("operationId")
        for methods in paths.values()
        for method, operation in methods.items()
        if method.lower()
        in {"get", "post", "put", "patch", "delete", "options", "head"}
    ]
    require(
        None not in operation_ids, "every OpenAPI operation requires an operationId"
    )
    require(
        len(operation_ids) == len(set(operation_ids)),
        "OpenAPI operationIds must be unique",
    )
    return len(paths), len(operation_ids)


def validate_seeds() -> int:
    manifest = load_yaml(ROOT / "config/seeds/manifest.yaml")
    require(
        manifest.get("production_allowed_groups") == ["system", "reference"],
        "production demo/test seeds must remain disabled",
    )
    seeds = [seed for group in manifest.get("groups", {}).values() for seed in group]
    for seed in seeds:
        module_name = seed.rsplit(".", 1)[-1]
        require(
            (API_SOURCE / "vav/cli" / f"{module_name}.py").exists(),
            f"seed does not exist: {seed}",
        )
    require(len(seeds) == len(set(seeds)), "seed entries must be unique")
    return len(seeds)


def main() -> None:
    project = load_yaml(ROOT / "project-manifest.yaml")
    assembly = project.get("production_assembly", {})
    require(
        assembly.get("architecture_version") == "1.0.0",
        "production assembly version missing",
    )
    graph, numeric = migration_inventory()
    manifests = module_inventory(numeric)
    validate_assembly(assembly, manifests)
    migration_heads = set(graph) - {
        parent for parent in graph.values() if parent is not None
    }
    require(
        assembly.get("migration_head") in migration_heads,
        "declared migration head is not the current migration head",
    )
    event_count = validate_events(manifests)
    permission_count = validate_permissions(manifests)
    environment_count = validate_environment_files()
    path_count, operation_count = validate_openapi()
    seed_count = validate_seeds()
    print(
        "project manifest valid: "
        f"{len(manifests)} modules, {len(graph)} migrations, {event_count} events, "
        f"{permission_count} permissions, {environment_count} environments, "
        f"{path_count} OpenAPI paths/{operation_count} operations, {seed_count} seeds"
    )


if __name__ == "__main__":
    main()
