from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.trust_safety import service
from vav.modules.trust_safety.schemas import (
    AppealCreateRequest,
    AppealDecisionRequest,
    BehaviorAggregateRequest,
    CaseAssignmentRequest,
    CaseDecisionRequest,
    EvidenceAccessRequest,
    FraudSignalRequest,
    RedTeamRunCompleteRequest,
    RedTeamRunCreateRequest,
    ReportCreateRequest,
    RestrictionCreateRequest,
    UserEvidenceUploadRequest,
)


async def _member() -> UUID:
    async with session_factory() as session:
        email = f"safety-case-{uuid4()}@example.com"
        user = User(
            email=email,
            display_email=email,
            password_hash=PasswordHasher().hash("SafetyFixture!2026"),
            status="active",
            email_verified_at=datetime.now(UTC),
            preferred_locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _case_fixture() -> tuple[UUID, UUID, UUID]:
    reporter, subject = await _member(), await _member()
    async with session_factory() as session:
        report = await service.create_report(
            session,
            reporter=reporter,
            payload=ReportCreateRequest(
                target_type="user",
                reported_user_id=subject,
                category="harassment",
                description="Repeated contact after a clear decline.",
                idempotency_key=f"case-{uuid4()}",
            ),
        )
        case_id = await session.scalar(
            text("SELECT safety_case_id FROM safety_case_reports WHERE report_id=:report"),
            {"report": UUID(report["id"])},
        )
        assert case_id is not None
        return reporter, subject, case_id


@pytest.mark.asyncio
async def test_evidence_is_encrypted_integrity_bound_and_purpose_audited() -> None:
    reporter, _, case_id = await _case_fixture()
    investigator = await _member()
    async with session_factory() as session:
        report_id = await session.scalar(
            text("SELECT report_id FROM safety_case_reports WHERE safety_case_id=:case"),
            {"case": case_id},
        )
        uploaded = await service.upload_report_evidence(
            session,
            reporter=reporter,
            report_id=report_id,
            payload=UserEvidenceUploadRequest(
                evidence_type="text",
                content="Evidence supplied voluntarily by the reporter.",
            ),
        )
        raw = await session.scalar(
            text(
                "SELECT evidence_snapshot_encrypted::text FROM safety_evidence_items WHERE id=:id"
            ),
            {"id": UUID(uploaded["id"])},
        )
        assert "Evidence supplied" not in raw
        viewed = await service.access_evidence(
            session,
            evidence_id=UUID(uploaded["id"]),
            actor=investigator,
            permission_code="safety.evidence.highly_restricted.read",
            payload=EvidenceAccessRequest(purpose_code="case_investigation"),
        )
        assert viewed["snapshot"]["submitted_by_reporter"] is True
        assert (
            await session.scalar(
                text("SELECT count(*) FROM safety_evidence_access_log WHERE evidence_item_id=:id"),
                {"id": UUID(uploaded["id"])},
            )
            == 1
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM privacy_audit_events WHERE subject_id=:id"),
                {"id": UUID(uploaded["id"])},
            )
            == 1
        )


@pytest.mark.asyncio
async def test_case_conflict_versioning_and_high_impact_four_eyes() -> None:
    reporter, subject, case_id = await _case_fixture()
    investigator, approver = await _member(), await _member()
    async with session_factory() as session:
        with pytest.raises(VavError, match="conflicted investigator"):
            await service.assign_case(
                session,
                case_id=case_id,
                actor=investigator,
                payload=CaseAssignmentRequest(
                    assigned_to=reporter,
                    assigned_team="safety",
                    expected_version=1,
                ),
            )
        assigned = await service.assign_case(
            session,
            case_id=case_id,
            actor=investigator,
            payload=CaseAssignmentRequest(
                assigned_to=investigator,
                assigned_team="safety",
                expected_version=1,
            ),
        )
        assert assigned["status"] == "assigned"
        with pytest.raises(VavError, match="conflicted investigator"):
            await service.create_case_decision(
                session,
                case_id=case_id,
                actor=reporter,
                payload=CaseDecisionRequest(
                    decision_type="no_action",
                    reason_codes=["insufficient_evidence"],
                    internal_rationale="Reporter cannot decide their own case.",
                ),
            )
        decision = await service.create_case_decision(
            session,
            case_id=case_id,
            actor=investigator,
            payload=CaseDecisionRequest(
                decision_type="permanent_disable",
                reason_codes=["confirmed_high_impact_policy"],
                internal_rationale="Human-reviewed high-impact test fixture.",
                restriction_manifest=[
                    {
                        "restriction_type": "account_permanently_disabled",
                        "scope_definition": {"authentication": False},
                        "starts_at": datetime.now(UTC).isoformat(),
                        "appeal_allowed": True,
                    }
                ],
            ),
        )
        assert decision["status"] == "pending_approval"
        assert (
            await session.scalar(
                text("SELECT count(*) FROM account_restrictions WHERE user_id=:user"),
                {"user": subject},
            )
            == 0
        )
        with pytest.raises(VavError, match="different administrator"):
            await service.approve_case_decision(
                session,
                case_id=case_id,
                decision_id=UUID(decision["id"]),
                approver=investigator,
            )
        approved = await service.approve_case_decision(
            session,
            case_id=case_id,
            decision_id=UUID(decision["id"]),
            approver=approver,
        )
        assert approved["status"] == "effective"
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM account_restrictions WHERE user_id=:user "
                    "AND status='active'"
                ),
                {"user": subject},
            )
            == 1
        )


@pytest.mark.asyncio
async def test_signals_are_governed_and_red_team_failures_block_release() -> None:
    subject, operator, independent = await _member(), await _member(), await _member()
    now = datetime.now(UTC)
    async with session_factory() as session:
        aggregate = await service.upsert_behavior_aggregate(
            session,
            actor=operator,
            payload=BehaviorAggregateRequest(
                user_id=subject,
                metric_code="post_decline_contact",
                window_type="hour",
                window_starts_at=now,
                window_ends_at=now + timedelta(hours=1),
                event_count=3,
                distinct_target_count=1,
                aggregation_version="v1",
            ),
        )
        assert aggregate["event_count"] == 3
        signal = await service.create_fraud_signal(
            session,
            actor=operator,
            payload=FraudSignalRequest(
                subject_user_id=subject,
                signal_code="money_request",
                signal_source="manual_review",
                severity="high",
                safe_signal_context={"detector": "money-request-v1"},
            ),
        )
        assert signal["status"] == "active"
        with pytest.raises(VavError, match="Protected or private-domain"):
            await service.create_fraud_signal(
                session,
                actor=operator,
                payload=FraudSignalRequest(
                    subject_user_id=subject,
                    signal_code="money_request",
                    signal_source="manual_review",
                    severity="high",
                    safe_signal_context={"religion": "forbidden"},
                ),
            )
        run = await service.create_red_team_run(
            session,
            actor=operator,
            payload=RedTeamRunCreateRequest(
                policy_version="1.0.0",
                fixture_manifest={"sha256": "fixture"},
            ),
        )
        completed = await service.complete_red_team_run(
            session,
            run_id=UUID(run["id"]),
            actor=operator,
            payload=RedTeamRunCompleteRequest(
                result_manifest={"failed": ["direct_profile_url"]},
                block_bypass_count=1,
                contact_leakage_count=0,
            ),
        )
        assert completed["status"] == "release_blocked"
        with pytest.raises(VavError, match="cannot be approved"):
            await service.approve_red_team_run(
                session,
                run_id=UUID(run["id"]),
                approver=independent,
            )


@pytest.mark.asyncio
async def test_appeal_is_owned_independent_and_can_safely_modify_restriction() -> None:
    appellant, imposer, reviewer, unrelated = (
        await _member(),
        await _member(),
        await _member(),
        await _member(),
    )
    now = datetime.now(UTC)
    async with session_factory() as session:
        restriction = await service.create_restriction(
            session,
            actor=imposer,
            payload=RestrictionCreateRequest(
                user_id=appellant,
                restriction_type="invitation_disabled",
                scope_definition={"invitations": False, "likes": True},
                source_type="manual",
                reason_code="manual_review_complete",
                starts_at=now,
                ends_at=now + timedelta(days=14),
            ),
        )
        appeal = await service.create_appeal(
            session,
            appellant=appellant,
            payload=AppealCreateRequest(
                restriction_id=UUID(restriction["id"]),
                reason="Please independently review this scoped restriction.",
            ),
        )
        with pytest.raises(VavError, match="original decision maker"):
            await service.decide_appeal(
                session,
                appeal_id=UUID(appeal["id"]),
                reviewer=imposer,
                payload=AppealDecisionRequest(
                    outcome="upheld",
                    outcome_message="The scoped restriction remains.",
                    internal_review="Imposer cannot independently review this appeal.",
                ),
            )
        result = await service.decide_appeal(
            session,
            appeal_id=UUID(appeal["id"]),
            reviewer=reviewer,
            payload=AppealDecisionRequest(
                outcome="modified",
                outcome_message="The restriction duration and scope were reduced.",
                internal_review="Independent review supports a narrower restriction.",
                modified_scope_definition={"invitations": False, "likes": True},
                modified_ends_at=now + timedelta(days=2),
            ),
        )
        assert result["outcome"] == "modified"
        row = (
            (
                await session.execute(
                    text("SELECT status,ends_at,version FROM account_restrictions WHERE id=:id"),
                    {"id": UUID(restriction["id"])},
                )
            )
            .mappings()
            .one()
        )
        assert row["status"] == "active"
        assert row["ends_at"] < now + timedelta(days=3)
        with pytest.raises(VavError, match="not eligible"):
            await service.create_appeal(
                session,
                appellant=unrelated,
                payload=AppealCreateRequest(
                    restriction_id=UUID(restriction["id"]),
                    reason="I cannot appeal a restriction that belongs to another member.",
                ),
            )
