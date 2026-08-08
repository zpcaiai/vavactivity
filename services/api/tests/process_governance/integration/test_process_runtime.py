# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.process_governance import service
from vav.modules.process_governance.schemas import (
    CancellationCreate,
    CertificationEvaluate,
    CompensationRequest,
    EventReceive,
    InterventionResolve,
    ProcessStart,
    StepBegin,
    StepComplete,
)


async def _user(label: str) -> UUID:
    async with session_factory() as session:
        email = f"process-{label}-{uuid4().hex}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("ProcessUser!2026"),
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
async def test_process_start_and_step_receipts_are_durable_and_idempotent() -> None:
    actor = await _user("saga")
    async with session_factory() as session:
        payload = ProcessStart(
            process_code="membership-purchase",
            business_key=f"order:{uuid4()}",
            source_entity_type="order",
            source_entity_id=uuid4(),
            context={"order_id": str(uuid4())},
        )
        instance = await service.start_process(session, actor, payload)
        replay = await service.start_process(session, actor, payload)
        assert replay["id"] == instance["id"]
        assert "context_encrypted" not in instance
        step = await service.begin_step(
            session,
            actor,
            instance["id"],
            StepBegin(
                step_code="create-order",
                idempotency_key=f"step:{uuid4()}",
                input={"order_version": 1},
            ),
        )
        duplicate = await service.begin_step(
            session,
            actor,
            instance["id"],
            StepBegin(
                step_code="create-order",
                idempotency_key=step["idempotency_key"],
                input={"order_version": 1},
            ),
        )
        assert duplicate["id"] == step["id"]
        completed = await service.complete_step(
            session,
            actor,
            instance["id"],
            StepComplete(
                idempotency_key=step["idempotency_key"],
                receipt={"domain_state_version": 1, "command": "commerce.create_order"},
            ),
        )
        assert completed["instance"]["current_step_code"] == "await-payment"


@pytest.mark.asyncio
async def test_registered_state_machines_pass_runtime_graph_verification() -> None:
    actor = await _user("machine-verifier")
    async with session_factory() as session:
        result = await service.verify_machines(session, actor)
        assert result["status"] == "pass"
        assert len(result["results"]) == 6
        assert all(item["findings"] == [] for item in result["results"])


@pytest.mark.asyncio
async def test_idempotency_key_reuse_with_different_input_is_rejected() -> None:
    actor = await _user("idempotency")
    async with session_factory() as session:
        instance = await service.start_process(
            session,
            actor,
            ProcessStart(
                process_code="authentication-session",
                business_key=f"auth:{uuid4()}",
                source_entity_type="session",
                context={},
            ),
        )
        key = f"step:{uuid4()}"
        await service.begin_step(
            session,
            actor,
            instance["id"],
            StepBegin(
                step_code="validate-credentials", idempotency_key=key, input={"attempt": "one"}
            ),
        )
        with pytest.raises(VavError, match="different input"):
            await service.begin_step(
                session,
                actor,
                instance["id"],
                StepBegin(
                    step_code="validate-credentials", idempotency_key=key, input={"attempt": "two"}
                ),
            )


@pytest.mark.asyncio
async def test_registered_compensation_is_idempotent_and_preserves_receipt() -> None:
    actor = await _user("compensation")
    async with session_factory() as session:
        instance = await service.start_process(
            session,
            actor,
            ProcessStart(
                process_code="activity-registration",
                business_key=f"activity:{uuid4()}",
                source_entity_type="registration",
                context={},
            ),
        )
        key = f"step:{uuid4()}"
        step = await service.begin_step(
            session,
            actor,
            instance["id"],
            StepBegin(step_code="hold-capacity", idempotency_key=key, input={"capacity": 1}),
        )
        await service.complete_step(
            session,
            actor,
            instance["id"],
            StepComplete(idempotency_key=key, receipt={"reservation_id": str(uuid4())}),
        )
        request = CompensationRequest(
            step_execution_id=step["id"],
            compensation_code="release-activity-capacity",
            idempotency_key=f"compensation:{uuid4()}",
        )
        first = await service.request_compensation(session, actor, instance["id"], request)
        replay = await service.request_compensation(session, actor, instance["id"], request)
        assert first["id"] == replay["id"]
        assert first["status"] == "approved"


@pytest.mark.asyncio
async def test_event_inbox_deduplicates_and_buffers_gaps() -> None:
    actor = await _user("events")
    aggregate = uuid4()
    async with session_factory() as session:
        instance = await service.start_process(
            session,
            actor,
            ProcessStart(
                process_code="notification-delivery",
                business_key=f"notification:{uuid4()}",
                source_entity_type="notification",
                context={},
            ),
        )
        event_id = uuid4()
        payload = EventReceive(
            consumer_code="process-runtime",
            event_id=event_id,
            event_code="notification.receipt.v1",
            aggregate_type="notification",
            aggregate_id=aggregate,
            aggregate_version=1,
            payload_hash="a" * 64,
        )
        first = await service.receive_event(session, instance["id"], payload)
        duplicate = await service.receive_event(session, instance["id"], payload)
        future = await service.receive_event(
            session,
            instance["id"],
            payload.model_copy(
                update={"event_id": uuid4(), "aggregate_version": 3, "payload_hash": "b" * 64}
            ),
        )
        assert first["disposition"] == "accepted"
        assert duplicate["duplicate"] is True
        assert future["disposition"] == "buffered_future"


@pytest.mark.asyncio
async def test_cancellation_uses_optimistic_version_and_is_idempotent() -> None:
    actor = await _user("cancel")
    async with session_factory() as session:
        instance = await service.start_process(
            session,
            actor,
            ProcessStart(
                process_code="course-enrollment",
                business_key=f"course:{uuid4()}",
                source_entity_type="enrollment",
                context={},
            ),
        )
        request = CancellationCreate(
            cancellation_key=f"cancel:{uuid4()}",
            request_type="user",
            reason_code="user_changed_mind",
            expected_lock_version=0,
        )
        result = await service.cancel(session, actor, instance["id"], request)
        replay = await service.cancel(session, actor, instance["id"], request)
        assert result["id"] == replay["id"]
        detail = await service.instance_detail(session, instance["id"])
        assert detail["instance"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_stuck_scan_creates_controlled_intervention_and_rejects_direct_state_edit() -> None:
    actor = await _user("stuck")
    async with session_factory() as session:
        instance = await service.start_process(
            session,
            actor,
            ProcessStart(
                process_code="ai-human-referral",
                business_key=f"referral:{uuid4()}",
                source_entity_type="referral",
                context={},
            ),
        )
        await session.execute(
            text(
                "UPDATE process_instances SET deadline_at=now()-interval '1 minute',last_progress_at=now()-interval '1 day' WHERE id=:id"
            ),
            {"id": instance["id"]},
        )
        await session.commit()
        result = await service.scan_stuck(session, actor)
        # The scanner is intentionally global and may also remediate backlog from
        # earlier workers or test runs.  Assert the target instance's invariant
        # instead of assuming this database contains no other stuck processes.
        assert result["created"] >= 1
        task_count = await session.scalar(
            text("SELECT count(*) FROM process_intervention_tasks WHERE process_instance_id=:id"),
            {"id": instance["id"]},
        )
        assert task_count == 1
        await service.scan_stuck(session, actor)
        replay_task_count = await session.scalar(
            text("SELECT count(*) FROM process_intervention_tasks WHERE process_instance_id=:id"),
            {"id": instance["id"]},
        )
        assert replay_task_count == 1
        task_id = await session.scalar(
            text("SELECT id FROM process_intervention_tasks WHERE process_instance_id=:id"),
            {"id": instance["id"]},
        )
        with pytest.raises(VavError, match="unsafe"):
            await service.resolve_intervention(
                session,
                actor,
                task_id,
                InterventionResolve(
                    resolution_command="direct_sql.set_state", receipt={"claimed": "success"}
                ),
            )
        resolved = await service.resolve_intervention(
            session,
            actor,
            task_id,
            InterventionResolve(
                resolution_command="process.rebuild_projection",
                receipt={"domain_receipt_verified": True},
            ),
        )
        assert resolved["status"] == "resolved"


@pytest.mark.asyncio
async def test_business_line_certification_requires_independent_production_evidence() -> None:
    evaluator = await _user("certification-evaluator")
    reviewer = await _user("certification-reviewer")
    paths = {
        path: "pass"
        for path in (
            "normal",
            "failure",
            "timeout",
            "cancellation",
            "compensation",
            "concurrency",
            "manual_recovery",
        )
    }
    async with session_factory() as session:
        record = await service.evaluate_certification(
            session,
            evaluator,
            CertificationEvaluate(
                business_domain="course",
                git_commit="a8cb785",
                environment="local",
                path_results=paths,
                evidence_checksum_sha256="c" * 64,
            ),
        )
        assert record["technical_status"] == "pass"
        assert record["production_status"] == "not_certified"
        with pytest.raises(VavError, match="own result"):
            await service.decide_certification(
                session, evaluator, record["id"], "certified", "Self approval is forbidden."
            )
        with pytest.raises(VavError, match="production-bound"):
            await service.decide_certification(
                session,
                reviewer,
                record["id"],
                "certified",
                "Local technical evidence is insufficient for production.",
            )
