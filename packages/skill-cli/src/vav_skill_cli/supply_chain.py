"""Deterministic SBOM, provenance, secret scanning, signing, and verification."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}"),
    re.compile(r"postgres(?:ql)?(?:\+asyncpg)?://[^\s]+"),
)
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml", ".toml", ".md"}


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scan_secrets(root: str | Path) -> tuple[str, ...]:
    findings: list[str] = []
    source = Path(root).resolve()
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES or ".git" in path.parts:
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            findings.append(path.relative_to(source).as_posix())
    return tuple(findings)


def _components(root: Path) -> list[dict[str, Any]]:
    components: dict[tuple[str, str], dict[str, Any]] = {}
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        import tomllib

        parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        for raw in parsed.get("project", {}).get("dependencies", []):
            match = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)", raw)
            if match:
                name, version = match.groups()
                components[("library", name.lower())] = {
                    "type": "library",
                    "name": name,
                    "version": version.lstrip("=<>~! ") or "unspecified",
                }
    package_json = root / "package.json"
    if package_json.is_file():
        parsed = json.loads(package_json.read_text(encoding="utf-8"))
        for section in ("dependencies", "peerDependencies"):
            for name, version in parsed.get(section, {}).items():
                components[("library", name)] = {
                    "type": "library",
                    "name": name,
                    "version": str(version),
                }
    return [components[key] for key in sorted(components)]


def generate_sbom(root: str | Path, destination: str | Path) -> dict[str, Any]:
    source = Path(root).resolve()
    manifest = source / "skill.yaml"
    serial_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    document: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial_hash[:8]}-{serial_hash[8:12]}-4{serial_hash[13:16]}-a{serial_hash[17:20]}-{serial_hash[20:32]}",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": source.name}},
        "components": _components(source),
    }
    Path(destination).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return document


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False, timeout=10
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def generate_provenance(
    package: str | Path,
    sbom: str | Path,
    destination: str | Path,
    *,
    source_root: str | Path,
    builder_id: str,
) -> dict[str, Any]:
    source = Path(source_root).resolve()
    document = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": "https://slsa.dev/provenance/v1",
        "subject": [{"name": Path(package).name, "digest": {"sha256": sha256_file(package)}}],
        "predicate": {
            "buildDefinition": {
                "buildType": "https://skills.vav.io/build/v1",
                "externalParameters": {"commit": _git(source, "rev-parse", "HEAD")},
                "internalParameters": {},
                "resolvedDependencies": [{"uri": "sbom", "digest": {"sha256": sha256_file(sbom)}}],
            },
            "runDetails": {
                "builder": {"id": builder_id},
                "metadata": {
                    "invocationId": sha256_file(package),
                    "startedOn": datetime.now(UTC).isoformat(),
                },
            },
        },
    }
    Path(destination).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return document


def sign_package(
    package: str | Path, private_key_path: str | Path, destination: str | Path, *, key_id: str
) -> dict[str, Any]:
    payload = Path(package).read_bytes()
    key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("only Ed25519 signing keys are supported")
    signature = key.sign(payload)
    envelope = {
        "algorithm": "ed25519",
        "keyId": key_id,
        "packageSha256": hashlib.sha256(payload).hexdigest(),
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    Path(destination).write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return envelope


def verify_package(
    package: str | Path, signature_path: str | Path, public_key_path: str | Path
) -> dict[str, Any]:
    payload = Path(package).read_bytes()
    envelope = json.loads(Path(signature_path).read_text(encoding="utf-8"))
    if (
        envelope.get("algorithm") != "ed25519"
        or envelope.get("packageSha256") != hashlib.sha256(payload).hexdigest()
    ):
        raise ValueError("signature envelope does not match the package")
    key = serialization.load_pem_public_key(Path(public_key_path).read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("only Ed25519 verification keys are supported")
    try:
        key.verify(base64.b64decode(envelope["signature"], validate=True), payload)
    except (InvalidSignature, ValueError, KeyError) as exc:
        raise ValueError("package signature is invalid") from exc
    return {
        "verified": True,
        "keyId": envelope["keyId"],
        "packageSha256": envelope["packageSha256"],
    }
