#!/usr/bin/env python3
"""Build and verify immutable backup checksum manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def build(directory: Path, revision: str, release: str) -> None:
    artifacts = {
        path.name: {"sha256": digest(path), "size": path.stat().st_size}
        for path in sorted(directory.glob("*.vavenc"))
    }
    manifest = {
        "schema_version": "1.0.0",
        "created_at": datetime.now(UTC).isoformat(),
        "database_revision": revision,
        "release_version": release,
        "artifacts": artifacts,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )


def verify(directory: Path) -> None:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["artifacts"].items():
        path = directory / name
        if not path.is_file() or digest(path) != expected["sha256"]:
            raise SystemExit(f"backup checksum mismatch: {name}")
        if path.stat().st_size != expected["size"]:
            raise SystemExit(f"backup size mismatch: {name}")
    print(f"backup manifest verified: {len(manifest['artifacts'])} artifacts")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    builder = subparsers.add_parser("build")
    builder.add_argument("directory", type=Path)
    builder.add_argument("--revision", required=True)
    builder.add_argument("--release", required=True)
    verifier = subparsers.add_parser("verify")
    verifier.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.operation == "build":
        build(args.directory, args.revision, args.release)
    else:
        verify(args.directory)


if __name__ == "__main__":
    main()
