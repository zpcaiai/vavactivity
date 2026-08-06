# ruff: noqa: E501

"""Seed Batch 22 design assets as drafts without manufacturing approvals."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.database import session_factory

ROOT = Path(__file__).resolve().parents[5]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


COMPONENTS = [
    ("VButton", "@vav/ui-core", "packages/ui-core/src/components/VButton.vue", ["default", "loading", "disabled"]),
    ("VStatusBadge", "@vav/ui-core", "packages/ui-core/src/components/VStatusBadge.vue", ["success", "warning", "danger", "info"]),
    ("VAlert", "@vav/ui-core", "packages/ui-core/src/components/VAlert.vue", ["info", "success", "warning", "danger"]),
    ("VFormField", "@vav/ui-core", "packages/ui-core/src/components/VFormField.vue", ["hint", "invalid", "required"]),
    ("VModal", "@vav/ui-core", "packages/ui-core/src/components/VModal.vue", ["open", "dangerous"]),
    ("VPageState", "@vav/ui-core", "packages/ui-core/src/components/VPageState.vue", ["loading", "empty", "partial", "error", "offline", "forbidden"]),
    ("AdminDataTable", "@vav/ui-admin", "packages/ui-admin/src/tables/AdminDataTable.vue", ["loading", "empty", "selected", "responsive"]),
    ("ReviewWorkbench", "@vav/ui-admin", "packages/ui-admin/src/workbenches/ReviewWorkbench.vue", ["default", "restricted", "busy"]),
    ("UserPageLayout", "@vav/ui-user", "packages/ui-user/src/layouts/UserPageLayout.vue", ["reading", "standard", "wide"]),
]

PATTERNS = [
    ("user-page-layout", "User page layout", "user", "packages/ui-user/src/layouts/UserPageLayout.vue", ["UserPageLayout", "VPageState"]),
    ("user-form-workflow", "User form workflow", "user", "packages/ui-user/src/layouts/UserFormLayout.vue", ["UserFormLayout", "VFormField", "VErrorSummary"]),
    ("admin-data-table", "Administrator data table", "admin", "packages/ui-admin/src/tables/AdminDataTable.vue", ["AdminDataTable", "AdminFilterPanel"]),
    ("admin-review-workbench", "Independent review workbench", "admin", "packages/ui-admin/src/workbenches/ReviewWorkbench.vue", ["ReviewWorkbench", "VStatusBadge"]),
    ("page-state-recovery", "Page state and recovery", "shared", "packages/ui-core/src/components/VPageState.vue", ["VPageState", "VAlert", "VButton"]),
]


def _pages() -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for application in ("user-web", "admin-web"):
        router = ROOT / "apps" / application / "src/router/index.ts"
        source = router.read_text(encoding="utf-8")
        imports = dict(
            re.findall(r'import\s+(\w+)\s+from\s+"@/([^\"]+\.vue)"', source)
        )
        for match in re.finditer(
            r"\{\s*path:\s*[`\"]([^`\"]+)[`\"][^{}]*?component:\s*(\w+)",
            source,
            re.DOTALL,
        ):
            route_path, component = match.groups()
            location = imports.get(component)
            if not location:
                continue
            fingerprint_source = f"{application}:{route_path}:{location}"
            pages.append(
                {
                    "application": application,
                    "route_name": f"{component}:{hashlib.sha1(route_path.encode(), usedforsecurity=False).hexdigest()[:10]}",
                    "route_path": route_path,
                    "page_type": "administrator" if application == "admin-web" else "user",
                    "actors": _json(["administrator"] if application == "admin-web" else ["anonymous", "member"]),
                    "source": f"apps/{application}/src/{location}",
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
                {"code": code, "package": package, "location": location, "accessibility": _json({"keyboard": True, "focus_visible": True, "color_alone": False}), "states": _json(states), "actor": SYSTEM_USER_ID},
            )
        for code, name, audience, location, components in PATTERNS:
            await session.execute(
                text(
                    "INSERT INTO ui_patterns (pattern_code,name,audience,source_location,required_components,required_states,accessibility_notes,status,created_by,updated_by) "
                    "VALUES (:code,:name,:audience,:location,CAST(:components AS jsonb),CAST(:states AS jsonb),'Keyboard order, visible focus, named landmarks and text-equivalent states are required.','active',:actor,:actor) "
                    "ON CONFLICT (pattern_code) DO UPDATE SET name=EXCLUDED.name,source_location=EXCLUDED.source_location,required_components=EXCLUDED.required_components,required_states=EXCLUDED.required_states,accessibility_notes=EXCLUDED.accessibility_notes,updated_at=now(),updated_by=EXCLUDED.updated_by"
                ),
                {"code": code, "name": name, "audience": audience, "location": location, "components": _json(components), "states": _json(["loading", "empty", "partial", "error", "success"]), "actor": SYSTEM_USER_ID},
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
    print(f"Design system seed complete: {len(COMPONENTS)} components, {len(PATTERNS)} patterns, {len(pages)} pages, 1 draft token release; human approvals still required")


if __name__ == "__main__":
    asyncio.run(seed_design_system())
