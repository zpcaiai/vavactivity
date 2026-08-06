from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.system import service
from vav.modules.system.schemas import (
    DeploymentEvidenceRequest,
    FeatureFlagCreateRequest,
    ReleaseRecordCreateRequest,
)


async def _operator() -> UUID:
    async with session_factory() as session:
        email = f"system-operator-{uuid4()}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("SystemOperator!2026"),
            status="active",
            email_verified_at=datetime.now(UTC),
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest.mark.asyncio
async def test_feature_flag_requires_independent_approval_before_activation() -> None:
    creator, approver = await _operator(), await _operator()
    async with session_factory() as session:
        created = await service.create_feature_flag(
            session,
            creator,
            FeatureFlagCreateRequest(
                flag_code=f"experience.e2e_{uuid4().hex}",
                default_value={"enabled": False},
                description="Independent approval integration fixture",
            ),
        )
        with pytest.raises(VavError, match="different administrator"):
            await service.approve_feature_flag(session, created["id"], creator)
        approved = await service.approve_feature_flag(session, created["id"], approver)
        assert approved["status"] == "approved"
        activated = await service.activate_feature_flag(session, created["id"], creator)
        assert activated["status"] == "active"
        assert activated["approved_by"] == approver


@pytest.mark.asyncio
async def test_release_record_preserves_immutable_artifact_identity() -> None:
    actor = await _operator()
    digest = "registry.example/vav@sha256:" + "a" * 64
    payload = ReleaseRecordCreateRequest(
        release_version=f"e2e-{uuid4().hex[:12]}",
        git_commit="b" * 40,
        image_digests={
            "api": digest,
            "worker": digest,
            "user_web": digest,
            "admin_web": digest,
        },
        database_revision="20260806_0083",
        contract_checksums={"openapi": "c" * 64},
        configuration_fingerprint={"non_secret_configuration_hash": "d" * 64},
    )
    async with session_factory() as session:
        created = await service.create_release_record(session, actor, payload)
        assert created["status"] == "candidate"
        assert created["image_digests"] == payload.image_digests
        assert created["evidence_manifest"] == {}


@pytest.mark.asyncio
async def test_release_requires_staging_evidence_and_four_eyes_before_production() -> None:
    creator, approver = await _operator(), await _operator()
    digest = "registry.example/vav@sha256:" + "e" * 64
    payload = ReleaseRecordCreateRequest(
        release_version=f"deploy-{uuid4().hex[:12]}",
        git_commit="f" * 40,
        image_digests={
            "api": digest,
            "worker": digest,
            "user_web": digest,
            "admin_web": digest,
        },
        database_revision="20260806_0083",
        contract_checksums={"openapi": "a" * 64},
        configuration_fingerprint={"non_secret_configuration_hash": "b" * 64},
    )
    evidence = DeploymentEvidenceRequest(
        artifact_sha256="c" * 64,
        completed_at=datetime.now(UTC),
        evidence={"smoke": "PASS"},
    )
    async with session_factory() as session:
        created = await service.create_release_record(session, creator, payload)
        staged = await service.record_release_deployment(
            session,
            release_id=created["id"],
            actor_id=creator,
            environment="staging",
            payload=evidence,
        )
        assert staged["status"] == "staging"
        with pytest.raises(VavError, match="different administrator"):
            await service.approve_release(session, created["id"], creator)
        approved = await service.approve_release(session, created["id"], approver)
        assert approved["approved_by"] == approver
        active = await service.record_release_deployment(
            session,
            release_id=created["id"],
            actor_id=creator,
            environment="production",
            payload=evidence,
        )
        assert active["status"] == "active"
        assert active["evidence_manifest"]["production"]["smoke"] == "PASS"
        rolled_back = await service.rollback_release(
            session, created["id"], creator, "e2e_release_rollback"
        )
        assert rolled_back["status"] == "rolled_back"
