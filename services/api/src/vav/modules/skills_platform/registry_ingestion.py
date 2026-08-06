"""Server-side verification and immutable storage for Skill release artifacts."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import boto3
import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from vav.common.exceptions import VavError
from vav.core.config import get_settings

MAX_PACKAGE_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_MEMBERS = 1000
REQUIRED_MEMBERS = {"skill.yaml", "README.md", "CHANGELOG.md", "LICENSE", "checksums.json"}
FORBIDDEN_MARKERS = (
    b"BEGIN PRIVATE KEY",
    b"BEGIN RSA PRIVATE KEY",
    b"postgresql://",
    b"docker.sock",
)
SECRET_PATTERNS = (
    re.compile(rb"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}"),
    re.compile(rb"(?i)postgres(?:ql)?(?:\+asyncpg)?://[^\s]+"),
)


@dataclass(frozen=True)
class ValidatedRelease:
    payload: bytes
    checksum: str
    key_id: str
    manifest: dict[str, Any]


def canonical_signing_key(key_id: str, public_key_pem: str) -> dict[str, Any]:
    try:
        key = serialization.load_pem_public_key(public_key_pem.encode())
    except (TypeError, ValueError) as exc:
        raise _reject("SKILL_PUBLISHER_KEY_INVALID", "Publisher key is not valid PEM.") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise _reject("SKILL_PUBLISHER_KEY_INVALID", "Publisher key must be Ed25519.")
    return {
        "keys": [
            {
                "keyId": key_id,
                "algorithm": "ed25519",
                "publicKeyPem": public_key_pem,
                "status": "active",
            }
        ]
    }


def _reject(code: str, message: str) -> VavError:
    return VavError(code, message, status_code=422)


def _decode_package(encoded: str, expected_checksum: str) -> bytes:
    try:
        payload = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise _reject("SKILL_PACKAGE_ENCODING_INVALID", "Package must be valid base64.") from exc
    if not payload or len(payload) > MAX_PACKAGE_BYTES:
        raise _reject("SKILL_PACKAGE_SIZE_INVALID", "Package exceeds the 10 MiB limit.")
    if hashlib.sha256(payload).hexdigest() != expected_checksum:
        raise _reject("SKILL_PACKAGE_CHECKSUM_MISMATCH", "Package checksum does not match.")
    return payload


def _read_archive(payload: bytes) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise _reject("SKILL_PACKAGE_INVALID", "Package is not a valid .vavskill archive.") from exc
    members = archive.infolist()
    if len(members) > MAX_MEMBERS:
        raise _reject("SKILL_PACKAGE_TOO_MANY_FILES", "Package contains too many files.")
    names: set[str] = set()
    expanded = 0
    result: dict[str, bytes] = {}
    for member in members:
        parts = member.filename.replace("\\", "/").split("/")
        mode = member.external_attr >> 16
        if (
            member.is_dir()
            or member.flag_bits & 0x1
            or member.filename.startswith("/")
            or ".." in parts
            or "" in parts
            or stat.S_ISLNK(mode)
            or member.filename in names
        ):
            raise _reject("SKILL_PACKAGE_PATH_INVALID", "Package contains an unsafe member.")
        names.add(member.filename)
        expanded += member.file_size
        if member.file_size > MAX_PACKAGE_BYTES or expanded > MAX_EXPANDED_BYTES:
            raise _reject("SKILL_PACKAGE_EXPANSION_INVALID", "Package expansion limit exceeded.")
        result[member.filename] = archive.read(member)
    missing = sorted(REQUIRED_MEMBERS - names)
    if missing:
        raise _reject(
            "SKILL_PACKAGE_INCOMPLETE", f"Required package members are missing: {missing}"
        )
    return result


def _verify_member_checksums(members: dict[str, bytes]) -> None:
    try:
        checksums = json.loads(members["checksums.json"])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _reject("SKILL_CHECKSUM_MANIFEST_INVALID", "checksums.json is invalid.") from exc
    expected_names = set(members) - {"checksums.json"}
    if not isinstance(checksums, dict) or set(checksums) != expected_names:
        raise _reject("SKILL_CHECKSUM_MANIFEST_INVALID", "checksums.json is incomplete.")
    for name in expected_names:
        if checksums[name] != hashlib.sha256(members[name]).hexdigest():
            raise _reject("SKILL_MEMBER_CHECKSUM_MISMATCH", "A package member was modified.")


def _validate_schema(schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise _reject("SKILL_SCHEMA_INVALID", f"{label} schema is invalid.") from exc
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise _reject(
            "SKILL_SCHEMA_OPEN_OBJECT",
            f"{label} schema must be an object with additionalProperties=false.",
        )


def _validate_manifest(
    members: dict[str, bytes],
    submitted: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    try:
        archived = yaml.safe_load(members["skill.yaml"])
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise _reject("SKILL_MANIFEST_INVALID", "Archived skill.yaml is invalid.") from exc
    if archived != submitted:
        raise _reject("SKILL_MANIFEST_MISMATCH", "Submitted and archived manifests differ.")
    schema_resource = files("vav_skill_sdk.schemas").joinpath("skill-manifest.schema.json")
    canonical_schema = json.loads(schema_resource.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(canonical_schema).iter_errors(submitted))
    if errors:
        raise _reject("SKILL_MANIFEST_INVALID", errors[0].message)
    references = {
        "input": submitted["spec"]["inputs"]["schema"],
        "output": submitted["spec"]["outputs"]["schema"],
        "error": submitted["spec"]["errors"]["schema"],
    }
    for label, reference in references.items():
        _validate_schema(schemas[label], label)
        try:
            archived_schema = json.loads(members[reference])
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _reject("SKILL_SCHEMA_MISSING", f"Archived {label} schema is missing.") from exc
        if archived_schema != schemas[label]:
            raise _reject(
                "SKILL_SCHEMA_MISMATCH", f"Submitted and archived {label} schemas differ."
            )
    return submitted


def _verify_supply_chain(
    payload: bytes,
    checksum: str,
    envelope: dict[str, Any],
    sbom: dict[str, Any],
    provenance: dict[str, Any],
    signing_key_manifest: dict[str, Any],
) -> str:
    if set(envelope) != {"algorithm", "keyId", "packageSha256", "signature"}:
        raise _reject("SKILL_SIGNATURE_ENVELOPE_INVALID", "Signature envelope is not canonical.")
    key_id = envelope.get("keyId")
    if envelope.get("algorithm") != "ed25519" or envelope.get("packageSha256") != checksum:
        raise _reject("SKILL_SIGNATURE_INVALID", "Signature metadata does not match the package.")
    keys = signing_key_manifest.get("keys", [])
    key = next(
        (
            item
            for item in keys
            if item.get("keyId") == key_id
            and item.get("algorithm") == "ed25519"
            and item.get("status") == "active"
        ),
        None,
    )
    if key is None:
        raise _reject(
            "SKILL_SIGNING_KEY_UNTRUSTED", "Signing key is not active for this publisher."
        )
    try:
        public_key = serialization.load_pem_public_key(key["publicKeyPem"].encode())
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError
        public_key.verify(base64.b64decode(envelope["signature"], validate=True), payload)
    except (InvalidSignature, ValueError, KeyError, TypeError) as exc:
        raise _reject("SKILL_SIGNATURE_INVALID", "Package signature verification failed.") from exc
    if sbom.get("bomFormat") != "CycloneDX" or not isinstance(sbom.get("components"), list):
        raise _reject("SKILL_SBOM_INVALID", "A canonical CycloneDX SBOM is required.")
    subjects = provenance.get("subject", [])
    if not any(item.get("digest", {}).get("sha256") == checksum for item in subjects):
        raise _reject("SKILL_PROVENANCE_INVALID", "Provenance does not bind this package.")
    return str(key_id)


def validate_release(
    *,
    package_base64: str,
    package_checksum: str,
    manifest: dict[str, Any],
    signature_envelope: dict[str, Any],
    sbom: dict[str, Any],
    provenance: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
    signing_key_manifest: dict[str, Any],
) -> ValidatedRelease:
    payload = _decode_package(package_base64, package_checksum)
    members = _read_archive(payload)
    _verify_member_checksums(members)
    if any(
        marker in content for marker in FORBIDDEN_MARKERS for content in members.values()
    ) or any(
        pattern.search(content) for pattern in SECRET_PATTERNS for content in members.values()
    ):
        raise _reject(
            "SKILL_PACKAGE_SECRET_DETECTED", "Package contains a forbidden secret marker."
        )
    canonical_manifest = _validate_manifest(members, manifest, schemas)
    key_id = _verify_supply_chain(
        payload, package_checksum, signature_envelope, sbom, provenance, signing_key_manifest
    )
    return ValidatedRelease(payload, package_checksum, key_id, canonical_manifest)


class SkillArtifactStore:
    async def put(self, release: ValidatedRelease) -> dict[str, str]:
        settings = get_settings()
        bucket = settings.media_bucket_private
        key = f"skills/packages/sha256/{release.checksum}.vavskill"
        client = boto3.client(
            "s3",
            endpoint_url=settings.media_s3_endpoint,
            region_name=settings.media_s3_region,
            aws_access_key_id=settings.media_s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.media_s3_secret_key.get_secret_value(),
        )
        await asyncio.to_thread(
            client.put_object,
            Bucket=bucket,
            Key=key,
            Body=release.payload,
            ContentType="application/vnd.vav.skill+zip",
            Metadata={"sha256": release.checksum},
        )
        response = await asyncio.to_thread(client.head_object, Bucket=bucket, Key=key)
        if (
            int(response.get("ContentLength", -1)) != len(release.payload)
            or response.get("Metadata", {}).get("sha256") != release.checksum
        ):
            raise VavError(
                "SKILL_ARTIFACT_STORAGE_FAILED",
                "Stored package integrity could not be confirmed.",
                status_code=503,
            )
        return {"provider": "s3", "bucket": bucket, "key": key, "sha256": release.checksum}


skill_artifact_store = SkillArtifactStore()
