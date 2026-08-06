from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vav_skill_cli.generator import create_skill
from vav_skill_cli.supply_chain import (
    generate_provenance,
    generate_sbom,
    scan_secrets,
    sign_package,
    verify_package,
)
from vav_skill_sdk.manifest import validate_manifest
from vav_skill_sdk.package import build_package


def _keys(tmp_path: Path) -> tuple[Path, Path]:
    private = Ed25519PrivateKey.generate()
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def test_generated_package_build_is_reproducible_and_valid(tmp_path: Path) -> None:
    package_root = create_skill(
        tmp_path / "source",
        name="vav.example.generated",
        skill_type="query",
        runtime="python",
    )
    manifest = validate_manifest(package_root / "skill.yaml")
    first = build_package(package_root, tmp_path / "first.vavskill")
    second = build_package(package_root, tmp_path / "second.vavskill")
    assert manifest.metadata.name == "vav.example.generated"
    assert first.package_sha256 == second.package_sha256
    assert first.content_sha256 == second.content_sha256


def test_sbom_provenance_signature_and_tamper_detection(tmp_path: Path) -> None:
    package_root = create_skill(
        tmp_path / "source",
        name="vav.example.signed",
        skill_type="command",
        runtime="sandbox",
    )
    archive = build_package(package_root, tmp_path / "skill.vavskill").archive
    sbom_path = tmp_path / "sbom.cdx.json"
    provenance_path = tmp_path / "provenance.json"
    signature_path = tmp_path / "signature.json"
    sbom = generate_sbom(package_root, sbom_path)
    provenance = generate_provenance(
        archive,
        sbom_path,
        provenance_path,
        source_root=package_root,
        builder_id="test://vav-skill-builder",
    )
    private_path, public_path = _keys(tmp_path)
    sign_package(archive, private_path, signature_path, key_id="test-key-1")
    result = verify_package(archive, signature_path, public_path)
    assert sbom["bomFormat"] == "CycloneDX"
    assert provenance["predicateType"] == "https://slsa.dev/provenance/v1"
    assert result["verified"] is True

    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="does not match"):
        verify_package(archive, signature_path, public_path)


def test_secret_scan_blocks_credentials_without_returning_secret(
    tmp_path: Path,
) -> None:
    secret = "super-sensitive-value-that-must-not-leak"
    (tmp_path / "unsafe.py").write_text(f'api_key = "{secret}"\n', encoding="utf-8")
    findings = scan_secrets(tmp_path)
    assert findings == ("unsafe.py",)
    assert secret not in json.dumps(findings)
