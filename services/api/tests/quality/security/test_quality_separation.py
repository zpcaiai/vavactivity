# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.quality import service
from vav.modules.quality.schemas import (
    GateDefinitionCreate,
    RequirementCreate,
    WaiverRequest,
)


async def _operator() -> UUID:
    async with session_factory() as session:
        email = f"quality-security-{uuid4().hex}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("QualitySecurity!2026"),
            status="active",
            email_verified_at=datetime.now(UTC),
            preferred_locale="en",
            timezone="UTC",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest.mark.asyncio
async def test_requirement_author_cannot_self_approve() -> None:
    actor = await _operator()
    suffix = uuid4().hex[:8].upper()
    async with session_factory() as session:
        requirement = await service.create_requirement(
            session,
            actor,
            RequirementCreate(
                requirement_code=f"REQ-VAV-SECURITY-{suffix}-001",
                title="Separation required",
                description="An author must never approve this requirement.",
                source_type="security_policy",
                requirement_type="security",
                business_domain="quality",
                criticality="blocker",
                acceptance_criteria=[{"criterion": "independent"}],
                owner_team="security_engineering",
            ),
        )
        with pytest.raises(VavError, match="independent"):
            await service.transition_requirement(session, requirement["id"], actor, "approved")


@pytest.mark.asyncio
async def test_nonwaivable_gate_rejects_waiver_approval() -> None:
    requester = await _operator()
    approver = await _operator()
    async with session_factory() as session:
        existing = next(
            (
                item
                for item in await service.list_gates(session)
                if item["gate_code"] == "GATE-SECURITY-CRITICAL"
            ),
            None,
        )
        if existing is None:
            gate = await service.create_gate(
                session,
                requester,
                GateDefinitionCreate(
                    gate_code="GATE-SECURITY-CRITICAL",
                    semantic_version=f"1.0.{int(uuid4().hex[:2], 16)}",
                    name="Critical security gate",
                    category="security",
                    enforcement_level="blocker",
                    condition_definition={
                        "metric": "critical_findings",
                        "operator": "eq",
                        "expected": 0,
                    },
                    required_evidence_types=["security_report"],
                    applicable_release_types=["security-test"],
                ),
            )
        else:
            gate = existing
        waiver = await service.request_waiver(
            session,
            requester,
            WaiverRequest(
                gate_definition_id=gate["id"],
                justification="Temporary exception requested to prove that policy rejects it.",
                mitigation_conditions={"owner": "security"},
                scope={"release_version": "security-test", "environment": "ci"},
                valid_from=datetime.now(UTC) - timedelta(minutes=1),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            ),
        )
        with pytest.raises(VavError, match="non-waivable"):
            await service.approve_waiver(session, approver, waiver["id"])
