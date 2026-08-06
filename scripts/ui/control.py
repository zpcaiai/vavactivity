#!/usr/bin/env python3
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "ui"


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def write(name: str, value: dict[str, Any]) -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    path = BUILD / name
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def token_check() -> dict[str, Any]:
    config = load_yaml(ROOT / "config/ui/style-exceptions.yaml")
    manifest = load_yaml(ROOT / "packages/design-tokens/design-token-manifest.yaml")
    categories = set(manifest.get("sources", {}))
    required = {"primitive", "semantic", "component", "layout", "motion", "density"}
    if categories != required:
        raise ValueError(f"token manifest categories differ: {sorted(categories ^ required)}")
    subprocess.run(["corepack", "pnpm", "--filter", "@vav/design-tokens", "build"], cwd=ROOT, check=True)
    patterns = {
        "hex": re.compile(r"#[0-9a-fA-F]{3,8}\b"),
        "rgb": re.compile(r"\brgba?\([^)]*\)"),
    }
    violations: list[dict[str, Any]] = []
    skill_files = sorted((ROOT / "skills/batch-22").glob("*/SKILL.md"))
    if len(skill_files) != 12:
        raise ValueError(f"Batch 22 must contain exactly 12 child Skills, found {len(skill_files)}")
    for skill_file in skill_files:
        frontmatter = skill_file.read_text(encoding="utf-8").split("---", 2)
        if len(frontmatter) != 3:
            raise ValueError(f"{skill_file.relative_to(ROOT)} has invalid frontmatter")
        metadata = yaml.safe_load(frontmatter[1])
        if not isinstance(metadata, dict) or not metadata.get("name") or not metadata.get("description"):
            raise ValueError(f"{skill_file.relative_to(ROOT)} lacks name or description")
    files = 0
    for configured in config["governed_paths"]:
        for path in sorted((ROOT / configured).rglob("*")):
            if path.suffix not in {".css", ".vue"}:
                continue
            files += 1
            text_value = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text_value.splitlines(), start=1):
                for kind, pattern in patterns.items():
                    for match in pattern.finditer(line):
                        violations.append({"file": str(path.relative_to(ROOT)), "line": line_number, "kind": kind, "value": match.group(0)})
    result = {
        "status": "PASS" if not violations else "FAIL",
        "checked_files": files,
        "skills": len(skill_files),
        "violations": violations,
        "generated": {name: sha256(ROOT / f"packages/design-tokens/generated/tokens.{name}") for name in ("css", "json", "ts", "scss")},
    }
    write("token-check.json", result)
    if violations:
        raise ValueError(f"governed UI contains {len(violations)} hard-coded color literals")
    return result


def page_audit() -> dict[str, Any]:
    exceptions = {item["component"]: item["reason"] for item in load_yaml(ROOT / "config/ui/page-audit-exceptions.yaml")["exceptions"]}
    audited: list[dict[str, Any]] = []
    for app in ("user-web", "admin-web"):
        router = ROOT / "apps" / app / "src/router/index.ts"
        source = router.read_text(encoding="utf-8")
        imports = {name: location for name, location in re.findall(r'import\s+(\w+)\s+from\s+"@/([^\"]+\.vue)"', source)}
        for match in re.finditer(r"\{\s*path:\s*[`\"]([^`\"]+)[`\"][^{}]*?component:\s*(\w+)", source, re.DOTALL):
            route_path, component = match.groups()
            location = imports.get(component)
            if not location:
                continue
            file_path = ROOT / "apps" / app / "src" / location
            body = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
            page_heading = bool(re.search(r"<(?:h1|UserPageLayout|ReviewWorkbench)\b", body))
            shell_heading = app == "admin-web" or component.endswith("Layout")
            exception = exceptions.get(component)
            audited.append({"application": app, "route_path": route_path, "component": component, "source": str(file_path.relative_to(ROOT)), "heading_contract": "page" if page_heading else "application_shell" if shell_heading else "documented_exception" if exception else "missing", "exception_reason": exception})
    missing = [item for item in audited if item["heading_contract"] == "missing"]
    shell_checks = {
        "user_skip_link": "<VSkipLink" in (ROOT / "apps/user-web/src/layouts/PublicLayout.vue").read_text(encoding="utf-8"),
        "user_main": 'id="main-content"' in (ROOT / "apps/user-web/src/layouts/PublicLayout.vue").read_text(encoding="utf-8"),
        "admin_skip_link": "<VSkipLink" in (ROOT / "apps/admin-web/src/layouts/AdminLayout.vue").read_text(encoding="utf-8"),
        "admin_main": 'id="admin-main"' in (ROOT / "apps/admin-web/src/layouts/AdminLayout.vue").read_text(encoding="utf-8"),
    }
    result = {"status": "PASS" if not missing and all(shell_checks.values()) else "FAIL", "routes": audited, "missing": missing, "shell_checks": shell_checks}
    write("page-audit.json", result)
    if result["status"] != "PASS":
        raise ValueError(f"page audit failed: {len(missing)} heading contracts missing")
    return result


def evidence() -> dict[str, Any]:
    reports = ["token-check.json", "page-audit.json", "accessibility.json", "responsive.json", "visual.json", "storybook.json"]
    items = []
    for name in reports:
        path = BUILD / name
        items.append({"name": name, "status": "PASS" if path.is_file() else "NOT_RUN", "checksum_sha256": sha256(path) if path.is_file() else None})
    technical = all(item["status"] == "PASS" for item in items)
    result = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "technical_status": "PASS" if technical else "FAIL",
        "production_certification": "NOT_CERTIFIED",
        "release_allowed": False,
        "evidence": items,
        "manual_gates": {"assistive_technology_review": "NOT_RUN", "visual_baseline_approval": "NOT_RUN", "real_device_review": "NOT_RUN"},
    }
    write("evidence-manifest.json", result)
    if not technical:
        raise ValueError("UI technical evidence is incomplete")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["token-check", "page-audit", "evidence"])
    args = parser.parse_args()
    result = {"token-check": token_check, "page-audit": page_audit, "evidence": evidence}[args.action]()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
