# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.skills_platform import service
from vav.modules.skills_platform.schemas import (
    ExecuteSkillRequest,
    InstallPlanRequest,
    MarketplaceListingRequest,
    ReviewDecisionRequest,
)


async def _operator() -> UUID:
    async with session_factory() as session:
        email = f"skill-operator-{uuid4()}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("SkillOperator!2026"),
            status="active",
            email_verified_at=datetime.now(UTC),
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _registered_fixture(*, signature: str = "verified") -> tuple[str, UUID]:
    suffix = uuid4().hex[:12]
    skill_name = f"vav.test.echo-{suffix}"
    manifest = {
        "apiVersion": "skills.vav.io/v1",
        "kind": "Skill",
        "metadata": {"name": skill_name, "version": "1.0.0"},
        "spec": {
            "type": "query",
            "runtime": "sandbox",
            "permissions": [],
            "execution": {"idempotency": "not_required", "timeoutSeconds": 5},
            "security": {"riskLevel": "low", "networkAccess": "none"},
        },
    }
    manifest_payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(manifest_payload.encode()).hexdigest()
    async with session_factory() as session:
        publisher_id = await session.scalar(
            text(
                "INSERT INTO skill_publishers (publisher_code,display_name,publisher_type,verification_status,"
                "signing_key_manifest,status,verified_at) VALUES (:code,'Test Publisher','organization','verified',"
                "'{}'::jsonb,'active',now()) RETURNING id"
            ),
            {"code": f"test-publisher-{suffix}"},
        )
        skill_id = await session.scalar(
            text(
                "INSERT INTO registered_skills (skill_name,publisher_id,display_name,description,skill_type,"
                "visibility,trust_level,lifecycle_status) VALUES (:name,:publisher,'Echo','Test echo','query',"
                "'organization_private','verified_publisher','active') RETURNING id"
            ),
            {"name": skill_name, "publisher": publisher_id},
        )
        version_id = await session.scalar(
            text(
                "INSERT INTO registered_skill_versions (registered_skill_id,semantic_version,manifest_version,"
                "runtime_api_version,manifest,manifest_checksum,package_reference_encrypted,package_checksum,"
                "sbom_reference_encrypted,provenance_reference_encrypted,signature_status,security_status,"
                "review_status,compatibility_status,published_at) VALUES (:skill,'1.0.0','1.0','1.0',"
                "CAST(:manifest AS jsonb),:checksum,'test://package',:checksum,'test://sbom','test://provenance',"
                ":signature,'passed','approved','compatible',now()) RETURNING id"
            ),
            {
                "skill": skill_id,
                "manifest": manifest_payload,
                "checksum": checksum,
                "signature": signature,
            },
        )
        await session.execute(
            text(
                "UPDATE registered_skills SET current_stable_version_id=:version,latest_version_id=:version "
                "WHERE id=:skill"
            ),
            {"version": version_id, "skill": skill_id},
        )
        await session.commit()
        assert isinstance(version_id, UUID)
        return skill_name, version_id


@pytest.mark.asyncio
async def test_install_activate_and_queue_are_fail_closed_and_idempotent() -> None:
    actor = await _operator()
    skill_name, _version_id = await _registered_fixture()
    async with session_factory() as session:
        plan = await service.create_install_plan(
            session,
            actor,
            InstallPlanRequest(
                skill_name=skill_name,
                semantic_version="1.0.0",
                environment="test",
            ),
        )
        assert plan["approval_required"] is False
        installation = await service.create_installation(
            session, actor, plan["id"], plan["plan_checksum"]
        )
        assert installation["status"] == "validating"
        activated = await service.activate_installation(session, installation["id"], actor)
        assert activated["status"] == "active"

        payload = ExecuteSkillRequest(
            input={"message": "hello"},
            idempotency_key=f"echo-{uuid4().hex}",
            deadline=datetime.now(UTC) + timedelta(seconds=30),
        )
        first = await service.queue_execution(session, actor, skill_name, payload)
        second = await service.queue_execution(session, actor, skill_name, payload)
        assert first["id"] == second["id"]
        assert first["status"] == "queued"


@pytest.mark.asyncio
async def test_unsigned_version_is_rejected_before_install_plan() -> None:
    actor = await _operator()
    skill_name, _version_id = await _registered_fixture(signature="failed")
    async with session_factory() as session:
        with pytest.raises(VavError) as error:
            await service.create_install_plan(
                session,
                actor,
                InstallPlanRequest(
                    skill_name=skill_name,
                    semantic_version="1.0.0",
                    environment="production",
                ),
            )
        assert error.value.code == "SKILL_SIGNATURE_REQUIRED"


@pytest.mark.asyncio
async def test_marketplace_requires_automated_and_independent_human_review() -> None:
    submitter, reviewer = await _operator(), await _operator()
    skill_name, version_id = await _registered_fixture()
    listing_payload = MarketplaceListingRequest(
        skill_name=skill_name,
        version_id=version_id,
        category_codes=["examples"],
        summary_localizations={
            "zh-CN": "用于验证技能市场安全审核闭环的示例。",
            "en": "Example used to verify governed Marketplace review.",
        },
        pricing_model="free",
        support_policy={
            "contact": "support@example.com",
            "responseTimeHours": 48,
            "endOfSupportPolicy": "At least ninety days of migration notice.",
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
    )
    async with session_factory() as session:
        listing = await service.submit_listing(session, submitter, listing_payload)
        assert listing["listing_status"] == "human_review"
        with pytest.raises(VavError, match="separation of duties"):
            await service.decide_listing(
                session,
                listing["id"],
                submitter,
                ReviewDecisionRequest(
                    decision="approved", reason_code="REVIEW_PASSED", findings=[]
                ),
            )
        approved = await service.decide_listing(
            session,
            listing["id"],
            reviewer,
            ReviewDecisionRequest(decision="approved", reason_code="REVIEW_PASSED", findings=[]),
        )
        assert approved["listing_status"] == "approved"
        published = await service.publish_listing(session, listing["id"], reviewer)
        assert published["listing_status"] == "published"
        assert published["visibility"] == "public"
