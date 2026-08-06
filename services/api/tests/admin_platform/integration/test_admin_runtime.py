# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.admin_platform import service
from vav.modules.admin_platform.schemas import (
    ApprovalCreate,
    ApprovalDecision,
    BulkPlan,
    CertificationEvaluate,
    ConfigurationAction,
    ConfigurationCreate,
    MaskRequest,
    RevealCreate,
    SavedViewCreate,
)
from vav.modules.identity.security import PasswordHasher


async def _user(label: str) -> UUID:
    async with session_factory() as session:
        email = f"admin-platform-{label}-{uuid4().hex}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("AdminPlatform!2026"),
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
async def test_saved_view_is_schema_validated_and_does_not_expand_columns() -> None:
    actor = await _user("saved-view")
    async with session_factory() as session:
        result = await service.create_saved_view(
            session,
            actor,
            SavedViewCreate(
                query_code="admin.work-items",
                name="Critical",
                filters={"status": "available"},
                sort="due_at",
                columns=["work_item_code", "status"],
            ),
        )
        assert result["visibility"] == "private"
        with pytest.raises(VavError, match="unregistered"):
            await service.create_saved_view(
                session,
                actor,
                SavedViewCreate(
                    query_code="admin.work-items",
                    name="Leak",
                    filters={},
                    sort="due_at",
                    columns=["safe_summary", "private_notes"],
                ),
            )


@pytest.mark.asyncio
async def test_bulk_requires_dry_run_freezes_selection_and_is_idempotent() -> None:
    actor = await _user("bulk")
    targets = [uuid4(), uuid4()]
    async with session_factory() as session:
        with pytest.raises(VavError, match="Dry Run"):
            await service.plan_bulk(
                session,
                actor,
                BulkPlan(
                    operation_code="ADMIN-BULK-DATA-PROJECTION-REBUILD",
                    target_ids=targets,
                    dry_run=False,
                    idempotency_key=f"bulk:{uuid4()}",
                ),
            )
        key = f"bulk:{uuid4()}"
        first = await service.plan_bulk(
            session,
            actor,
            BulkPlan(
                operation_code="ADMIN-BULK-DATA-PROJECTION-REBUILD",
                target_ids=targets + [targets[0]],
                expected_versions={str(targets[0]): 7},
                parameters={"partition": "zh-CN"},
                idempotency_key=key,
            ),
        )
        replay = await service.plan_bulk(
            session,
            actor,
            BulkPlan(
                operation_code="ADMIN-BULK-DATA-PROJECTION-REBUILD",
                target_ids=targets + [targets[0]],
                expected_versions={str(targets[0]): 7},
                parameters={"partition": "zh-CN"},
                idempotency_key=key,
            ),
        )
        assert first["id"] == replay["id"] and first["total_count"] == 2
        assert (
            await session.scalar(
                text("SELECT count(*) FROM admin_bulk_job_items WHERE bulk_job_id=:id"),
                {"id": first["id"]},
            )
            == 2
        )


@pytest.mark.asyncio
async def test_two_person_approval_denies_self_and_requires_distinct_reviewers() -> None:
    requester, reviewer_one, reviewer_two = (
        await _user("requester"),
        await _user("reviewer-one"),
        await _user("reviewer-two"),
    )
    async with session_factory() as session:
        request = await service.create_approval(
            session,
            requester,
            ApprovalCreate(
                policy_code="APPROVAL-CRITICAL-TWO-PERSON",
                capability_code="ADMIN-DATA-DIFFERENCE-REPAIR",
                target_entity_type="difference",
                target_entity_id=uuid4(),
                payload={"repair": "registered"},
                business_state_snapshot={"version": 1},
            ),
        )
        with pytest.raises(VavError, match="own request"):
            await service.decide_approval(
                session,
                requester,
                request["id"],
                ApprovalDecision(
                    decision="approved",
                    reason_code="verified",
                    rationale="I verified the evidence.",
                ),
            )
        first = await service.decide_approval(
            session,
            reviewer_one,
            request["id"],
            ApprovalDecision(
                decision="approved", reason_code="verified", rationale="First independent review."
            ),
        )
        second = await service.decide_approval(
            session,
            reviewer_two,
            request["id"],
            ApprovalDecision(
                decision="approved", reason_code="verified", rationale="Second independent review."
            ),
        )
        assert first["status"] == "in_review" and second["status"] == "approved"


@pytest.mark.asyncio
async def test_configuration_rejects_inline_secret_and_production_self_approval() -> None:
    creator, reviewer = await _user("config-creator"), await _user("config-reviewer")
    async with session_factory() as session:
        with pytest.raises(VavError, match="secret references"):
            await service.create_configuration(
                session,
                creator,
                ConfigurationCreate(
                    namespace_code="notifications.routing",
                    environment="production",
                    semantic_version="1.0.0",
                    configuration={"provider_secret": "raw-secret"},
                ),
            )
        version = await service.create_configuration(
            session,
            creator,
            ConfigurationCreate(
                namespace_code="notifications.routing",
                environment="production",
                semantic_version="1.0.0",
                configuration={
                    "provider_secret": "secret://notifications/provider",
                    "region": "ap-east",
                },
            ),
        )
        assert version["status"] == "review_required" and "raw-secret" not in str(
            version["configuration_encrypted"]
        )
        with pytest.raises(VavError, match="Creator"):
            await service.act_configuration(
                session, creator, version["id"], ConfigurationAction(action="approve")
            )
        approved = await service.act_configuration(
            session, reviewer, version["id"], ConfigurationAction(action="approve")
        )
        active = await service.act_configuration(
            session, reviewer, version["id"], ConfigurationAction(action="activate")
        )
        assert approved["status"] == "approved" and active["status"] == "active"


@pytest.mark.asyncio
async def test_reveal_requires_purpose_and_step_up_then_is_entity_scoped() -> None:
    actor, entity = await _user("reveal"), uuid4()
    async with session_factory() as session:
        with pytest.raises(VavError, match="Purpose"):
            await service.create_reveal(
                session,
                actor,
                RevealCreate(
                    policy_code="ADMIN-FIELD-USER-EMAIL",
                    entity_type="user",
                    entity_id=entity,
                    purpose_code="curiosity",
                    reason="This is not a permitted purpose.",
                    step_up_authenticated_at=datetime.now(UTC),
                ),
            )
        grant = await service.create_reveal(
            session,
            actor,
            RevealCreate(
                policy_code="ADMIN-FIELD-USER-EMAIL",
                entity_type="user",
                entity_id=entity,
                purpose_code="customer_support",
                reason="Customer requested account support.",
                step_up_authenticated_at=datetime.now(UTC),
            ),
        )
        masked = await service.apply_masking(
            session,
            actor,
            MaskRequest(
                policy_code="ADMIN-FIELD-USER-EMAIL",
                value="private@example.com",
                purpose_code="customer_support",
                permission_codes=["admin.entities.sensitive.read"],
            ),
        )
        revealed = await service.apply_masking(
            session,
            actor,
            MaskRequest(
                policy_code="ADMIN-FIELD-USER-EMAIL",
                value="private@example.com",
                purpose_code="customer_support",
                permission_codes=["admin.entities.sensitive.read"],
                reveal_grant_id=grant["id"],
            ),
        )
        assert masked["value"] == "p***@example.com" and revealed["value"] == "private@example.com"


@pytest.mark.asyncio
async def test_entity_view_authorizes_each_section_and_remains_partial() -> None:
    async with session_factory() as session:
        result = await service.entity_view(session, "user", uuid4(), {"users.read"})
        assert result["partial"] is True
        assert {section["status"] for section in result["sections"]} == {"available", "masked"}


@pytest.mark.asyncio
async def test_exception_projection_is_deduplicated() -> None:
    async with session_factory() as session:
        first = await service.sync_exception_work_items(session)
        second = await service.sync_exception_work_items(session)
        count = await session.scalar(
            text("SELECT count(*) FROM admin_work_items WHERE work_item_type='exception'")
        )
        assert first["projected"] == second["projected"] == count


@pytest.mark.asyncio
async def test_domain_certification_remains_not_certified_without_complete_production_evidence() -> (
    None
):
    actor = await _user("certification")
    async with session_factory() as session:
        record = await service.evaluate_certification(
            session,
            actor,
            CertificationEvaluate(
                business_domain="commerce",
                release_version="26.0.0",
                environment="local",
                verified_capability_codes=[],
            ),
        )
        assert record["status"] == "not_certified" and record["unresolved_critical_gaps"] > 0
