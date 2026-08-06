"""Immutable version registry with trust, compatibility, and revocation gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from vav_skill_sdk.models import SkillManifest
from vav_skill_runtime.versions import parse_version, satisfies

TrustLevel = Literal[
    "builtin_trusted",
    "official_signed",
    "verified_publisher",
    "community_reviewed",
    "unverified",
    "quarantined",
    "revoked",
]


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class RegisteredVersion:
    manifest: SkillManifest
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    error_schema: dict[str, Any]
    package_checksum: str
    signature_status: Literal["verified", "unverified", "revoked"]
    security_status: Literal["passed", "blocked", "quarantined"]
    review_status: Literal["approved", "pending", "rejected"]
    trust_level: TrustLevel


class SkillRegistry:
    def __init__(self, *, require_signature: bool = True, allow_unverified: bool = False) -> None:
        self.require_signature = require_signature
        self.allow_unverified = allow_unverified
        self._versions: dict[str, dict[str, RegisteredVersion]] = {}
        self._revoked_packages: set[str] = set()

    def register(self, version: RegisteredVersion) -> None:
        name = version.manifest.metadata.name
        semantic_version = version.manifest.metadata.version
        versions = self._versions.setdefault(name, {})
        existing = versions.get(semantic_version)
        if existing and existing != version:
            raise RegistryError(f"active Skill version is immutable: {name}@{semantic_version}")
        if existing:
            return
        versions[semantic_version] = version

    def revoke_package(self, checksum: str) -> None:
        self._revoked_packages.add(checksum)

    def executable(self, version: RegisteredVersion) -> None:
        if version.package_checksum in self._revoked_packages:
            raise RegistryError("Skill package is revoked")
        if version.trust_level in {"quarantined", "revoked"}:
            raise RegistryError(f"Skill trust state blocks execution: {version.trust_level}")
        if version.security_status != "passed" or version.review_status != "approved":
            raise RegistryError("Skill security or review state blocks execution")
        if self.require_signature and version.signature_status != "verified":
            raise RegistryError("production Skill package requires a verified signature")
        if not self.allow_unverified and version.trust_level == "unverified":
            raise RegistryError("unverified Skill packages are disabled")

    def resolve(self, name: str, constraint: str) -> RegisteredVersion:
        candidates = self._versions.get(name, {})
        compatible = [
            item for version, item in candidates.items() if satisfies(version, constraint)
        ]
        if not compatible:
            raise RegistryError(f"no version of {name} satisfies {constraint}")
        compatible.sort(
            key=lambda item: parse_version(item.manifest.metadata.version), reverse=True
        )
        resolved = compatible[0]
        self.executable(resolved)
        return resolved

    def get(self, name: str, version: str) -> RegisteredVersion:
        try:
            found = self._versions[name][version]
        except KeyError as exc:
            raise RegistryError(f"Skill version not found: {name}@{version}") from exc
        self.executable(found)
        return found
