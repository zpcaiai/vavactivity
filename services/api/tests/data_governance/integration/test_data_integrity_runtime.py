# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from vav_worker.tasks import _dispatch_data_outbox

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.data_governance import service
from vav.modules.data_governance.schemas import (
    BackfillAction,
    BackfillStart,
    ErasurePlanCreate,
    ErasureTaskComplete,
    EventEnvelope,
    ExternalIdentifierCreate,
    InboxApply,
    IntegrityEvaluate,
    ProjectionRebuild,
    QualityEvaluationCreate,
    ReconciliationRun,
    RepairRequest,
)
from vav.modules.identity.security import PasswordHasher


async def _user(label: str) -> UUID:
    async with session_factory() as session:
        email = f"data-{label}-{uuid4().hex}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("DataUser!2026"),
            status="active",
            email_verified_at=datetime.now(UTC),
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


def _event(aggregate_id: UUID, version: int, event_id: UUID | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id or uuid4(),
        event_type="commerce.payment.changed.v1",
        event_version=1,
        aggregate_type="payment",
        aggregate_id=aggregate_id,
        aggregate_version=version,
        sequence_number=version,
        producer_module="commerce",
        payload={"payment_id": str(aggregate_id), "status": "confirmed"},
    )


@pytest.mark.asyncio
async def test_external_identifier_is_encrypted_hashed_and_never_returned() -> None:
    actor = await _user("external-identifier")
    plaintext = f"provider-{uuid4()}@private.example"
    async with session_factory() as session:
        result = await service.register_external_identifier(
            session,
            actor,
            ExternalIdentifierCreate(
                entity_type="user",
                canonical_entity_id=actor,
                provider_code="test-provider",
                external_identifier=plaintext,
            ),
        )
        assert "external_identifier_encrypted" not in result
        stored = (
            (
                await session.execute(
                    text(
                        "SELECT external_identifier_hash,external_identifier_encrypted FROM canonical_external_identifiers WHERE id=:id"
                    ),
                    {"id": result["id"]},
                )
            )
            .mappings()
            .one()
        )
        assert plaintext not in stored["external_identifier_hash"]
        assert plaintext not in stored["external_identifier_encrypted"]


@pytest.mark.asyncio
async def test_quality_evaluation_is_fail_closed_and_minimizes_samples() -> None:
    async with session_factory() as session:
        passing = await service.evaluate_quality(
            session,
            QualityEvaluationCreate(
                rule_code="user-id-required",
                evaluated_records=10,
                failed_records=0,
                sample={"rows": 10, "email": "private@example.com"},
            ),
        )
        failing = await service.evaluate_quality(
            session,
            QualityEvaluationCreate(
                rule_code="user-id-required",
                evaluated_records=10,
                failed_records=1,
                sample={"rows": 1, "phone": "+886900000000"},
            ),
        )
        assert passing["status"] == "pass"
        assert failing["status"] == "fail"
        assert failing["minimized_sample"] == {"rows": 1}


@pytest.mark.asyncio
async def test_repair_request_uses_registered_command_and_minimized_input() -> None:
    actor = await _user("repair")
    async with session_factory() as session:
        result = await service.request_repair(
            session,
            actor,
            RepairRequest(
                repair_code="repair.payment-order",
                idempotency_key=f"repair:{uuid4()}",
                input_mapping={
                    "order_id": str(uuid4()),
                    "email": "private@example.com",
                },
            ),
        )
        assert result["status"] == "requested"
        assert "email" not in result["input_mapping"]
        assert result["input_mapping"]["order_id"]


@pytest.mark.asyncio
async def test_transactional_outbox_rolls_back_with_caller_transaction_and_deduplicates() -> None:
    aggregate, event_id = uuid4(), uuid4()
    envelope = _event(aggregate, 1, event_id)
    async with session_factory() as session:
        await service.enqueue_outbox(session, envelope)
        await session.rollback()
    async with session_factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM data_event_outbox WHERE event_id=:id"), {"id": event_id}
            )
            == 0
        )
        first = await service.enqueue_outbox(session, envelope)
        await session.commit()
        replay = await service.enqueue_outbox(session, envelope)
        await session.commit()
        assert first["id"] == replay["id"]


@pytest.mark.asyncio
async def test_worker_dispatches_governed_outbox_to_delivery_queue_once() -> None:
    aggregate, event_id = uuid4(), uuid4()
    async with session_factory() as session:
        await service.enqueue_outbox(session, _event(aggregate, 1, event_id))
        await session.commit()
    first = await _dispatch_data_outbox()
    second = await _dispatch_data_outbox()
    async with session_factory() as session:
        delivered = await session.scalar(
            text("SELECT count(*) FROM outbox_events WHERE payload->>'event_id'=:event_id"),
            {"event_id": str(event_id)},
        )
        status = await session.scalar(
            text("SELECT status FROM data_event_outbox WHERE event_id=:event_id"),
            {"event_id": event_id},
        )
    assert first["published"] >= 1
    assert second["published"] == 0
    assert delivered == 1 and status == "published"


@pytest.mark.asyncio
async def test_inbox_deduplicates_and_persists_event_gap_without_sensitive_receipt() -> None:
    aggregate = uuid4()
    async with session_factory() as session:
        first_payload = InboxApply(
            consumer_code="recommendation-projection",
            envelope=_event(aggregate, 1),
            effect_receipt={"email": "private@example.com", "rows": 1},
        )
        first = await service.apply_inbox(session, first_payload)
        duplicate = await service.apply_inbox(session, first_payload)
        future = await service.apply_inbox(
            session,
            InboxApply(
                consumer_code="recommendation-projection",
                envelope=_event(aggregate, 3),
                effect_receipt={},
            ),
        )
        assert first["disposition"] == "accepted" and first["effect_receipt"] == {"rows": 1}
        assert duplicate["duplicate"] is True
        assert future["disposition"] == "buffered_future"
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM data_event_gaps WHERE aggregate_id=:id AND status='open'"
                ),
                {"id": aggregate},
            )
            == 1
        )


@pytest.mark.asyncio
async def test_reconciliation_persists_fingerprints_and_registered_repair_only() -> None:
    actor = await _user("reconciliation")
    async with session_factory() as session:
        result = await service.run_reconciliation(
            session,
            actor,
            ReconciliationRun(
                reconciliation_code="payment-order",
                comparisons=[
                    {
                        "key": "order-1",
                        "source": {"status": "confirmed"},
                        "target": {"status": "pending"},
                    },
                    {
                        "key": "order-2",
                        "source": {"status": "confirmed"},
                        "target": {"status": "confirmed"},
                    },
                ],
            ),
        )
        assert result["difference_count"] == 1
        difference = (
            (
                await session.execute(
                    text("SELECT * FROM data_reconciliation_differences WHERE run_id=:run"),
                    {"run": result["run_id"]},
                )
            )
            .mappings()
            .one()
        )
        assert difference["source_fingerprint"] != difference["target_fingerprint"]
        assert result["repair_command_code"] == "commerce.reconcile_confirmed_payment"


@pytest.mark.asyncio
async def test_backfill_dry_run_pause_resume_and_independent_production_approval() -> None:
    requester, reviewer = await _user("backfill-requester"), await _user("backfill-reviewer")
    async with session_factory() as session:
        dry = await service.start_backfill(
            session,
            requester,
            BackfillStart(
                backfill_code="rebuild-user-home-projection",
                environment="local",
                dry_run=True,
                idempotency_key=f"dry:{uuid4()}",
                stable_candidate_hash="a" * 64,
            ),
        )
        running = await service.act_backfill(
            session, requester, dry["id"], BackfillAction(action="start")
        )
        paused = await service.act_backfill(
            session,
            requester,
            dry["id"],
            BackfillAction(
                action="pause", cursor_value="user:100", processed_delta=100, success_delta=100
            ),
        )
        resumed = await service.act_backfill(
            session, requester, dry["id"], BackfillAction(action="resume")
        )
        assert (
            running["status"] == "running"
            and paused["status"] == "paused"
            and resumed["cursor_value"] == "user:100"
        )
        production = await service.start_backfill(
            session,
            requester,
            BackfillStart(
                backfill_code="rebuild-search-source-versions",
                environment="production",
                dry_run=False,
                idempotency_key=f"prod:{uuid4()}",
                stable_candidate_hash="b" * 64,
            ),
        )
        with pytest.raises(VavError, match="Requester"):
            await service.act_backfill(
                session, requester, production["id"], BackfillAction(action="approve")
            )
        approved = await service.act_backfill(
            session, reviewer, production["id"], BackfillAction(action="approve")
        )
        assert approved["status"] == "approved"
        with pytest.raises(VavError, match="Processed delta"):
            await service.act_backfill(
                session,
                reviewer,
                production["id"],
                BackfillAction(action="start", processed_delta=2, success_delta=1),
            )


@pytest.mark.asyncio
async def test_projection_rebuild_rejects_source_of_truth() -> None:
    actor = await _user("projection")
    async with session_factory() as session:
        with pytest.raises(VavError, match="Only rebuildable projections"):
            await service.request_projection_rebuild(
                session,
                actor,
                ProjectionRebuild(
                    asset_code="commerce.payments", scope="full", source_checkpoint={"version": 1}
                ),
            )
        result = await service.request_projection_rebuild(
            session,
            actor,
            ProjectionRebuild(
                asset_code="experience.search_index",
                scope="partition",
                scope_key="zh-CN",
                source_checkpoint={"version": 25},
                shadow_build=True,
            ),
        )
        assert result["status"] == "created" and result["shadow_build"] is True


@pytest.mark.asyncio
async def test_erasure_plan_covers_every_sensitive_asset_and_certifies_zero_residuals() -> None:
    actor = await _user("erasure")
    async with session_factory() as session:
        plan = await service.create_erasure_plan(
            session,
            actor,
            ErasurePlanCreate(
                privacy_request_id=uuid4(), subject_user_id=actor, lineage_release_version="25.0.0"
            ),
        )
        tasks = list(
            (
                await session.execute(
                    text("SELECT id,action FROM data_erasure_tasks WHERE plan_id=:plan"),
                    {"plan": plan["id"]},
                )
            ).mappings()
        )
        assert {task["action"] for task in tasks}.issuperset(
            {"invalidate_cache", "remove_search", "remove_vector", "remove_export"}
        )
        for task in tasks:
            await service.complete_erasure_task(
                session,
                actor,
                task["id"],
                ErasureTaskComplete(
                    status="completed", execution_receipt={"verified": True}, residual_count=0
                ),
            )
        certificate = await service.issue_erasure_certificate(session, actor, plan["id"])
        assert certificate["result_summary"]["deleted_or_anonymized"] == len(tasks)


@pytest.mark.asyncio
async def test_integrity_certification_fails_closed_on_open_gaps_and_local_environment() -> None:
    evaluator = await _user("integrity-evaluator")
    evidence = {
        key: "pass"
        for key in (
            "contracts",
            "lineage",
            "events",
            "quality",
            "reconciliation",
            "backfill",
            "erasure",
        )
    }
    async with session_factory() as session:
        record = await service.evaluate_integrity(
            session,
            evaluator,
            IntegrityEvaluate(
                business_domain="commerce",
                git_commit="8665cd1",
                environment="local",
                evidence_results=evidence,
                evidence_checksum_sha256="d" * 64,
            ),
        )
        assert record["production_status"] == "not_certified"
        assert record["technical_status"] == "fail"
