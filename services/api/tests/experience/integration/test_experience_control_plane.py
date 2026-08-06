# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.experience import service
from vav.modules.experience.schemas import (
    ClosureEvaluation,
    DeepLinkCreate,
    HandoffCreate,
    JourneyStart,
    SupportRequestCreate,
)
from vav.modules.identity.security import PasswordHasher


async def _user(label: str, verified: bool = True) -> UUID:
    async with session_factory() as session:
        email = f"experience-{label}-{uuid4().hex}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("ExperienceUser!2026"),
            status="active",
            email_verified_at=datetime.now(UTC) if verified else None,
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest.mark.asyncio
async def test_task_home_and_journey_resume_use_authoritative_projections() -> None:
    user_id = await _user("journey", verified=False)
    async with session_factory() as session:
        tasks = await service.list_tasks(session, user_id)
        assert [item["task_code"] for item in tasks] == ["identity.verify-email"]
        home = await service.user_home(session, user_id)
        assert len(home["critical_tasks"]) == 1
        payload = JourneyStart(
            journey_code="onboarding",
            source_module="identity",
            source_entity_type="user",
            source_entity_id=user_id,
            authoritative_state_version="user:1",
        )
        first = await service.start_journey(session, user_id, payload)
        resumed = await service.start_journey(session, user_id, payload)
        assert first["id"] == resumed["id"]
        assert first["current_step_code"] == "register"


@pytest.mark.asyncio
async def test_handoff_encrypts_context_rechecks_access_and_never_returns_ciphertext() -> None:
    user_id = await _user("handoff")
    source_id = uuid4()
    async with session_factory() as session:
        handoff = await service.create_handoff(
            session,
            user_id,
            HandoffCreate(
                handoff_code="recommendation-to-interaction",
                source_entity_type="recommendation_item",
                source_entity_id=source_id,
                user_intent="respond.to.recommendation",
                context={"recommendation_item_id": str(source_id)},
                source_route_code="user.recommendations",
            ),
        )
        assert "context_encrypted" not in handoff
        accepted = await service.accept_handoff(session, user_id, handoff["id"], set())
        assert accepted["state"] == "accepted"
        assert accepted["route_parameters"] == {"recommendation_item_id": str(source_id)}


@pytest.mark.asyncio
async def test_deep_link_is_user_bound_single_use_and_has_safe_fallback() -> None:
    creator = await _user("link-creator")
    target = await _user("link-target")
    async with session_factory() as session:
        link = await service.create_deep_link(
            session,
            creator,
            DeepLinkCreate(
                purpose="task.status",
                user_id=target,
                entity_type="user",
                entity_id=target,
                target_route_code="user.tasks",
                fallback_route_code="user.experience-home",
                route_parameters={"user_id": target},
            ),
        )
        resolved = await service.resolve_deep_link(session, target, link["token"], set())
        assert resolved["resolved"] is True
        replay = await service.resolve_deep_link(session, target, link["token"], set())
        assert replay == {
            "resolved": False,
            "fallback": {"route_code": "user.experience-home", "reason_code": "link_unavailable"},
        }


@pytest.mark.asyncio
async def test_support_routing_encrypts_description_and_search_is_owner_filtered() -> None:
    owner = await _user("search-owner")
    other = await _user("search-other")
    async with session_factory() as session:
        support = await service.create_support_request(
            session,
            owner,
            SupportRequestCreate(
                source_route_code="user.safety",
                category="safety",
                description="I need help finding the current safety-case status.",
            ),
        )
        assert support["assignment_queue"] == "trust-safety"
        stored = await session.scalar(
            text("SELECT description_encrypted FROM experience_support_requests WHERE id=:id"),
            {"id": support["id"]},
        )
        assert stored and "safety-case" not in stored
        await session.execute(
            text(
                "INSERT INTO experience_search_documents (document_code,source_module,source_entity_type,source_entity_id,title,summary,locale,visibility,owner_user_id,route_code,source_version) VALUES (:code,'commerce','personal_order',:entity,'Order Alpha','Personal order status','en','personal',:owner,'user.account','1')"
            ),
            {"code": f"personal:{uuid4()}", "entity": uuid4(), "owner": owner},
        )
        await session.commit()
        assert (
            len(
                await service.search(session, query="Order Alpha", user_id=owner, permissions=set())
            )
            == 1
        )
        assert (
            await service.search(session, query="Order Alpha", user_id=other, permissions=set())
            == []
        )


@pytest.mark.asyncio
async def test_runtime_dead_end_and_closure_gates_remain_fail_closed_without_review() -> None:
    evaluator = await _user("closure-evaluator")
    reviewer = await _user("closure-reviewer")
    async with session_factory() as session:
        scan = await service.scan_dead_ends(session)
        assert scan["passed"] is True
        assert scan["critical_count"] == 0
        records = await service.evaluate_closure(
            session,
            evaluator,
            ClosureEvaluation(
                git_commit="a7f0638",
                environment="test",
                capability_codes=["user.tasks"],
                evidence_reference="artifact://batch-23/runtime-gate.json",
            ),
        )
        assert records[0]["technical_status"] == "pass"
        assert records[0]["production_status"] == "not_certified"
        with pytest.raises(VavError, match="independent"):
            await service.certify_closure(
                session,
                evaluator,
                records[0]["id"],
                "certify",
                "Self approval is forbidden by policy.",
                {},
            )
        with pytest.raises(VavError, match="incomplete"):
            await service.certify_closure(
                session,
                reviewer,
                records[0]["id"],
                "certify",
                "Independent review requires complete evidence.",
                {},
            )
        dashboard = await service.admin_dashboard(session)
        assert dashboard["release_allowed"] is False
