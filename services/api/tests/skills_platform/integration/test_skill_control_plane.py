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
from vav.modules.privacy.crypto import decrypt_private
from vav.modules.skills_platform import service
from vav.modules.skills_platform.executor import (
    AdapterRegistry,
    ExecutionContext,
    process_execution_batch,
)
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
    input_schema = {
        "type": "object",
        "required": ["message"],
        "properties": {"message": {"type": "string", "maxLength": 200}},
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "required": ["echo"],
        "properties": {"echo": {"type": "string", "maxLength": 200}},
        "additionalProperties": False,
    }
    error_schema = {
        "type": "object",
        "required": ["code"],
        "properties": {"code": {"type": "string"}},
        "additionalProperties": False,
    }
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
                "review_status,compatibility_status,input_schema,output_schema,error_schema,published_at) "
                "VALUES (:skill,'1.0.0','1.0','1.0',"
                "CAST(:manifest AS jsonb),:checksum,'test://package',:checksum,'test://sbom','test://provenance',"
                ":signature,'passed','approved','compatible',CAST(:input_schema AS jsonb),"
                "CAST(:output_schema AS jsonb),CAST(:error_schema AS jsonb),now()) RETURNING id"
            ),
            {
                "skill": skill_id,
                "manifest": manifest_payload,
                "checksum": checksum,
                "signature": signature,
                "input_schema": json.dumps(input_schema),
                "output_schema": json.dumps(output_schema),
                "error_schema": json.dumps(error_schema),
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

        stored_input = await session.scalar(
            text("SELECT input_encrypted FROM skill_executions WHERE id=:id"), {"id": first["id"]}
        )
        assert stored_input != payload.input
        assert "hello" not in json.dumps(stored_input)


@pytest.mark.asyncio
async def test_worker_executes_exact_isolated_adapter_and_encrypts_output() -> None:
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
        installation = await service.create_installation(
            session, actor, plan["id"], plan["plan_checksum"], {"private": "configured"}
        )
        await service.activate_installation(session, installation["id"], actor)
        queued = await service.queue_execution(
            session,
            actor,
            skill_name,
            ExecuteSkillRequest(
                input={"message": "worker hello"},
                deadline=datetime.now(UTC) + timedelta(seconds=30),
            ),
        )

        async def echo(payload: dict[str, object], context: ExecutionContext) -> dict[str, object]:
            assert context.actor_user_id == actor
            return {"echo": payload["message"]}

        registry = AdapterRegistry()
        registry.register(skill_name, "1.0.0", echo, isolated=True)
        assert await process_execution_batch(session, registry) >= 1
        result = (
            (
                await session.execute(
                    text(
                        "SELECT status,output_encrypted,output_hash,error_code FROM skill_executions WHERE id=:id"
                    ),
                    {"id": queued["id"]},
                )
            )
            .mappings()
            .one()
        )
        assert result["status"] == "succeeded"
        assert result["error_code"] is None
        assert "worker hello" not in json.dumps(result["output_encrypted"])
        assert decrypt_private(result["output_encrypted"]["ciphertext"]) == {"echo": "worker hello"}


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
