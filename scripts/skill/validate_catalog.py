#!/usr/bin/env python3
"""Validate the repository's batch-deliverable Skill catalog.

This is intentionally a static, fail-closed check. It proves that the declared
Skill surface exists and is structurally readable; it does not claim that a
runtime, provider, browser, production or human-certification gate passed.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "skills" / "catalog.yaml"
BATCH_PATTERN = re.compile(r"^batch-(\d{2})$")
CHILD_PATTERN = re.compile(r"^(\d{2})-[a-z0-9][a-z0-9-]*$")


def fail(message: str) -> None:
    raise SystemExit(f"Skill catalog validation failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    require(len(parts) == 3 and not parts[0].strip(), f"{path.relative_to(ROOT)} lacks frontmatter")
    try:
        value = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        fail(f"{path.relative_to(ROOT)} has invalid frontmatter: {exc}")
    require(isinstance(value, dict), f"{path.relative_to(ROOT)} frontmatter is not an object")
    require(isinstance(value.get("name"), str) and value["name"].strip(), f"{path.relative_to(ROOT)} has no name")
    require(
        isinstance(value.get("description"), str) and value["description"].strip(),
        f"{path.relative_to(ROOT)} has no description",
    )
    return value


def load_catalog() -> dict[str, Any]:
    require(CATALOG.is_file(), "skills/catalog.yaml is missing")
    try:
        value = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        fail(f"skills/catalog.yaml is invalid: {exc}")
    require(isinstance(value, dict), "catalog root must be an object")
    require(value.get("schema_version") == "1.0", "unsupported catalog schema version")
    require(value.get("source", {}).get("document") == "ChatGPT-Codex 实现项目方案.md", "catalog source document drifted")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit a machine-readable summary")
    args = parser.parse_args()

    catalog = load_catalog()
    declarations = catalog.get("batches")
    require(isinstance(declarations, list), "batches must be a list")
    require(len(declarations) == catalog["delivery"]["total_batches"] == 32, "catalog must declare exactly 32 batches")

    expected_ids = [f"batch-{number:02d}" for number in range(1, 33)]
    actual_ids = [item.get("id") for item in declarations if isinstance(item, dict)]
    require(actual_ids == expected_ids, "batches must be ordered batch-01 through batch-32")

    seen_skill_names: set[str] = set()
    total_children = 0
    for item in declarations:
        require(isinstance(item, dict), "each batch declaration must be an object")
        batch_id = item["id"]
        require(item.get("phase") in {"product", "quality"}, f"{batch_id} has an invalid phase")
        parent = ROOT / "skills" / batch_id / "SKILL.md"
        require(parent.is_file(), f"{batch_id} parent SKILL.md is missing")
        frontmatter(parent)

        batch_dir = parent.parent
        # A batch may carry non-Skill fixtures (for example ``evals/``). Only
        # directories containing the canonical child SKILL.md are deliverables.
        child_dirs = sorted(
            path for path in batch_dir.iterdir() if path.is_dir() and (path / "SKILL.md").is_file()
        )
        numbers: list[int] = []
        for child_dir in child_dirs:
            match = CHILD_PATTERN.fullmatch(child_dir.name)
            require(match is not None, f"{batch_id} has an invalid child directory: {child_dir.name}")
            numbers.append(int(match.group(1)))
            child = child_dir / "SKILL.md"
            require(child.is_file(), f"{child.relative_to(ROOT)} is missing")
            metadata = frontmatter(child)
            skill_name = metadata["name"]
            require(skill_name not in seen_skill_names, f"duplicate Skill name: {skill_name}")
            seen_skill_names.add(skill_name)

        require(numbers == list(range(1, item["expected_child_skills"] + 1)), f"{batch_id} child numbering/count drifted")
        total_children += len(numbers)

    require(total_children == 384, f"unexpected child Skill total: {total_children}")
    summary = {"batches": len(declarations), "child_skills": total_children, "status": "PASS"}
    if args.json:
        import json

        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Skill catalog valid: {len(declarations)} batches, {total_children} child Skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
