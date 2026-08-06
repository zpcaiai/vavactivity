from __future__ import annotations

import base64
import hashlib
import json
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.privacy.crypto import decrypt_private
from vav.modules.skills_platform import service
from vav.modules.skills_platform.registry_ingestion import ValidatedRelease
from vav.modules.skills_platform.schemas import (
    AppealDecisionRequest,
    AppealRequest,
    CreatePublisherRequest,
    MarketplaceListingRequest,
    PublisherDecisionRequest,
    PublishSkillVersionRequest,
    SecurityReviewRequest,
    SignatureRevocationRequest,
)


async def _operator() -> UUID:
    async with session_factory() as session:
        email = f"registry-operator-{uuid4()}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("RegistryOperator!2026"),
            status="active",
            email_verified_at=datetime.now(UTC),
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


def _release(tmp_path: Path, publisher_code: str) -> tuple[PublishSkillVersionRequest, str]:
    source = tmp_path / "source"
    (source / "schemas").mkdir(parents=True)
    object_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {"message": {"type": "string", "maxLength": 200}},
    }
    error_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["code"],
        "properties": {"code": {"type": "string"}},
    }
    manifest = {
        "apiVersion": "skills.vav.io/v1",
        "kind": "Skill",
        "metadata": {
            "name": f"vav.registry.echo-{uuid4().hex[:8]}",
            "displayName": "Registry Echo",
            "version": "1.0.0",
            "publisher": publisher_code,
            "description": "Governed registry integration fixture.",
            "license": "Apache-2.0",
        },
        "spec": {
            "type": "query",
            "runtime": "sandbox",
            "entrypoint": "skill:execute",
            "runtimeApiVersion": "1.0",
            "manifestVersion": "1.0",
            "inputs": {"schema": "schemas/input.schema.json"},
            "outputs": {"schema": "schemas/output.schema.json"},
            "errors": {"schema": "schemas/error.schema.json"},
            "permissions": [],
            "capabilities": {"provides": [], "requires": []},
            "dependencies": {"skills": [], "modules": [], "providers": []},
            "execution": {
                "timeoutSeconds": 5,
                "retryPolicy": "none",
                "idempotency": "not_required",
                "concurrencyLimit": 1,
            },
            "data": {"reads": [], "writes": []},
            "security": {
                "networkAccess": "none",
                "filesystemAccess": "none",
                "secretAccess": [],
                "riskLevel": "low",
                "userConfirmationRequired": False,
            },
            "compatibility": {
                "minimumPlatformVersion": "1.0.0",
                "maximumPlatformVersion": "1.x",
            },
            "observability": {
                "tracing": True,
                "metrics": True,
                "auditLevel": "metadata",
            },
            "tests": {"command": "pytest"},
        },
    }
    manifest_path = source / "skill.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    for name in ("README.md", "CHANGELOG.md", "LICENSE"):
        (source / name).write_text(f"{name}\n", encoding="utf-8")
    for name, schema in (
        ("input", object_schema),
        ("output", object_schema),
        ("error", error_schema),
    ):
        (source / f"schemas/{name}.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    archive = tmp_path / "release.vavskill"
    entries = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    entries["checksums.json"] = (
        json.dumps(
            {name: hashlib.sha256(content).hexdigest() for name, content in entries.items()},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        for name, content in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            output.writestr(info, content)
    package_payload = archive.read_bytes()
    package_checksum = hashlib.sha256(package_payload).hexdigest()
    sbom = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}
    provenance = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": archive.name, "digest": {"sha256": package_checksum}}],
    }
    private_key = Ed25519PrivateKey.generate()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    envelope = {
        "algorithm": "ed25519",
        "keyId": "release-key-1",
        "packageSha256": package_checksum,
        "signature": base64.b64encode(private_key.sign(package_payload)).decode(),
    }
    return (
        PublishSkillVersionRequest(
            publisher_id=uuid4(),
            manifest=manifest,
            package_base64=base64.b64encode(package_payload).decode(),
            package_checksum=package_checksum,
            signature_envelope=envelope,
            sbom=sbom,
            provenance=provenance,
            input_schema=json.loads((source / "schemas/input.schema.json").read_text()),
            output_schema=json.loads((source / "schemas/output.schema.json").read_text()),
            error_schema=json.loads((source / "schemas/error.schema.json").read_text()),
        ),
        public_pem,
    )


class _MemoryArtifactStore:
    def __init__(self) -> None:
        self.checksums: list[str] = []

    async def put(self, release: ValidatedRelease) -> dict[str, str]:
        checksum = release.checksum
        self.checksums.append(checksum)
        return {"provider": "test", "key": checksum, "sha256": checksum}


@pytest.mark.asyncio
async def test_publish_requires_independent_publisher_and_security_reviews(tmp_path: Path) -> None:
    owner, verifier, security_reviewer = await _operator(), await _operator(), await _operator()
    publisher_code = f"registry-{uuid4().hex[:12]}"
    release, public_pem = _release(tmp_path, publisher_code)
    artifact_store = _MemoryArtifactStore()
    async with session_factory() as session:
        publisher = await service.create_publisher(
            session,
            owner,
            CreatePublisherRequest(
                publisher_code=publisher_code,
                display_name="Registry Test Publisher",
                publisher_type="organization",
                key_id="release-key-1",
                public_key_pem=public_pem,
            ),
        )
        with pytest.raises(VavError, match="independent"):
            await service.decide_publisher(
                session,
                publisher["id"],
                owner,
                PublisherDecisionRequest(decision="verified", reason_code="IDENTITY_VERIFIED"),
            )
        await session.rollback()
        verified = await service.decide_publisher(
            session,
            publisher["id"],
            verifier,
            PublisherDecisionRequest(decision="verified", reason_code="IDENTITY_VERIFIED"),
        )
        assert verified["verification_status"] == "verified"
        release.publisher_id = publisher["id"]
        submitted = await service.publish_skill_version(
            session,
            owner,
            release,
            artifact_store=artifact_store,  # type: ignore[arg-type]
        )
        assert submitted["signature_status"] == "verified"
        assert submitted["security_status"] == "pending"
        assert artifact_store.checksums == [release.package_checksum]
        with pytest.raises(VavError, match="independently"):
            await service.review_skill_version_security(
                session,
                submitted["id"],
                owner,
                SecurityReviewRequest(
                    decision="passed",
                    compatible=True,
                    reason_code="SCANS_PASSED",
                    report={"sbom": "passed", "vulnerabilities": "passed"},
                ),
            )
        await session.rollback()
        approved = await service.review_skill_version_security(
            session,
            submitted["id"],
            security_reviewer,
            SecurityReviewRequest(
                decision="passed",
                compatible=True,
                reason_code="SCANS_PASSED",
                report={"sbom": "passed", "vulnerabilities": "passed"},
            ),
        )
        assert approved["review_status"] == "approved"
        assert approved["compatibility_status"] == "compatible"
        listing = await service.submit_listing(
            session,
            owner,
            MarketplaceListingRequest(
                skill_name=release.manifest["metadata"]["name"],
                version_id=submitted["id"],
                category_codes=["examples"],
                summary_localizations={
                    "zh-CN": "用于验证发布者申诉治理闭环的注册技能。",
                    "en": "Registry Skill used to verify the governed publisher appeal flow.",
                },
                support_policy={
                    "contact": "support@example.com",
                    "responseTimeHours": 48,
                    "endOfSupportPolicy": "Ninety days of migration notice.",
                },
                privacy_disclosure={
                    "reads": [],
                    "writes": [],
                    "externalDestinations": [],
                    "retention": "none",
                    "deletion": "No user data is retained.",
                    "modelTraining": False,
                    "automatedDecision": False,
                },
            ),
        )
        removed = await service.remove_listing(
            session, listing["id"], security_reviewer, "CONTROLLED_ENFORCEMENT_TEST"
        )
        assert removed["listing_status"] == "removed"
        appeal = await service.create_appeal(
            session,
            listing["id"],
            owner,
            AppealRequest(
                reason_code="EVIDENCE_REVIEW_REQUESTED",
                statement="Please independently review the controlled enforcement evidence.",
            ),
        )
        with pytest.raises(VavError, match="independent"):
            await service.decide_appeal(
                session,
                appeal["id"],
                owner,
                AppealDecisionRequest(
                    decision="accepted",
                    reason="The publisher cannot decide its own appeal.",
                ),
            )
        decided = await service.decide_appeal(
            session,
            appeal["id"],
            verifier,
            AppealDecisionRequest(
                decision="accepted",
                reason="Independent evidence review accepted the controlled appeal.",
            ),
        )
        assert decided["status"] == "accepted"


@pytest.mark.asyncio
async def test_signature_revocation_quarantines_versions_and_records_incident(
    tmp_path: Path,
) -> None:
    owner, verifier, security_reviewer = await _operator(), await _operator(), await _operator()
    publisher_code = f"revoke-{uuid4().hex[:12]}"
    release, public_pem = _release(tmp_path, publisher_code)
    async with session_factory() as session:
        publisher = await service.create_publisher(
            session,
            owner,
            CreatePublisherRequest(
                publisher_code=publisher_code,
                display_name="Revocation Test Publisher",
                publisher_type="verified_partner",
                key_id="release-key-1",
                public_key_pem=public_pem,
            ),
        )
        await service.decide_publisher(
            session,
            publisher["id"],
            verifier,
            PublisherDecisionRequest(decision="verified", reason_code="IDENTITY_VERIFIED"),
        )
        release.publisher_id = publisher["id"]
        version = await service.publish_skill_version(
            session,
            owner,
            release,
        )
        encrypted_reference = await session.scalar(
            text("SELECT package_reference_encrypted FROM registered_skill_versions WHERE id=:id"),
            {"id": version["id"]},
        )
        stored_reference = decrypt_private(encrypted_reference)
        assert stored_reference["provider"] == "s3"
        assert stored_reference["sha256"] == release.package_checksum
        await service.review_skill_version_security(
            session,
            version["id"],
            security_reviewer,
            SecurityReviewRequest(
                decision="passed",
                compatible=True,
                reason_code="SCANS_PASSED",
                report={"clean": True},
            ),
        )
        revoked = await service.revoke_signature(
            session,
            security_reviewer,
            SignatureRevocationRequest(
                publisher_id=publisher["id"],
                key_id="release-key-1",
                package_checksum=release.package_checksum,
                reason_code="KEY_COMPROMISE_TEST",
                reason="Controlled test of package-specific signature revocation.",
            ),
        )
        assert revoked["affected_versions"] == 1
        state = (
            (
                await session.execute(
                    text(
                        "SELECT signature_status,security_status,revoked_at "
                        "FROM registered_skill_versions "
                        "WHERE id=:id"
                    ),
                    {"id": version["id"]},
                )
            )
            .mappings()
            .one()
        )
        assert state["signature_status"] == "revoked"
        assert state["security_status"] == "quarantined"
        assert state["revoked_at"] is not None
        assert (
            await session.scalar(
                text("SELECT count(*) FROM skill_security_incidents WHERE skill_version_id=:id"),
                {"id": version["id"]},
            )
            == 1
        )
