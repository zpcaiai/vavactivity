# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.quality import design_service
from vav.modules.quality.design_schemas import AuditRunCreate, BaselineCreate, TokenReleaseCreate


async def _operator(label: str) -> UUID:
    async with session_factory() as session:
        email = f"design-{label}-{uuid4().hex}@example.com"
        user = User(email=email, display_email=email, password_hash=PasswordHasher().hash("DesignOperator!2026"), status="active", email_verified_at=datetime.now(UTC), preferred_locale="zh-CN", timezone="Asia/Shanghai")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest.mark.asyncio
async def test_token_release_requires_separation_and_complete_accepted_evidence() -> None:
    author = await _operator("author")
    reviewer = await _operator("reviewer")
    version = f"22.0.{uuid4().int}"
    async with session_factory() as session:
        release = await design_service.create_token_release(session, author, TokenReleaseCreate(token_version=version, manifest_checksum_sha256="a" * 64, generated_checksum_sha256="b" * 64, change_summary="Production token release with generated artifact parity."))
        with pytest.raises(VavError, match="independent"):
            await design_service.approve_token_release(session, author, release["id"])
        approved = await design_service.approve_token_release(session, reviewer, release["id"])
        assert approved["status"] == "approved"
        with pytest.raises(VavError, match="missing"):
            await design_service.release_tokens(session, reviewer, release["id"], {})
        evidence = {name: {"status": "accepted", "checksum_sha256": uuid4().hex + uuid4().hex} for name in ("token_build", "component_tests", "accessibility_review", "visual_baseline_review")}
        released = await design_service.release_tokens(session, reviewer, release["id"], evidence)
        assert released["status"] == "released"


@pytest.mark.asyncio
async def test_accessibility_audit_cannot_auto_certify_and_needs_independent_review() -> None:
    runner = await _operator("runner")
    reviewer = await _operator("a11y-reviewer")
    async with session_factory() as session:
        with pytest.raises(VavError, match="manual review"):
            await design_service.create_audit(session, runner, AuditRunCreate(audit_code=f"A11Y.AUTO.{uuid4().hex[:8].upper()}", audit_type="accessibility", application_code="design-system", git_commit=uuid4().hex, environment="ci", status="technical_pass", evidence_checksum_sha256="c" * 64))
        audit = await design_service.create_audit(session, runner, AuditRunCreate(audit_code=f"A11Y.REVIEW.{uuid4().hex[:8].upper()}", audit_type="accessibility", application_code="design-system", git_commit=uuid4().hex, environment="ci", status="technical_pass", evidence_checksum_sha256="d" * 64, manual_review_required=True))
        with pytest.raises(VavError, match="independent"):
            await design_service.review_audit(session, runner, audit["id"], "approve", "Self approval must remain forbidden.")
        approved = await design_service.review_audit(session, reviewer, audit["id"], "approve", "Keyboard and assistive technology evidence reviewed.")
        assert approved["status"] == "approved"


@pytest.mark.asyncio
async def test_visual_baseline_requires_independent_approval() -> None:
    author = await _operator("baseline-author")
    reviewer = await _operator("baseline-reviewer")
    async with session_factory() as session:
        baseline = await design_service.create_baseline(session, author, BaselineCreate(baseline_code=f"design-system.home.{uuid4().hex[:8]}", application_code="design-system", route_path="/", viewport="desktop-1440", theme="light", locale="zh-CN", density="comfortable", artifact_reference="artifact://synthetic/design-system-home.png", checksum_sha256="e" * 64))
        with pytest.raises(VavError, match="independent"):
            await design_service.decide_baseline(session, author, baseline["id"], "approve", "The author cannot approve their own baseline.")
        approved = await design_service.decide_baseline(session, reviewer, baseline["id"], "approve", "Visual content and synthetic fixture policy reviewed.")
        assert approved["status"] == "approved"
