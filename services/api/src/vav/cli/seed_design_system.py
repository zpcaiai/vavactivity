# ruff: noqa: E501

"""Seed Batch 22 design assets as drafts without manufacturing approvals."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.database import session_factory

ROOT = Path(__file__).resolve().parents[5]
PAGE_CATALOG = ROOT / "config/ui/page-catalog.yaml"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


COMPONENTS = [
    (
        "VButton",
        "@vav/ui-core",
        "packages/ui-core/src/components/VButton.vue",
        ["default", "loading", "disabled"],
    ),
    (
        "VStatusBadge",
        "@vav/ui-core",
        "packages/ui-core/src/components/VStatusBadge.vue",
        ["success", "warning", "danger", "info"],
    ),
    (
        "VAlert",
        "@vav/ui-core",
        "packages/ui-core/src/components/VAlert.vue",
        ["info", "success", "warning", "danger"],
    ),
    (
        "VFormField",
        "@vav/ui-core",
        "packages/ui-core/src/components/VFormField.vue",
        ["hint", "invalid", "required"],
    ),
    ("VModal", "@vav/ui-core", "packages/ui-core/src/components/VModal.vue", ["open", "dangerous"]),
    (
        "VPageState",
        "@vav/ui-core",
        "packages/ui-core/src/components/VPageState.vue",
        ["loading", "empty", "partial", "error", "offline", "forbidden"],
    ),
    (
        "AdminDataTable",
        "@vav/ui-admin",
        "packages/ui-admin/src/tables/AdminDataTable.vue",
        ["loading", "empty", "selected", "responsive"],
    ),
    (
        "ReviewWorkbench",
        "@vav/ui-admin",
        "packages/ui-admin/src/workbenches/ReviewWorkbench.vue",
        ["default", "restricted", "busy"],
    ),
    (
        "UserPageLayout",
        "@vav/ui-user",
        "packages/ui-user/src/layouts/UserPageLayout.vue",
        ["reading", "standard", "wide"],
    ),
]

PATTERNS = [
    (
        "user-page-layout",
        "User page layout",
        "user",
        "packages/ui-user/src/layouts/UserPageLayout.vue",
        ["UserPageLayout", "VPageState"],
    ),
    (
        "user-form-workflow",
        "User form workflow",
        "user",
        "packages/ui-user/src/layouts/UserFormLayout.vue",
        ["UserFormLayout", "VFormField", "VErrorSummary"],
    ),
    (
        "admin-data-table",
        "Administrator data table",
        "admin",
        "packages/ui-admin/src/tables/AdminDataTable.vue",
        ["AdminDataTable", "AdminFilterPanel"],
    ),
    (
        "admin-review-workbench",
        "Independent review workbench",
        "admin",
        "packages/ui-admin/src/workbenches/ReviewWorkbench.vue",
        ["ReviewWorkbench", "VStatusBadge"],
    ),
    (
        "page-state-recovery",
        "Page state and recovery",
        "shared",
        "packages/ui-core/src/components/VPageState.vue",
        ["VPageState", "VAlert", "VButton"],
    ),
]


def _pages(catalog_path: Path = PAGE_CATALOG) -> list[dict[str, Any]]:
    """Load the immutable page inventory shipped with the backend image.

    The API production image intentionally excludes frontend source.  The catalog is
    generated from the routers and checked for drift by ``scripts/ui/control.py`` so
    database seeding remains deterministic in development and production.
    """

    raw_catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(raw_catalog, dict) or raw_catalog.get("schema_version") != "1.0.0":
        raise ValueError("UI page catalog must use schema_version 1.0.0")
    raw_routes = raw_catalog.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError("UI page catalog must contain at least one route")

    pages: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, raw_route in enumerate(raw_routes):
        if not isinstance(raw_route, dict):
            raise ValueError(f"UI page catalog route {index} must be an object")
        application = raw_route.get("application")
        route_path = raw_route.get("route_path")
        component = raw_route.get("component")
        source = raw_route.get("source")
        if application not in {"user-web", "admin-web"}:
            raise ValueError(f"UI page catalog route {index} has invalid application")
        if (
            not isinstance(route_path, str)
            or not route_path
            or not isinstance(component, str)
            or not component
            or not isinstance(source, str)
            or not source
        ):
            raise ValueError(f"UI page catalog route {index} has incomplete fields")

        source_path = PurePosixPath(source)
        if (
            source_path.is_absolute()
            or ".." in source_path.parts
            or source_path.parts[:3] != ("apps", application, "src")
            or source_path.suffix != ".vue"
        ):
            raise ValueError(f"UI page catalog route {index} has unsafe source path")
        identity = (application, route_path, component)
        if identity in seen:
            raise ValueError(f"UI page catalog contains duplicate route {identity!r}")
        seen.add(identity)

        fingerprint_source = f"{application}:{route_path}:{source}"
        pages.append(
            {
                "application": application,
                "route_name": f"{component}:{hashlib.sha1(route_path.encode(), usedforsecurity=False).hexdigest()[:10]}",
                "route_path": route_path,
                "page_type": "administrator" if application == "admin-web" else "user",
                "actors": _json(
                    ["administrator"] if application == "admin-web" else ["anonymous", "member"]
                ),
                "source": source,
                "fingerprint": hashlib.sha256(fingerprint_source.encode()).hexdigest(),
            }
        )
    return pages


async def seed_design_system() -> None:
    await ensure_system_user()
    manifest = ROOT / "packages/design-tokens/design-token-manifest.yaml"
    generated = ROOT / "packages/design-tokens/generated/tokens.json"
    pages = _pages()
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO ui_token_releases (token_version,manifest_checksum_sha256,generated_checksum_sha256,change_summary,breaking_changes,status,created_by) "
                "VALUES ('1.0.0',:manifest,:generated,'Initial governed Batch 22 design token release.','[]'::jsonb,'draft',:actor) "
                "ON CONFLICT (token_version) DO UPDATE SET manifest_checksum_sha256=EXCLUDED.manifest_checksum_sha256,generated_checksum_sha256=EXCLUDED.generated_checksum_sha256,change_summary=EXCLUDED.change_summary"
            ),
            {"manifest": _sha(manifest), "generated": _sha(generated), "actor": SYSTEM_USER_ID},
        )
        for code, package, location, states in COMPONENTS:
            await session.execute(
                text(
                    "INSERT INTO ui_components (component_code,package_name,source_location,owner_team,accessibility_contract,supported_states,status,created_by,updated_by) "
                    "VALUES (:code,:package,:location,'design_system',CAST(:accessibility AS jsonb),CAST(:states AS jsonb),'active',:actor,:actor) "
                    "ON CONFLICT (component_code) DO UPDATE SET package_name=EXCLUDED.package_name,source_location=EXCLUDED.source_location,accessibility_contract=EXCLUDED.accessibility_contract,supported_states=EXCLUDED.supported_states,updated_at=now(),updated_by=EXCLUDED.updated_by"
                ),
                {
                    "code": code,
                    "package": package,
                    "location": location,
                    "accessibility": _json(
                        {"keyboard": True, "focus_visible": True, "color_alone": False}
                    ),
                    "states": _json(states),
                    "actor": SYSTEM_USER_ID,
                },
            )
        for code, name, audience, location, components in PATTERNS:
            await session.execute(
                text(
                    "INSERT INTO ui_patterns (pattern_code,name,audience,source_location,required_components,required_states,accessibility_notes,status,created_by,updated_by) "
                    "VALUES (:code,:name,:audience,:location,CAST(:components AS jsonb),CAST(:states AS jsonb),'Keyboard order, visible focus, named landmarks and text-equivalent states are required.','active',:actor,:actor) "
                    "ON CONFLICT (pattern_code) DO UPDATE SET name=EXCLUDED.name,source_location=EXCLUDED.source_location,required_components=EXCLUDED.required_components,required_states=EXCLUDED.required_states,accessibility_notes=EXCLUDED.accessibility_notes,updated_at=now(),updated_by=EXCLUDED.updated_by"
                ),
                {
                    "code": code,
                    "name": name,
                    "audience": audience,
                    "location": location,
                    "components": _json(components),
                    "states": _json(["loading", "empty", "partial", "error", "success"]),
                    "actor": SYSTEM_USER_ID,
                },
            )
        for page in pages:
            await session.execute(
                text(
                    "INSERT INTO quality_pages (application_code,route_name,route_path,page_type,actor_types,required_permissions,source_location,status,scan_fingerprint) "
                    "VALUES (:application,:route_name,:route_path,:page_type,CAST(:actors AS jsonb),'[]'::jsonb,:source,'active',:fingerprint) "
                    "ON CONFLICT (application_code,route_name) DO UPDATE SET route_path=EXCLUDED.route_path,page_type=EXCLUDED.page_type,actor_types=EXCLUDED.actor_types,source_location=EXCLUDED.source_location,status='active',scan_fingerprint=EXCLUDED.scan_fingerprint,updated_at=now()"
                ),
                page,
            )
        await session.commit()
    print(
        f"Design system seed complete: {len(COMPONENTS)} components, {len(PATTERNS)} patterns, {len(pages)} pages, 1 draft token release; human approvals still required"
    )


if __name__ == "__main__":
    asyncio.run(seed_design_system())
