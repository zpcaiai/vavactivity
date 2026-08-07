"""Deterministic, traversal-safe .vavskill package builder."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

from vav_skill_sdk.manifest import validate_manifest

FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
IGNORED_NAMES = {".DS_Store", "signature.sig", "checksums.json"}


@dataclass(frozen=True)
class PackageBuild:
    archive: Path
    package_sha256: str
    content_sha256: str
    files: tuple[str, ...]


def _entries(source: Path) -> list[tuple[str, bytes]]:
    collected: list[tuple[str, bytes]] = []
    for candidate in sorted(source.rglob("*")):
        if candidate.is_dir() or candidate.name in IGNORED_NAMES or ".git" in candidate.parts:
            continue
        if candidate.is_symlink():
            raise ValueError(f"symbolic links are forbidden in Skill packages: {candidate}")
        relative = candidate.relative_to(source).as_posix()
        if relative.startswith("/") or ".." in Path(relative).parts:
            raise ValueError(f"unsafe package path: {relative}")
        payload = candidate.read_bytes()
        if len(payload) > 10 * 1024 * 1024:
            raise ValueError(f"package member exceeds 10 MiB: {relative}")
        collected.append((relative, payload))
    return collected


def build_package(source_dir: str | Path, destination: str | Path) -> PackageBuild:
    source = Path(source_dir).resolve()
    validate_manifest(source / "skill.yaml")
    entries = _entries(source)
    checksums = {name: hashlib.sha256(payload).hexdigest() for name, payload in entries}
    checksum_payload = (
        json.dumps(checksums, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    entries.append(("checksums.json", checksum_payload))
    entries.sort(key=lambda item: item[0])

    content_hasher = hashlib.sha256()
    for name, payload in entries:
        content_hasher.update(name.encode())
        content_hasher.update(b"\0")
        content_hasher.update(hashlib.sha256(payload).digest())

    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_STORED, strict_timestamps=True
    ) as archive:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, FIXED_TIMESTAMP)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, payload)
    return PackageBuild(
        archive=target,
        package_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        content_sha256=content_hasher.hexdigest(),
        files=tuple(name for name, _ in entries),
    )
