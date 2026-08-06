from __future__ import annotations

import pytest

from tests.skill_support import registered_version
from vav_skill_runtime.registry import RegistryError, SkillRegistry


def test_resolver_selects_highest_compatible_version() -> None:
    registry = SkillRegistry()
    registry.register(registered_version(version="1.0.0"))
    registry.register(registered_version(version="1.4.2"))
    registry.register(registered_version(version="2.0.0"))
    resolved = registry.resolve("vav.example.echo", ">=1.0.0 <2.0.0")
    assert resolved.manifest.metadata.version == "1.4.2"


def test_active_version_is_immutable() -> None:
    registry = SkillRegistry()
    original = registered_version()
    registry.register(original)
    changed = original.__class__(
        **{**original.__dict__, "package_checksum": "replacement"}
    )
    with pytest.raises(RegistryError, match="immutable"):
        registry.register(changed)


def test_unsigned_unverified_and_revoked_packages_fail_closed() -> None:
    unsigned = SkillRegistry()
    unsigned.register(registered_version(signature_status="unverified"))
    with pytest.raises(RegistryError, match="signature"):
        unsigned.resolve("vav.example.echo", "==1.0.0")

    unverified = SkillRegistry()
    unverified.register(registered_version(trust_level="unverified"))
    with pytest.raises(RegistryError, match="unverified"):
        unverified.resolve("vav.example.echo", "==1.0.0")

    revoked = SkillRegistry()
    version = registered_version()
    revoked.register(version)
    revoked.revoke_package(version.package_checksum)
    with pytest.raises(RegistryError, match="revoked"):
        revoked.get("vav.example.echo", "1.0.0")
