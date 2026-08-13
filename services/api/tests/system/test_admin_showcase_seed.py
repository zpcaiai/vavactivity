from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vav.cli import seed_admin_showcase


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["production", "dr"])
async def test_admin_showcase_refuses_protected_environments(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    class Settings:
        pass

    settings = Settings()
    settings.environment = environment
    monkeypatch.setattr(seed_admin_showcase, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="protected environment"):
        await seed_admin_showcase.seed_admin_showcase()


def test_admin_showcase_has_three_row_gates_for_admin_surfaces() -> None:
    expected = {
        "administrators",
        "admin_sessions",
        "admin_invitations",
        "security_audit",
        "work_items",
        "saved_views",
        "bulk_jobs",
        "approvals",
        "exceptions",
        "configurations",
        "reveal_history",
        "certifications",
        "operation_audit",
        "quality_requirements",
        "design_components",
        "experience_routes",
        "process_definitions",
        "data_assets",
        "privacy_assets",
        "knowledge_documents",
    }
    assert expected <= set(seed_admin_showcase.ADMIN_PAGE_COVERAGE)
    assert set(seed_admin_showcase.ADMIN_PAGE_COVERAGE.values()) == {3}


def test_seed_manifest_registers_admin_showcase_as_non_production_data() -> None:
    manifest = Path("config/seeds/manifest.yaml").read_text(encoding="utf-8")
    production_prefix = manifest.split("  test:", 1)[0]

    assert "vav.cli.seed_admin_showcase" in manifest
    assert "vav.cli.seed_admin_showcase" not in production_prefix


def test_neon_staging_runs_complete_admin_showcase_after_migrations() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/backend-ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["neon-migrations"]["steps"]
    migration_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Apply pending migrations to Neon"
    )
    showcase_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Seed deterministic staging showcases"
    )
    commands = steps[showcase_index]["run"]

    assert migration_index < showcase_index
    assert "python -m vav.cli.seed_admin_showcase" in commands
    assert "python -m vav.cli.seed_test_showcase" not in commands
    assert "business_counts = await seed_test_showcase()" in Path(
        "services/api/src/vav/cli/seed_admin_showcase.py"
    ).read_text(encoding="utf-8")
    assert "--email admin@vav.com" in commands
    assert "--confirm-admin-showcase" in commands
