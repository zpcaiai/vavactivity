"""Structural contract of the Batch 21 quality control plane.

These checks run against the repository itself: manifests, the migration chain,
the Skill tree and the Make fragment must stay consistent with the module.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SKILL_DIRECTORIES = (
    "01-product-quality-constitution",
    "02-requirement-registry",
    "03-capability-inventory",
    "04-traceability-graph",
    "05-page-api-data-test-mapping",
    "06-business-closure-matrix",
    "07-exception-path-coverage",
    "08-gap-orphan-detection",
    "09-quality-risk-waiver",
    "10-release-gate-engine",
    "11-quality-evidence-certification",
    "12-quality-dashboard-testing",
)

REQUIRED_MAKE_TARGETS = (
    "batch-21",
    "quality-migrate",
    "quality-seed",
    "quality-sync",
    "quality-manifest-check",
    "quality-trace-check",
    "quality-closure-check",
    "quality-gap-check",
    "quality-gate-evaluate",
    "quality-test",
    "quality-gate-test",
    "quality-security-test",
    "quality-admin-e2e",
    "quality-evidence-build",
    "quality-release-report",
    "quality-verify",
)

QUALITY_TABLES = (
    "quality_requirements",
    "quality_capabilities",
    "quality_trace_nodes",
    "quality_trace_links",
    "quality_pages",
    "quality_api_operations",
    "quality_business_flows",
    "quality_business_flow_steps",
    "quality_exception_scenarios",
    "quality_gaps",
    "quality_risks",
    "quality_gate_definitions",
    "quality_waivers",
    "quality_evidence",
    "quality_gate_runs",
    "quality_release_evaluations",
    "quality_certifications",
)


def _root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "project-manifest.yaml").exists():
            return candidate
    return None


ROOT = _root() or Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "services/api/migrations/versions/20260806_0087_quality_governance.py"
)

pytestmark = pytest.mark.skipif(
    _root() is None, reason="structural contract requires the repository checkout"
)


def test_module_manifest_declares_quality_contract() -> None:
    manifest = yaml.safe_load(
        (ROOT / "services/api/src/vav/modules/quality/module.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["module"]["code"] == "quality"
    assert "identity" in manifest["dependencies"]["required"]
    assert 87 in manifest["database"]["revisions"]
    assert "quality." in manifest["permissions"]["prefixes"]


def test_migration_is_chained_after_batch_twenty() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260806_0087"' in source
    assert 'down_revision = "20260806_0086"' in source
    assert "def upgrade()" in source
    assert "def downgrade()" in source


def test_every_quality_table_is_created_and_dropped() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for table in QUALITY_TABLES:
        assert f"CREATE TABLE {table}" in source, table
        assert (
            f"DROP TABLE IF EXISTS {table}" in source or f"DROP TABLE {table}" in source
        ), table


def test_skill_tree_is_complete() -> None:
    skills = ROOT / "skills/batch-21"
    assert (skills / "SKILL.md").exists()
    for directory in SKILL_DIRECTORIES:
        skill = skills / directory / "SKILL.md"
        assert skill.exists(), directory
        text = skill.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert "name:" in text and "description:" in text


def test_make_fragment_exposes_every_required_target() -> None:
    fragment = (ROOT / "make/batch-21.mk").read_text(encoding="utf-8")
    for target in REQUIRED_MAKE_TARGETS:
        assert f"\n{target}:" in fragment or fragment.startswith(f"{target}:"), target
    for line in fragment.splitlines():
        if line.startswith("    ") and not line.startswith("\t"):
            raise AssertionError(f"recipe line is space indented: {line!r}")
    assert "|| true" not in fragment
    assert "quality-gate-evaluate" in fragment.split("quality-verify:", 1)[1]


@pytest.mark.parametrize(
    ("batch", "aggregate"),
    (
        (22, "ui-verify"),
        (23, "experience-verify"),
        (24, "process-verify"),
        (25, "data-integrity-verify"),
        (26, "admin-completeness-verify"),
    ),
)
def test_later_quality_batches_expose_canonical_entrypoints(
    batch: int, aggregate: str
) -> None:
    fragment = (ROOT / f"make/batch-{batch}.mk").read_text(encoding="utf-8")
    assert f"batch-{batch}: {aggregate}" in fragment


@pytest.mark.parametrize(
    ("batch", "aggregate", "browser_targets"),
    (
        (21, "quality-verify", ("quality-admin-e2e",)),
        (
            22,
            "ui-verify",
            (
                "ui-storybook-test",
                "ui-accessibility-test",
                "ui-responsive-test",
                "ui-visual-test",
            ),
        ),
        (23, "experience-verify", ("experience-user-e2e", "experience-admin-e2e")),
        (24, "process-verify", ("process-admin-e2e",)),
        (25, "data-integrity-verify", ("data-admin-e2e",)),
        (26, "admin-completeness-verify", ("admin-platform-e2e",)),
    ),
)
def test_batch_aggregates_include_browser_gates(
    batch: int, aggregate: str, browser_targets: tuple[str, ...]
) -> None:
    fragment = (ROOT / f"make/batch-{batch}.mk").read_text(encoding="utf-8")
    aggregate_dependencies = fragment.split(f"{aggregate}:", 1)[1]
    for target in browser_targets:
        assert target in aggregate_dependencies
    assert "NO_PROXY=127.0.0.1,localhost" in fragment
    assert "RUN_IF_TIMEOUT_SECONDS=600" in fragment


@pytest.mark.parametrize(
    ("control", "status_files"),
    (
        ("quality", ("admin-e2e-status.json",)),
        ("experience", ("user-e2e-status.json", "admin-e2e-status.json")),
        ("process", ("admin-e2e-status.json",)),
        ("data", ("admin-e2e-status.json",)),
        ("admin", ("browser-e2e-status.json",)),
    ),
)
def test_evidence_manifests_consume_browser_status_sidecars(
    control: str, status_files: tuple[str, ...]
) -> None:
    source = (ROOT / f"scripts/{control}/control.py").read_text(encoding="utf-8")
    for status_file in status_files:
        assert status_file in source


def test_quality_manifest_requirements_are_well_formed() -> None:
    from vav.modules.quality.domain import (
        REQUIREMENT_CODE_PATTERN,
        QualityCriticality,
        validate_code,
    )

    manifest = yaml.safe_load(
        (ROOT / "quality-manifest.yaml").read_text(encoding="utf-8")
    )
    requirements = manifest["requirements"]
    assert requirements
    codes = [item["code"] for item in requirements]
    assert len(codes) == len(set(codes))
    for requirement in requirements:
        validate_code(requirement["code"], REQUIREMENT_CODE_PATTERN, "Requirement")
        QualityCriticality(requirement["criticality"])
        assert requirement["source"] in {"project_plan", "batch_specification"}


def test_constitution_declares_non_waivable_gates() -> None:
    from vav.modules.quality.domain import NON_WAIVABLE_GATE_CODES

    manifest = yaml.safe_load(
        (ROOT / "quality-manifest.yaml").read_text(encoding="utf-8")
    )
    declared = set(manifest["constitution"]["non_waivable_gates"])
    assert declared == set(NON_WAIVABLE_GATE_CODES)
    assert manifest["constitution"]["release_policy"] == "fail_closed"
    assert manifest["constitution"]["production_conditional_go_allowed"] is False
