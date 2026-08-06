from __future__ import annotations

import pytest

from tests.skill_support import registered_version
from vav_skill_runtime.installation import InstallationError, InstallationManager
from vav_skill_runtime.registry import SkillRegistry


def _permissioned_version() -> object:
    version = registered_version()
    payload = version.manifest.canonical()
    payload["spec"]["permissions"] = ["commerce.orders.create"]
    return version.__class__(
        **{
            **version.__dict__,
            "manifest": version.manifest.__class__.model_validate(payload),
        }
    )


def test_installation_requires_approval_and_health_before_activation() -> None:
    registry = SkillRegistry()
    version = _permissioned_version()
    registry.register(version)  # type: ignore[arg-type]
    manager = InstallationManager(registry)
    plan = manager.plan(version)  # type: ignore[arg-type]
    assert plan.dry_run is True
    assert plan.high_risk is True
    installation = manager.create(plan)
    with pytest.raises(InstallationError, match="permissions"):
        manager.activate(
            installation.installation_id,
            approved_permissions=frozenset(),
            health_passed=True,
        )
    assert installation.active_version is None
    with pytest.raises(InstallationError, match="health"):
        manager.activate(
            installation.installation_id,
            approved_permissions=frozenset({"commerce.orders.create"}),
            health_passed=False,
        )
    assert installation.active_version is None
