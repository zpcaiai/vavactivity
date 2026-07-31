#!/usr/bin/env python3
"""Validate the VAV project charter and its fail-closed decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "project-manifest.yaml"
ALLOWED_STATUSES = {"foundation_in_progress", "planned", "blocked", "complete"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"manifest validation failed: {message}")


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value.startswith("{") and value.endswith("}"):
        entries: dict[str, Any] = {}
        for item in value[1:-1].split(","):
            key, item_value = item.split(":", 1)
            entries[key.strip()] = parse_scalar(item_value)
        return entries
    if value in {"null", "~"}:
        return None
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith(('"', "'")):
        return json.loads(value) if value.startswith('"') else value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def parse_project_yaml(text: str) -> dict[str, Any]:
    """Parse the deliberately small YAML subset used by project-manifest.yaml."""

    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()
    for index, source_line in enumerate(lines):
        line = source_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if content.startswith("- "):
            if not isinstance(parent, list):
                raise ValueError(f"unexpected list item: {content}")
            parent.append(parse_scalar(content[2:]))
            continue
        key, raw_value = content.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            parent[key] = parse_scalar(raw_value)
            continue
        next_nonempty = next(
            (
                candidate.strip()
                for candidate in lines[index + 1 :]
                if candidate.strip() and not candidate.lstrip().startswith("#")
            ),
            "",
        )
        child: Any = [] if next_nonempty.startswith("- ") else {}
        parent[key] = child
        stack.append((indent, child))
    return root


def load_manifest() -> dict[str, Any]:
    text = MANIFEST.read_text(encoding="utf-8")
    try:
        import yaml

        value = yaml.safe_load(text)
    except ModuleNotFoundError:
        value = parse_project_yaml(text)
    require(isinstance(value, dict), "root must be an object")
    return value


def main() -> None:
    manifest = load_manifest()
    phases = manifest.get("phases", {})
    require({"phase_1", "phase_2"} <= phases.keys(), "phase_1 and phase_2 are required")

    modules = manifest.get("module_registry", {})
    require(bool(modules), "module_registry cannot be empty")
    for name, module in modules.items():
        require(module.get("owner"), f"{name} has no owner")
        require(module.get("status") in ALLOWED_STATUSES, f"{name} has invalid status")
        require(module.get("phase") in phases, f"{name} references an unknown phase")

    registered = set(modules)
    phase_modules: set[str] = set()
    for phase_name, phase in phases.items():
        listed = phase.get("modules", [])
        require(bool(listed), f"{phase_name} has no modules")
        phase_modules.update(listed)
        for name in listed:
            require(name in registered, f"{phase_name} references unknown module {name}")
            require(modules[name]["phase"] == phase_name, f"{name} has inconsistent phase")
    require(registered == phase_modules, "every module must belong to exactly one listed phase")

    decisions = manifest.get("pending_decisions", {})
    require(bool(decisions), "pending_decisions cannot be empty")
    for key, decision in decisions.items():
        require(decision.get("status") == "undecided", f"{key} must default to undecided")
        require(decision.get("value") is None, f"{key} must not have a production default")
        require(decision.get("owner"), f"{key} has no owner")

    print(
        f"manifest valid: {len(modules)} modules, "
        f"{len(phases)} phases, {len(decisions)} fail-closed decisions"
    )


if __name__ == "__main__":
    main()
