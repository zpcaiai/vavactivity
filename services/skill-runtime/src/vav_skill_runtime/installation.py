"""Dry-run-first installation, approval, activation, and rollback state machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from vav_skill_runtime.registry import RegisteredVersion, SkillRegistry


@dataclass(frozen=True)
class InstallPlan:
    skill_name: str
    target_version: str
    dependencies: tuple[str, ...]
    permissions_added: frozenset[str]
    configuration_required: tuple[str, ...]
    high_risk: bool
    requires_approval: bool
    dry_run: bool = True


@dataclass
class Installation:
    installation_id: UUID
    skill_name: str
    active_version: str | None
    target_version: str
    status: Literal["planned", "awaiting_approval", "installing", "active", "failed"]
    approved_permissions: frozenset[str]
    previous_version: str | None = None


class InstallationError(ValueError):
    pass


class InstallationManager:
    HIGH_RISK_PREFIXES = (
        "commerce.",
        "privacy.exports.",
        "notifications.send.",
        "safety.restrictions.",
        "secrets.",
    )

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry
        self._installations: dict[UUID, Installation] = {}

    def plan(
        self,
        target: RegisteredVersion,
        *,
        currently_approved: frozenset[str] = frozenset(),
    ) -> InstallPlan:
        requested = frozenset(target.manifest.spec.permissions)
        added = requested - currently_approved
        high_risk = any(item.startswith(self.HIGH_RISK_PREFIXES) for item in added)
        dependencies = tuple(next(iter(item)) for item in target.manifest.spec.dependencies.skills)
        return InstallPlan(
            skill_name=target.manifest.metadata.name,
            target_version=target.manifest.metadata.version,
            dependencies=dependencies,
            permissions_added=added,
            configuration_required=(),
            high_risk=high_risk,
            requires_approval=bool(added),
        )

    def create(self, plan: InstallPlan) -> Installation:
        installation = Installation(
            installation_id=uuid4(),
            skill_name=plan.skill_name,
            active_version=None,
            target_version=plan.target_version,
            status="awaiting_approval" if plan.requires_approval else "planned",
            approved_permissions=frozenset(),
        )
        self._installations[installation.installation_id] = installation
        return installation

    def activate(
        self,
        installation_id: UUID,
        *,
        approved_permissions: frozenset[str],
        health_passed: bool,
    ) -> Installation:
        installation = self._installations[installation_id]
        target = self._registry.get(installation.skill_name, installation.target_version)
        requested = frozenset(target.manifest.spec.permissions)
        if not requested.issubset(approved_permissions):
            installation.status = "awaiting_approval"
            raise InstallationError("all requested permissions require approval")
        if not health_passed:
            installation.status = "failed"
            raise InstallationError("installation health validation failed")
        installation.previous_version = installation.active_version
        installation.active_version = installation.target_version
        installation.approved_permissions = approved_permissions
        installation.status = "active"
        return installation

    def rollback(self, installation_id: UUID) -> Installation:
        installation = self._installations[installation_id]
        if installation.previous_version is None:
            raise InstallationError("no verified previous version is available")
        self._registry.get(installation.skill_name, installation.previous_version)
        installation.active_version, installation.previous_version = (
            installation.previous_version,
            installation.active_version,
        )
        installation.status = "active"
        return installation
