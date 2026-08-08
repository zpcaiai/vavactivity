# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.quality import service
from vav.modules.quality.schemas import (
    EvidenceRegister,
    GateDefinitionCreate,
    ReleaseEvaluationRequest,
    RequirementCreate,
)


async def _operator(label: str) -> UUID:
    async with session_factory() as session:
        email = f"quality-{label}-{uuid4().hex}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("QualityOperator!2026"),
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
async def test_requirement_approval_uses_independent_reviewer() -> None:
    author = await _operator("author")
    reviewer = await _operator("reviewer")
    suffix = uuid4().hex[:8].upper()
    async with session_factory() as session:
        requirement = await service.create_requirement(
            session,
            author,
            RequirementCreate(
                requirement_code=f"REQ-VAV-TEST-{suffix}-001",
                title="Independent quality requirement",
                description="A production requirement must be reviewed independently.",
                source_type="product_requirement",
                requirement_type="business",
                business_domain="quality",
                criticality="critical",
                acceptance_criteria=[{"criterion": "approved"}],
                owner_team="quality_engineering",
            ),
        )
        approved = await service.transition_requirement(
            session, requirement["id"], reviewer, "approved"
        )
        assert approved["status"] == "approved"
        assert approved["approved_by"] == reviewer


@pytest.mark.asyncio
async def test_current_evidence_drives_go_and_independent_certification() -> None:
    author = await _operator("gate-author")
    reviewer = await _operator("gate-reviewer")
    suffix = uuid4().hex[:8].upper()
    release_type = f"integration-{suffix.lower()}"
    release_version = f"21.0.{int(suffix[:2], 16)}"
    commit = uuid4().hex + uuid4().hex
    async with session_factory() as session:
        gate = await service.create_gate(
            session,
            author,
            GateDefinitionCreate(
                gate_code=f"GATE-INTEGRATION-{suffix}",
                semantic_version="1.0.0",
                name="Integration evidence gate",
                category="integration",
                enforcement_level="required",
                condition_definition={
                    "metric": "integration_statuses",
                    "operator": "all_passed",
                    "expected": "passed",
                },
                required_evidence_types=["integration_test_report"],
                applicable_release_types=[release_type],
            ),
        )
        await service.approve_gate(session, reviewer, gate["id"])
        evidence = await service.register_evidence(
            session,
            author,
            EvidenceRegister(
                evidence_code=f"EVID-INTEGRATION-{suffix}",
                evidence_type="integration_test_report",
                title="Integration test result",
                source_system="pytest",
                release_version=release_version,
                git_commit=commit,
                environment="ci",
                artifact_reference="s3://quality-evidence/integration.json",
                artifact_checksum_sha256="a" * 64,
                summary={"integration_statuses": ["passed", "passed"]},
                generated_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            ),
        )
        await service.transition_evidence(session, reviewer, evidence["id"], "validated")
        await service.transition_evidence(session, reviewer, evidence["id"], "accepted")
        evaluation = await service.evaluate_release(
            session,
            author,
            release_version,
            ReleaseEvaluationRequest(
                git_commit=commit,
                environment="ci",
                release_type=release_type,
            ),
        )
        assert evaluation["decision"] == "go"
        certification = await service.certify_release(
            session,
            reviewer,
            release_version,
            "ci",
            {"evidence_ids": [str(evidence["id"])], "git_commit": commit},
        )
        assert certification["certification_status"] == "certified"


@pytest.mark.asyncio
async def test_production_evaluation_fails_closed_without_approved_gates_and_verified_scope() -> (
    None
):
    actor = await _operator("production-evaluator")
    suffix = uuid4().hex[:8].lower()
    async with session_factory() as session:
        evaluation = await service.evaluate_release(
            session,
            actor,
            f"production-{suffix}",
            ReleaseEvaluationRequest(
                git_commit=uuid4().hex + uuid4().hex,
                environment="production",
                release_type=f"unconfigured-{suffix}",
            ),
        )
        assert evaluation["decision"] == "no_go"
        assert "no_applicable_approved_gate" in " ".join(evaluation["failure_reasons"])
