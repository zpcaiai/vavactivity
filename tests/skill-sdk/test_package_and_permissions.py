from __future__ import annotations

from pathlib import Path

import pytest

from vav_skill_sdk.package import build_package
from vav_skill_sdk.permissions import effective_permissions

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "skill-packs/examples/vav.example.echo"


def test_package_build_is_byte_for_byte_deterministic(tmp_path: Path) -> None:
    first = build_package(EXAMPLE, tmp_path / "one.vavskill")
    second = build_package(EXAMPLE, tmp_path / "two.vavskill")
    assert first.package_sha256 == second.package_sha256
    assert first.content_sha256 == second.content_sha256
    assert first.archive.read_bytes() == second.archive.read_bytes()
    assert first.files == tuple(sorted(first.files))
    assert "checksums.json" in first.files


def test_permissions_are_an_intersection() -> None:
    effective = effective_permissions(
        {"profiles.self.read", "commerce.orders.create"},
        {"profiles.self.read", "notifications.send.transactional"},
        {"profiles.self.read", "commerce.orders.create"},
        {"profiles.self.read"},
    )
    assert effective == frozenset({"profiles.self.read"})


def test_overbroad_permissions_fail_closed() -> None:
    with pytest.raises(ValueError, match="overbroad"):
        effective_permissions({"admin.*"}, {"admin.*"}, {"admin.*"}, {"admin.*"})
