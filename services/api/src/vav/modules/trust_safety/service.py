"""Transactional Trust & Safety application services."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.trust_safety.crypto import decrypt_sensitive, encrypt_sensitive
from vav.modules.trust_safety.domain import (
    CASE_TRANSITIONS,
    REPORT_TRANSITIONS,
    TrustSafetyDecision,
    canonical_pair,
    classify_text,
    evaluate_condition,
    requires_second_approval,
    validate_transition,
)
from vav.modules.trust_safety.schemas import (
    AppealCreateRequest,
    AppealDecisionRequest,
    BehaviorAggregateRequest,
    CaseAssignmentRequest,
    CaseDecisionRequest,
    EvidenceAccessRequest,
    FraudSignalRequest,
    ModerationCreateRequest,
    ModerationDecisionRequest,
    RedTeamRunCompleteRequest,
    RedTeamRunCreateRequest,
    ReportCreateRequest,
    RestrictionCreateRequest,
    RuleCreateRequest,
    UserEvidenceUploadRequest,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _number(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12].upper()}"


async def _outbox(
    session: AsyncSession,
    topic: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,:aggregate_type,:aggregate_id,CAST(:payload AS jsonb))"
        ),
        {
            "topic": topic,
            "aggregate_type": aggregate_type,
            "aggregate_id": str(aggregate_id),
            "payload": _json(payload),
        },
    )


async def _audit(
    session: AsyncSession,
    *,
    actor_user_id: UUID | None,
    subject_user_id: UUID | None,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO safety_audit_events "
            "(actor_user_id,subject_user_id,event_type,aggregate_type,aggregate_id,safe_metadata) "
            "VALUES (:actor,:subject,:event,:aggregate_type,:aggregate_id,CAST(:metadata AS jsonb))"
        ),
        {
            "actor": actor_user_id,
            "subject": subject_user_id,
            "event": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "metadata": _json(metadata or {}),
        },
    )


def _safe_report(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "report_number": row["report_number"],
        "reported_user_id": str(row["reported_user_id"]) if row["reported_user_id"] else None,
        "target_type": row["target_type"],
        "target_reference_id": (
            str(row["target_reference_id"]) if row["target_reference_id"] else None
        ),
        "category": row["category"],
        "status": row["status"],
        "block_requested": row["block_requested"],
        "immediate_danger_claimed": row["immediate_danger_claimed"],
        "submitted_at": row["submitted_at"].isoformat(),
        "closed_at": row["closed_at"].isoformat() if row["closed_at"] else None,
        "version": row["version"],
    }


async def _pair_version(session: AsyncSession, first: UUID, second: UUID) -> int:
    low, high = canonical_pair(first, second)
    row = (
        await session.execute(
            text(
                "INSERT INTO safety_pair_versions (user_low_id,user_high_id,restriction_version) "
                "VALUES (:low,:high,1) ON CONFLICT (user_low_id,user_high_id) DO UPDATE SET "
                "restriction_version=safety_pair_versions.restriction_version+1,updated_at=now() "
                "RETURNING restriction_version"
            ),
            {"low": low, "high": high},
        )
    ).scalar_one()
    return int(row)


async def _propagate_block(
    session: AsyncSession, *, blocker: UUID, blocked: UUID, block_id: UUID
) -> int:
    """Apply the block synchronously to all existing cross-module grants."""

    low, high = canonical_pair(blocker, blocked)
    version = await _pair_version(session, blocker, blocked)
    await session.execute(
        text(
            "INSERT INTO recommendation_pair_exclusions "
            "(user_low_id,user_high_id,exclusion_type,source_module,reason_code) "
            "VALUES (:low,:high,'block','trust_safety','user_block') "
            "ON CONFLICT (user_low_id,user_high_id,exclusion_type) WHERE released_at IS NULL "
            "DO NOTHING"
        ),
        {"low": low, "high": high},
    )
    await session.execute(
        text(
            "UPDATE recommendation_candidate_pairs SET status='invalidated',invalidated_at=now(),"
            "invalidation_reason='user_block' WHERE user_low_id=:low AND user_high_id=:high "
            "AND status <> 'invalidated'"
        ),
        {"low": low, "high": high},
    )
    await session.execute(
        text(
            "UPDATE recommendation_items SET status='invalidated',invalidated_at=now(),"
            "invalidation_reason='user_block' WHERE ((viewer_user_id=:a AND recommended_user_id=:b) "
            "OR (viewer_user_id=:b AND recommended_user_id=:a)) AND status <> 'invalidated'"
        ),
        {"a": blocker, "b": blocked},
    )
    await session.execute(
        text(
            "UPDATE matchmaking_pairs SET status='restricted',restriction_version=:version,"
            "pair_version=pair_version+1,updated_at=now() WHERE user_low_id=:low AND user_high_id=:high"
        ),
        {"low": low, "high": high, "version": version},
    )
    await session.execute(
        text(
            "UPDATE matchmaking_likes SET status='invalidated',invalidated_at=now(),"
            "invalidation_reason_code='user_block' WHERE ((actor_user_id=:a AND target_user_id=:b) "
            "OR (actor_user_id=:b AND target_user_id=:a)) AND status IN ('active','matched')"
        ),
        {"a": blocker, "b": blocked},
    )
    await session.execute(
        text(
            "UPDATE matchmaking_mutual_matches SET status='safety_frozen',match_version=match_version+1,"
            "closure_reason_code='user_block',updated_at=now() WHERE user_low_id=:low AND user_high_id=:high "
            "AND status NOT IN ('closed','invalidated','safety_frozen')"
        ),
        {"low": low, "high": high},
    )
    await session.execute(
        text(
            "UPDATE matchmaking_introduction_invitations SET status='invalidated',invalidated_at=now(),"
            "internal_invalidation_reason='user_block',invitation_version=invitation_version+1,updated_at=now() "
            "WHERE ((sender_user_id=:a AND recipient_user_id=:b) OR "
            "(sender_user_id=:b AND recipient_user_id=:a)) AND status='pending'"
        ),
        {"a": blocker, "b": blocked},
    )
    await session.execute(
        text(
            "UPDATE matchmaking_contact_exchange_grants SET status='revoked',revoked_at=now(),"
            "revoke_reason='user_block' WHERE ((viewer_user_id=:a AND owner_user_id=:b) OR "
            "(viewer_user_id=:b AND owner_user_id=:a)) AND status='active'"
        ),
        {"a": blocker, "b": blocked},
    )
    await session.execute(
        text(
            "UPDATE matchmaking_contact_reveal_tokens SET status='invalidated',invalidated_at=now() "
            "WHERE status='issued' AND grant_id IN (SELECT id FROM matchmaking_contact_exchange_grants "
            "WHERE ((viewer_user_id=:a AND owner_user_id=:b) OR "
            "(viewer_user_id=:b AND owner_user_id=:a)))"
        ),
        {"a": blocker, "b": blocked},
    )
    await session.execute(
        text(
            "UPDATE relationship_journeys SET status='safety_frozen',paused_at=now(),version=version+1,"
            "updated_at=now() WHERE user_low_id=:low AND user_high_id=:high "
            "AND status IN ('pending_activation','active','paused')"
        ),
        {"low": low, "high": high},
    )
    await session.execute(
        text(
            "UPDATE relationship_reminder_plans SET status='cancelled',updated_at=now() "
            "WHERE status='active' AND journey_id IN (SELECT id FROM relationship_journeys "
            "WHERE user_low_id=:low AND user_high_id=:high)"
        ),
        {"low": low, "high": high},
    )
    await _outbox(
        session,
        "safety.block.created",
        "user_block",
        block_id,
        {
            "blocker_user_id": str(blocker),
            "blocked_user_id": str(blocked),
            "restriction_version": version,
            "suppress_nonessential_notifications": True,
        },
    )
    return version


async def _create_block(
    session: AsyncSession,
    *,
    blocker: UUID,
    blocked: UUID,
    source: str,
    source_report_id: UUID | None,
    reason_code: str | None,
    private_reason: str | None,
) -> dict[str, Any]:
    if blocker == blocked:
        raise VavError("SAFETY_SELF_BLOCK_FORBIDDEN", "You cannot block yourself.", status_code=409)
    low, high = canonical_pair(blocker, blocked)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:pair_key))"),
        {"pair_key": f"safety:block:{low}:{high}"},
    )
    existing = (
        (
            await session.execute(
                text(
                    "SELECT * FROM user_blocks WHERE blocker_user_id=:blocker AND blocked_user_id=:blocked "
                    "AND status='active' FOR UPDATE"
                ),
                {"blocker": blocker, "blocked": blocked},
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        version_row = (
            await session.execute(
                text(
                    "SELECT restriction_version FROM safety_pair_versions "
                    "WHERE user_low_id=:low AND user_high_id=:high"
                ),
                {"low": low, "high": high},
            )
        ).scalar_one_or_none()
        return {
            "id": str(existing["id"]),
            "status": "active",
            "restriction_version": version_row or 1,
        }
    block = (
        (
            await session.execute(
                text(
                    "INSERT INTO user_blocks "
                    "(blocker_user_id,blocked_user_id,status,source,source_report_id,reason_code,private_reason_encrypted) "
                    "VALUES (:blocker,:blocked,'active',:source,:report,:reason,:private) RETURNING *"
                ),
                {
                    "blocker": blocker,
                    "blocked": blocked,
                    "source": source,
                    "report": source_report_id,
                    "reason": reason_code,
                    "private": encrypt_sensitive({"reason": private_reason})
                    if private_reason
                    else None,
                },
            )
        )
        .mappings()
        .one()
    )
    version = await _propagate_block(
        session, blocker=blocker, blocked=blocked, block_id=block["id"]
    )
    await _audit(
        session,
        actor_user_id=blocker,
        subject_user_id=blocked,
        event_type="safety.block.created",
        aggregate_type="user_block",
        aggregate_id=block["id"],
        metadata={"source": source, "restriction_version": version},
    )
    return {"id": str(block["id"]), "status": "active", "restriction_version": version}


async def create_block(
    session: AsyncSession,
    *,
    blocker: UUID,
    blocked: UUID,
    reason_code: str | None = None,
    private_reason: str | None = None,
) -> dict[str, Any]:
    result = await _create_block(
        session,
        blocker=blocker,
        blocked=blocked,
        source="user",
        source_report_id=None,
        reason_code=reason_code,
        private_reason=private_reason,
    )
    await session.commit()
    return result


async def lift_block(session: AsyncSession, *, blocker: UUID, blocked: UUID) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE user_blocks SET status='lifted',lifted_at=now(),version=version+1 "
                "WHERE blocker_user_id=:blocker AND blocked_user_id=:blocked AND status='active' "
                "RETURNING id"
            ),
            {"blocker": blocker, "blocked": blocked},
        )
    ).first()
    if row is None:
        raise VavError("SAFETY_BLOCK_NOT_FOUND", "Active block was not found.", status_code=404)
    low, high = canonical_pair(blocker, blocked)
    version = await _pair_version(session, blocker, blocked)
    await session.execute(
        text(
            "UPDATE recommendation_pair_exclusions SET released_at=now() WHERE user_low_id=:low "
            "AND user_high_id=:high AND exclusion_type='block' AND released_at IS NULL"
        ),
        {"low": low, "high": high},
    )
    await _outbox(
        session,
        "safety.block.lifted",
        "user_block",
        row[0],
        {
            "blocker_user_id": str(blocker),
            "blocked_user_id": str(blocked),
            "restriction_version": version,
            "historical_access_restored": False,
        },
    )
    await _audit(
        session,
        actor_user_id=blocker,
        subject_user_id=blocked,
        event_type="safety.block.lifted",
        aggregate_type="user_block",
        aggregate_id=row[0],
        metadata={"restriction_version": version, "historical_access_restored": False},
    )
    await session.commit()
    return {"id": str(row[0]), "status": "lifted", "restriction_version": version}


async def list_blocks(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id,blocked_user_id,reason_code,created_at,version FROM user_blocks "
                "WHERE blocker_user_id=:user AND status='active' ORDER BY created_at DESC"
            ),
            {"user": user_id},
        )
    ).mappings()
    return [
        {
            "id": str(row["id"]),
            "blocked_user_id": str(row["blocked_user_id"]),
            "reason_code": row["reason_code"],
            "created_at": row["created_at"].isoformat(),
            "version": row["version"],
        }
        for row in rows
    ]


async def create_report(
    session: AsyncSession, *, reporter: UUID, payload: ReportCreateRequest
) -> dict[str, Any]:
    if payload.reported_user_id == reporter:
        raise VavError(
            "SAFETY_SELF_REPORT_FORBIDDEN", "You cannot report yourself.", status_code=409
        )
    existing = (
        (
            await session.execute(
                text(
                    "SELECT * FROM safety_reports WHERE reporter_user_id=:reporter "
                    "AND idempotency_key=:key"
                ),
                {"reporter": reporter, "key": payload.idempotency_key},
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        return _safe_report(dict(existing))
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:idempotency_scope))"),
        {"idempotency_scope": f"safety:report:{reporter}:{payload.idempotency_key}"},
    )
    existing = (
        (
            await session.execute(
                text(
                    "SELECT * FROM safety_reports WHERE reporter_user_id=:reporter "
                    "AND idempotency_key=:key"
                ),
                {"reporter": reporter, "key": payload.idempotency_key},
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        await session.commit()
        return _safe_report(dict(existing))
    settings = get_settings()
    recent = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM safety_reports WHERE reporter_user_id=:reporter "
                    "AND submitted_at >= now()-interval '1 hour'"
                ),
                {"reporter": reporter},
            )
        ).scalar_one()
    )
    if recent >= settings.safety_report_rate_limit_per_hour and not (
        payload.immediate_danger and settings.safety_immediate_report_rate_limit_bypass
    ):
        raise VavError(
            "SAFETY_REPORT_RATE_LIMITED",
            "Too many reports were submitted. Immediate safety reports remain available.",
            status_code=429,
        )
    priority = (
        "critical"
        if payload.immediate_danger
        else (
            "urgent"
            if payload.category.value in {"threat", "underage_concern", "money_request"}
            else "normal"
        )
    )
    report = (
        (
            await session.execute(
                text(
                    "INSERT INTO safety_reports "
                    "(report_number,reporter_user_id,reported_user_id,target_type,target_reference_id,"
                    "category,severity_claim,status,description_encrypted,user_safety_state,block_requested,"
                    "immediate_danger_claimed,source_context,idempotency_key) VALUES "
                    "(:number,:reporter,:reported,:target_type,:target_id,:category,:severity,'submitted',"
                    ":description,CAST(:safety_state AS jsonb),:block,:immediate,CAST(:context AS jsonb),:key) "
                    "RETURNING *"
                ),
                {
                    "number": _number("SR"),
                    "reporter": reporter,
                    "reported": payload.reported_user_id,
                    "target_type": payload.target_type,
                    "target_id": payload.target_reference_id,
                    "category": payload.category.value,
                    "severity": payload.severity_claim,
                    "description": (
                        encrypt_sensitive({"description": payload.description})
                        if payload.description
                        else None
                    ),
                    "safety_state": _json(
                        {"immediate_support_shown": payload.immediate_danger, "block_offered": True}
                    ),
                    "block": payload.block_user,
                    "immediate": payload.immediate_danger,
                    "context": _json(payload.source_context),
                    "key": payload.idempotency_key,
                },
            )
        )
        .mappings()
        .one()
    )
    case = (
        await session.execute(
            text(
                "INSERT INTO safety_cases "
                "(case_number,case_type,status,priority,subject_user_id,risk_level,primary_category,"
                "source_manifest,sla_due_at) VALUES (:number,'user_report','open',:priority,:subject,"
                ":risk,:category,CAST(:manifest AS jsonb),:sla) RETURNING id"
            ),
            {
                "number": _number("SC"),
                "priority": priority,
                "subject": payload.reported_user_id,
                "risk": "critical" if priority == "critical" else "moderate",
                "category": payload.category.value,
                "manifest": _json({"report_ids": [str(report["id"])]}),
                "sla": _sla_due(priority),
            },
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO safety_case_reports (safety_case_id,report_id,linked_by) "
            "VALUES (:case,:report,:actor)"
        ),
        {"case": case, "report": report["id"], "actor": reporter},
    )
    if payload.block_user and payload.reported_user_id:
        await _create_block(
            session,
            blocker=reporter,
            blocked=payload.reported_user_id,
            source="report",
            source_report_id=report["id"],
            reason_code=payload.category.value,
            private_reason=None,
        )
    await _outbox(
        session,
        "safety.report.submitted",
        "safety_report",
        report["id"],
        {
            "report_number": report["report_number"],
            "priority": priority,
            "case_id": str(case),
            "reporter_identity_confidential": True,
        },
    )
    await _audit(
        session,
        actor_user_id=reporter,
        subject_user_id=payload.reported_user_id,
        event_type="safety.report.submitted",
        aggregate_type="safety_report",
        aggregate_id=report["id"],
        metadata={"target_type": payload.target_type, "category": payload.category.value},
    )
    await session.commit()
    return _safe_report(dict(report))


def _sla_due(priority: str) -> datetime:
    settings = get_settings()
    now = datetime.now(UTC)
    if priority == "critical":
        return now + timedelta(minutes=settings.safety_case_critical_sla_minutes)
    if priority == "urgent":
        return now + timedelta(hours=settings.safety_case_urgent_sla_hours)
    if priority == "high":
        return now + timedelta(hours=settings.safety_case_high_sla_hours)
    return now + timedelta(hours=settings.safety_case_normal_sla_hours)


async def list_reports(session: AsyncSession, reporter: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT * FROM safety_reports WHERE reporter_user_id=:reporter "
                "ORDER BY submitted_at DESC LIMIT 200"
            ),
            {"reporter": reporter},
        )
    ).mappings()
    return [_safe_report(dict(row)) for row in rows]


async def get_report(session: AsyncSession, reporter: UUID, report_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM safety_reports WHERE id=:id AND reporter_user_id=:reporter"),
                {"id": report_id, "reporter": reporter},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("SAFETY_REPORT_NOT_FOUND", "Report was not found.", status_code=404)
    return _safe_report(dict(row))


async def withdraw_report(session: AsyncSession, reporter: UUID, report_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM safety_reports WHERE id=:id AND reporter_user_id=:reporter FOR UPDATE"
                ),
                {"id": report_id, "reporter": reporter},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("SAFETY_REPORT_NOT_FOUND", "Report was not found.", status_code=404)
    try:
        validate_transition(str(row["status"]), "withdrawn", REPORT_TRANSITIONS)
    except ValueError as exc:
        raise VavError(
            "SAFETY_REPORT_WITHDRAWAL_FORBIDDEN",
            "This report can no longer be withdrawn.",
            status_code=409,
        ) from exc
    updated = (
        (
            await session.execute(
                text(
                    "UPDATE safety_reports SET status='withdrawn',updated_at=now(),version=version+1 "
                    "WHERE id=:id RETURNING *"
                ),
                {"id": report_id},
            )
        )
        .mappings()
        .one()
    )
    await _audit(
        session,
        actor_user_id=reporter,
        subject_user_id=updated["reported_user_id"],
        event_type="safety.report.withdrawn",
        aggregate_type="safety_report",
        aggregate_id=report_id,
        metadata={"confirmed_restrictions_unchanged": True},
    )
    await session.commit()
    return _safe_report(dict(updated))


_CONTEXT_RESTRICTIONS: dict[str, frozenset[str]] = {
    "profile-view": frozenset(
        {"profile_hidden", "account_temporarily_suspended", "account_permanently_disabled"}
    ),
    "recommendation": frozenset(
        {
            "profile_hidden",
            "recommendation_disabled",
            "account_temporarily_suspended",
            "account_permanently_disabled",
        }
    ),
    "interaction": frozenset(
        {
            "like_disabled",
            "invitation_disabled",
            "communication_rate_limited",
            "account_temporarily_suspended",
            "account_permanently_disabled",
        }
    ),
    "contact-exchange": frozenset(
        {
            "contact_exchange_disabled",
            "account_temporarily_suspended",
            "account_permanently_disabled",
        }
    ),
    "relationship": frozenset(
        {
            "relationship_interaction_frozen",
            "account_temporarily_suspended",
            "account_permanently_disabled",
        }
    ),
    "activity": frozenset(
        {
            "activity_registration_disabled",
            "account_temporarily_suspended",
            "account_permanently_disabled",
        }
    ),
    "ai": frozenset(
        {
            "ai_write_actions_disabled",
            "account_temporarily_suspended",
            "account_permanently_disabled",
        }
    ),
}


async def evaluate_gate(
    session: AsyncSession,
    *,
    decision_context: str,
    subject_user_id: UUID,
    counterpart_user_id: UUID | None = None,
) -> TrustSafetyDecision:
    """Read-only safety gateway for business-domain transactions.

    The caller receives only an allow/deny contract. It never receives reports,
    evidence, rules or investigator notes, and a storage error fails closed.
    """

    if decision_context not in _CONTEXT_RESTRICTIONS:
        raise ValueError("unknown safety decision context")
    try:
        pair_version = 1
        if counterpart_user_id is not None:
            low, high = canonical_pair(subject_user_id, counterpart_user_id)
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT COALESCE((SELECT restriction_version FROM safety_pair_versions "
                            "WHERE user_low_id=:low AND user_high_id=:high),1) AS version,"
                            "EXISTS(SELECT 1 FROM user_blocks WHERE status='active' AND "
                            "((blocker_user_id=:subject AND blocked_user_id=:other) OR "
                            "(blocker_user_id=:other AND blocked_user_id=:subject))) AS blocked"
                        ),
                        {
                            "low": low,
                            "high": high,
                            "subject": subject_user_id,
                            "other": counterpart_user_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            pair_version = int(row["version"])
            if row["blocked"]:
                return TrustSafetyDecision(
                    allowed=False,
                    action="deny",
                    safe_reason_code="pair_blocked",
                    restriction_version=pair_version,
                    decision_id=uuid4(),
                )
        restriction = (
            (
                await session.execute(
                    text(
                        "SELECT restriction_type,version FROM account_restrictions WHERE user_id=:user "
                        "AND status='active' AND starts_at<=now() AND (ends_at IS NULL OR ends_at>now()) "
                        "AND restriction_type=ANY(CAST(:types AS varchar[])) ORDER BY version DESC LIMIT 1"
                    ),
                    {
                        "user": subject_user_id,
                        "types": list(_CONTEXT_RESTRICTIONS[decision_context]),
                    },
                )
            )
            .mappings()
            .first()
        )
        if restriction is not None:
            return TrustSafetyDecision(
                allowed=False,
                action="deny",
                safe_reason_code="account_restricted",
                restriction_version=max(pair_version, int(restriction["version"])),
                decision_id=uuid4(),
            )
        return TrustSafetyDecision(
            allowed=True,
            action="allow",
            safe_reason_code=None,
            restriction_version=pair_version,
            decision_id=uuid4(),
        )
    except (SQLAlchemyError, TypeError, ValueError):
        return TrustSafetyDecision(
            allowed=False,
            action="deny",
            safe_reason_code="safety_unavailable",
            restriction_version=0,
            decision_id=uuid4(),
            human_review_required=True,
        )


async def decide(
    session: AsyncSession,
    *,
    decision_context: str,
    subject_user_id: UUID,
    counterpart_user_id: UUID | None,
    target_type: str | None,
    target_reference_id: UUID | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    if decision_context not in _CONTEXT_RESTRICTIONS:
        raise VavError(
            "SAFETY_CONTEXT_INVALID", "Unknown safety decision context.", status_code=422
        )
    settings = get_settings()
    try:
        pair_blocked = False
        pair_version = 1
        if counterpart_user_id is not None:
            if counterpart_user_id == subject_user_id:
                raise VavError(
                    "SAFETY_PAIR_INVALID",
                    "A safety pair requires different users.",
                    status_code=422,
                )
            low, high = canonical_pair(subject_user_id, counterpart_user_id)
            pair = (
                (
                    await session.execute(
                        text(
                            "SELECT COALESCE(v.restriction_version,1) AS version,EXISTS(SELECT 1 FROM user_blocks b "
                            "WHERE b.status='active' AND ((b.blocker_user_id=:subject AND b.blocked_user_id=:other) "
                            "OR (b.blocker_user_id=:other AND b.blocked_user_id=:subject))) AS blocked "
                            "FROM (SELECT 1) seed LEFT JOIN safety_pair_versions v "
                            "ON v.user_low_id=:low AND v.user_high_id=:high"
                        ),
                        {
                            "subject": subject_user_id,
                            "other": counterpart_user_id,
                            "low": low,
                            "high": high,
                        },
                    )
                )
                .mappings()
                .one()
            )
            pair_blocked = bool(pair["blocked"])
            pair_version = int(pair["version"])
        restriction_types = _CONTEXT_RESTRICTIONS[decision_context]
        restrictions = list(
            (
                await session.execute(
                    text(
                        "SELECT id,restriction_type,version,ends_at FROM account_restrictions "
                        "WHERE user_id=:user AND status='active' AND starts_at <= now() "
                        "AND (ends_at IS NULL OR ends_at > now()) "
                        "AND restriction_type = ANY(CAST(:types AS varchar[])) "
                        "ORDER BY created_at"
                    ),
                    {"user": subject_user_id, "types": list(restriction_types)},
                )
            ).mappings()
        )
        registered_signals = {
            "pair_blocked": pair_blocked,
            "active_restriction_count": len(restrictions),
            **{
                key: value
                for key, value in context.items()
                if key
                in {
                    "like_rate",
                    "invitation_rate",
                    "repeated_contact_count",
                    "post_decline_contact_count",
                    "distinct_target_count",
                    "money_request_detected",
                    "external_payment_link_detected",
                    "threat_detected",
                    "staff_impersonation_detected",
                    "account_takeover_signal",
                    "classifier_confidence_bps",
                }
            },
        }
        rule_rows = (
            await session.execute(
                text(
                    "SELECT rule_code,semantic_version,condition_definition,action_definition,severity,score_delta "
                    "FROM safety_risk_rules WHERE status='active' "
                    "AND applicable_modules ? :module ORDER BY rule_code"
                ),
                {"module": decision_context},
            )
        ).mappings()
        rule_hits: list[dict[str, Any]] = []
        score = 0
        rule_action: str | None = None
        for rule in rule_rows:
            definition = rule["condition_definition"]
            conditions = definition.get("all", [definition]) if isinstance(definition, dict) else []
            if conditions and all(
                evaluate_condition(item, registered_signals) for item in conditions
            ):
                score += int(rule["score_delta"])
                action = rule["action_definition"].get("action")
                rule_action = str(action) if action else rule_action
                rule_hits.append(
                    {
                        "rule_code": rule["rule_code"],
                        "semantic_version": rule["semantic_version"],
                        "severity": rule["severity"],
                    }
                )
        if pair_blocked:
            action, reason, allowed, review = "deny", "pair_blocked", False, False
            risk_level = "high"
        elif restrictions:
            action, reason, allowed, review = "deny", "account_restricted", False, False
            risk_level = "high"
        elif rule_action in {"deny", "interaction_freeze", "content_hold", "temporary_restriction"}:
            action, reason, allowed, review = rule_action, "safety_rule", False, True
            risk_level = "high"
        elif rule_action in {"rate_limit", "human_review_required"}:
            action, reason, allowed, review = rule_action, "safety_review", False, True
            risk_level = "moderate"
        else:
            action, reason, allowed, review = "allow", None, True, False
            risk_level = "low" if rule_hits else "none"
        decision_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO safety_risk_decisions "
                "(id,subject_user_id,target_type,target_reference_id,decision_context,risk_level,risk_score,"
                "rule_hits,model_signals,decision,reason_codes,policy_version,restriction_version,human_review_required) "
                "VALUES (:id,:subject,:target_type,:target_id,:context,:risk,:score,CAST(:hits AS jsonb),'[]'::jsonb,"
                ":decision,CAST(:reasons AS jsonb),:policy,:version,:review)"
            ),
            {
                "id": decision_id,
                "subject": subject_user_id,
                "target_type": target_type,
                "target_id": target_reference_id,
                "context": decision_context,
                "risk": risk_level,
                "score": score,
                "hits": _json(rule_hits),
                "decision": action,
                "reasons": _json([reason] if reason else []),
                "policy": settings.safety_default_policy_version,
                "version": max([pair_version, *[int(item["version"]) for item in restrictions]]),
                "review": review,
            },
        )
        await session.commit()
        return TrustSafetyDecision(
            allowed=allowed,
            action=action,
            safe_reason_code=reason,
            restriction_version=max(
                [pair_version, *[int(item["version"]) for item in restrictions]]
            ),
            decision_id=decision_id,
            human_review_required=review,
        ).as_dict()
    except VavError:
        raise
    except (SQLAlchemyError, ValueError, TypeError) as exc:
        await session.rollback()
        if settings.safety_fail_closed:
            decision_id = uuid4()
            return TrustSafetyDecision(
                allowed=False,
                action="deny",
                safe_reason_code="safety_unavailable",
                restriction_version=0,
                decision_id=decision_id,
                human_review_required=True,
            ).as_dict()
        raise VavError(
            "SAFETY_DECISION_FAILED", "Safety decision could not be evaluated.", status_code=503
        ) from exc


async def create_moderation_task(
    session: AsyncSession, *, payload: ModerationCreateRequest
) -> dict[str, Any]:
    settings = get_settings()
    checksum = hashlib.sha256(payload.content.encode()).hexdigest()
    hits = sorted(classify_text(payload.content))
    high_risk = bool(set(hits) & {"money_request", "threat", "impersonation"})
    recommendation = "content_hold" if high_risk else ("reject" if hits else "approve")
    status = "awaiting_human" if high_risk else "completed"
    task_id = uuid4()
    try:
        task = (
            (
                await session.execute(
                    text(
                        "INSERT INTO moderation_tasks "
                        "(id,target_type,target_reference_id,target_version,status,priority,policy_version,completed_at) "
                        "VALUES (:id,:type,:reference,:version,:status,:priority,:policy,"
                        "CASE WHEN :status='completed' THEN now() END) RETURNING *"
                    ),
                    {
                        "id": task_id,
                        "type": payload.target_type.value,
                        "reference": payload.target_reference_id,
                        "version": payload.target_version,
                        "status": status,
                        "priority": "urgent" if high_risk else payload.priority,
                        "policy": settings.safety_default_policy_version,
                    },
                )
            )
            .mappings()
            .one()
        )
    except IntegrityError:
        await session.rollback()
        existing = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM moderation_tasks WHERE target_type=:type AND target_reference_id=:reference "
                        "AND target_version=:version"
                    ),
                    {
                        "type": payload.target_type.value,
                        "reference": payload.target_reference_id,
                        "version": payload.target_version,
                    },
                )
            )
            .mappings()
            .one()
        )
        return {"id": str(existing["id"]), "status": existing["status"], "idempotent": True}
    automated_id = (
        await session.execute(
            text(
                "INSERT INTO moderation_automated_results "
                "(moderation_task_id,provider,model_name,model_revision,category_scores,detected_patterns,"
                "recommendation,confidence_basis_points,input_checksum) VALUES "
                "(:task,'deterministic_rules','registered-patterns',:revision,CAST(:scores AS jsonb),"
                "CAST(:patterns AS jsonb),:recommendation,:confidence,:checksum) RETURNING id"
            ),
            {
                "task": task_id,
                "revision": settings.safety_default_policy_version,
                "scores": _json({hit: 10000 for hit in hits}),
                "patterns": _json(hits),
                "recommendation": recommendation,
                "confidence": 10000 if hits else 9500,
                "checksum": checksum,
            },
        )
    ).scalar_one()
    await session.execute(
        text("UPDATE moderation_tasks SET automated_result_id=:result WHERE id=:task"),
        {"result": automated_id, "task": task_id},
    )
    await _outbox(
        session,
        "safety.moderation.held" if high_risk else f"safety.moderation.{recommendation}",
        "moderation_task",
        task_id,
        {
            "target_type": payload.target_type.value,
            "target_reference_id": str(payload.target_reference_id),
            "target_version": payload.target_version,
            "category_codes": hits,
            "human_review_required": high_risk,
        },
    )
    await session.commit()
    return {
        "id": str(task["id"]),
        "status": status,
        "recommendation": recommendation,
        "category_codes": hits,
        "human_review_required": high_risk,
        "input_checksum": checksum,
    }


async def decide_moderation(
    session: AsyncSession,
    *,
    task_id: UUID,
    actor: UUID,
    payload: ModerationDecisionRequest,
) -> dict[str, Any]:
    task = (
        (
            await session.execute(
                text("SELECT * FROM moderation_tasks WHERE id=:id FOR UPDATE"), {"id": task_id}
            )
        )
        .mappings()
        .first()
    )
    if task is None:
        raise VavError(
            "MODERATION_TASK_NOT_FOUND", "Moderation task was not found.", status_code=404
        )
    decision_id = (
        await session.execute(
            text(
                "INSERT INTO moderation_decisions "
                "(moderation_task_id,decision,category_codes,reason_code,user_message_safe,"
                "internal_note_encrypted,decided_by,policy_version) VALUES "
                "(:task,:decision,CAST(:categories AS jsonb),:reason,:message,:note,:actor,:policy) RETURNING id"
            ),
            {
                "task": task_id,
                "decision": payload.decision,
                "categories": _json(payload.category_codes),
                "reason": payload.reason_code,
                "message": payload.user_message,
                "note": (
                    encrypt_sensitive({"note": payload.internal_note})
                    if payload.internal_note
                    else None
                ),
                "actor": actor,
                "policy": task["policy_version"],
            },
        )
    ).scalar_one()
    await session.execute(
        text("UPDATE moderation_tasks SET status='completed',completed_at=now() WHERE id=:id"),
        {"id": task_id},
    )
    await _outbox(
        session,
        f"safety.moderation.{payload.decision}",
        "moderation_task",
        task_id,
        {
            "decision_id": str(decision_id),
            "target_type": task["target_type"],
            "target_reference_id": str(task["target_reference_id"]),
            "target_version": task["target_version"],
        },
    )
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=None,
        event_type="safety.moderation.decided",
        aggregate_type="moderation_task",
        aggregate_id=task_id,
        metadata={"decision": payload.decision},
    )
    await session.commit()
    return {"id": str(decision_id), "task_id": str(task_id), "decision": payload.decision}


async def create_restriction(
    session: AsyncSession, *, actor: UUID, payload: RestrictionCreateRequest
) -> dict[str, Any]:
    duration = (
        int((payload.ends_at - payload.starts_at).total_seconds() // 3600)
        if payload.ends_at
        else None
    )
    second_approval = requires_second_approval(payload.restriction_type.value, duration)
    status = "pending_approval" if second_approval else "active"
    restriction = (
        (
            await session.execute(
                text(
                    "INSERT INTO account_restrictions "
                    "(user_id,restriction_type,scope_definition,status,source_type,source_reference_id,"
                    "reason_code,user_message_safe,internal_reason_encrypted,starts_at,ends_at,appeal_allowed,"
                    "imposed_by,approved_by) VALUES (:user,:type,CAST(:scope AS jsonb),:status,:source,:reference,"
                    ":reason,:message,:internal,:starts,:ends,:appeal,:actor,NULL) "
                    "RETURNING *"
                ),
                {
                    "user": payload.user_id,
                    "type": payload.restriction_type.value,
                    "scope": _json(payload.scope_definition),
                    "status": status,
                    "source": payload.source_type,
                    "reference": payload.source_reference_id,
                    "reason": payload.reason_code,
                    "message": payload.user_message,
                    "internal": (
                        encrypt_sensitive({"reason": payload.internal_reason})
                        if payload.internal_reason
                        else None
                    ),
                    "starts": payload.starts_at,
                    "ends": payload.ends_at,
                    "appeal": payload.appeal_allowed,
                    "actor": actor,
                },
            )
        )
        .mappings()
        .one()
    )
    if status == "active":
        await _outbox(
            session,
            "safety.restriction.created",
            "account_restriction",
            restriction["id"],
            {
                "user_id": str(payload.user_id),
                "restriction_type": payload.restriction_type.value,
                "version": restriction["version"],
            },
        )
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=payload.user_id,
        event_type="safety.restriction.requested",
        aggregate_type="account_restriction",
        aggregate_id=restriction["id"],
        metadata={"type": payload.restriction_type.value, "second_approval": second_approval},
    )
    await session.commit()
    return {
        "id": str(restriction["id"]),
        "status": status,
        "second_approval_required": second_approval,
        "version": restriction["version"],
    }


async def approve_restriction(
    session: AsyncSession, *, restriction_id: UUID, approver: UUID
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM account_restrictions WHERE id=:id FOR UPDATE"),
                {"id": restriction_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "SAFETY_RESTRICTION_NOT_FOUND", "Restriction was not found.", status_code=404
        )
    if row["status"] != "pending_approval":
        raise VavError(
            "SAFETY_RESTRICTION_NOT_PENDING",
            "Restriction is not awaiting approval.",
            status_code=409,
        )
    if row["imposed_by"] == approver:
        raise VavError(
            "SAFETY_FOUR_EYES_REQUIRED",
            "A different administrator must approve this restriction.",
            status_code=409,
        )
    updated = (
        (
            await session.execute(
                text(
                    "UPDATE account_restrictions SET status='active',approved_by=:actor,version=version+1,"
                    "updated_at=now() WHERE id=:id RETURNING *"
                ),
                {"actor": approver, "id": restriction_id},
            )
        )
        .mappings()
        .one()
    )
    await _outbox(
        session,
        "safety.restriction.created",
        "account_restriction",
        restriction_id,
        {
            "user_id": str(updated["user_id"]),
            "restriction_type": updated["restriction_type"],
            "version": updated["version"],
        },
    )
    await _audit(
        session,
        actor_user_id=approver,
        subject_user_id=updated["user_id"],
        event_type="safety.restriction.approved",
        aggregate_type="account_restriction",
        aggregate_id=restriction_id,
    )
    await session.commit()
    return {"id": str(restriction_id), "status": "active", "version": updated["version"]}


async def lift_restriction(
    session: AsyncSession, *, restriction_id: UUID, actor: UUID, reason: str
) -> dict[str, Any]:
    updated = (
        (
            await session.execute(
                text(
                    "UPDATE account_restrictions SET status='lifted',lifted_by=:actor,lifted_at=now(),"
                    "lift_reason_encrypted=:reason,version=version+1,updated_at=now() "
                    "WHERE id=:id AND status='active' RETURNING *"
                ),
                {
                    "actor": actor,
                    "reason": encrypt_sensitive({"reason": reason}),
                    "id": restriction_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if updated is None:
        raise VavError(
            "SAFETY_RESTRICTION_NOT_ACTIVE", "Active restriction was not found.", status_code=404
        )
    await _outbox(
        session,
        "safety.restriction.lifted",
        "account_restriction",
        restriction_id,
        {
            "user_id": str(updated["user_id"]),
            "restriction_type": updated["restriction_type"],
            "version": updated["version"],
        },
    )
    await session.commit()
    return {"id": str(restriction_id), "status": "lifted", "version": updated["version"]}


async def restriction_summary(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,restriction_type,user_message_safe,starts_at,ends_at,appeal_allowed,version "
                    "FROM account_restrictions WHERE user_id=:user AND status='active' AND starts_at<=now() "
                    "AND (ends_at IS NULL OR ends_at>now()) ORDER BY created_at DESC"
                ),
                {"user": user_id},
            )
        ).mappings()
    )
    return {
        "restricted": bool(rows),
        "restrictions": [
            {
                "id": str(row["id"]),
                "restriction_type": row["restriction_type"],
                "user_message": row["user_message_safe"],
                "starts_at": row["starts_at"].isoformat(),
                "ends_at": row["ends_at"].isoformat() if row["ends_at"] else None,
                "appeal_allowed": row["appeal_allowed"],
                "version": row["version"],
            }
            for row in rows
        ],
    }


async def create_appeal(
    session: AsyncSession, *, appellant: UUID, payload: AppealCreateRequest
) -> dict[str, Any]:
    restriction = None
    case_id = None
    decision_id = payload.decision_id
    if payload.restriction_id:
        restriction = (
            (
                await session.execute(
                    text("SELECT * FROM account_restrictions WHERE id=:id AND user_id=:user"),
                    {"id": payload.restriction_id, "user": appellant},
                )
            )
            .mappings()
            .first()
        )
        if restriction is None or not restriction["appeal_allowed"]:
            raise VavError(
                "SAFETY_APPEAL_INELIGIBLE",
                "This restriction is not eligible for appeal.",
                status_code=409,
            )
        if restriction["source_type"] == "case":
            case_id = restriction["source_reference_id"]
    if decision_id:
        decision = (
            (
                await session.execute(
                    text(
                        "SELECT d.id,d.safety_case_id,d.appeal_allowed FROM safety_case_decisions d "
                        "JOIN safety_cases c ON c.id=d.safety_case_id "
                        "WHERE d.id=:decision AND c.subject_user_id=:appellant"
                    ),
                    {"decision": decision_id, "appellant": appellant},
                )
            )
            .mappings()
            .first()
        )
        if decision is None or not decision["appeal_allowed"]:
            raise VavError(
                "SAFETY_APPEAL_INELIGIBLE",
                "This decision is not eligible for appeal.",
                status_code=409,
            )
        if case_id is not None and case_id != decision["safety_case_id"]:
            raise VavError(
                "SAFETY_APPEAL_TARGET_MISMATCH",
                "The restriction and decision do not belong to the same case.",
                status_code=422,
            )
        case_id = decision["safety_case_id"]
    due = datetime.now(UTC) + timedelta(days=get_settings().safety_appeal_default_due_days)
    try:
        appeal = (
            (
                await session.execute(
                    text(
                        "INSERT INTO safety_appeals "
                        "(appeal_number,appellant_user_id,restriction_id,safety_case_id,decision_id,status,"
                        "appeal_reason_encrypted,evidence_manifest,review_due_at) VALUES "
                        "(:number,:user,:restriction,:case,:decision,'submitted',:reason,CAST(:evidence AS jsonb),:due) "
                        "RETURNING *"
                    ),
                    {
                        "number": _number("SA"),
                        "user": appellant,
                        "restriction": payload.restriction_id,
                        "case": case_id,
                        "decision": decision_id,
                        "reason": encrypt_sensitive({"reason": payload.reason}),
                        "evidence": _json(payload.evidence_manifest),
                        "due": due,
                    },
                )
            )
            .mappings()
            .one()
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "SAFETY_APPEAL_ALREADY_OPEN",
            "An appeal is already open for this restriction.",
            status_code=409,
        ) from exc
    await _outbox(
        session,
        "safety.appeal.submitted",
        "safety_appeal",
        appeal["id"],
        {"appellant_user_id": str(appellant), "appeal_number": appeal["appeal_number"]},
    )
    await session.commit()
    return {
        "id": str(appeal["id"]),
        "appeal_number": appeal["appeal_number"],
        "status": appeal["status"],
        "review_due_at": appeal["review_due_at"].isoformat(),
    }


async def list_appeals(session: AsyncSession, appellant: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id,appeal_number,restriction_id,status,outcome,outcome_message_safe,submitted_at,"
                "review_due_at,decided_at,version FROM safety_appeals WHERE appellant_user_id=:user "
                "ORDER BY submitted_at DESC"
            ),
            {"user": appellant},
        )
    ).mappings()
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "restriction_id": str(row["restriction_id"]) if row["restriction_id"] else None,
        }
        for row in rows
    ]


async def decide_appeal(
    session: AsyncSession,
    *,
    appeal_id: UUID,
    reviewer: UUID,
    payload: AppealDecisionRequest,
) -> dict[str, Any]:
    appeal = (
        (
            await session.execute(
                text(
                    "SELECT a.*,d.decided_by AS original_decider,d.approved_by AS original_approver,"
                    "r.imposed_by AS restriction_imposer,r.approved_by AS restriction_approver "
                    "FROM safety_appeals a LEFT JOIN safety_case_decisions d ON d.id=a.decision_id "
                    "LEFT JOIN account_restrictions r ON r.id=a.restriction_id "
                    "WHERE a.id=:id FOR UPDATE OF a"
                ),
                {"id": appeal_id},
            )
        )
        .mappings()
        .first()
    )
    if appeal is None:
        raise VavError("SAFETY_APPEAL_NOT_FOUND", "Appeal was not found.", status_code=404)
    if reviewer in {
        appeal["original_decider"],
        appeal["original_approver"],
        appeal["restriction_imposer"],
        appeal["restriction_approver"],
    }:
        raise VavError(
            "SAFETY_APPEAL_INDEPENDENCE_REQUIRED",
            "The original decision maker cannot review this appeal.",
            status_code=409,
        )
    if appeal["status"] in {"decided", "closed", "ineligible"}:
        raise VavError(
            "SAFETY_APPEAL_FINAL", "Appeal already has a final outcome.", status_code=409
        )
    if payload.outcome == "modified" and not appeal["restriction_id"]:
        raise VavError(
            "SAFETY_APPEAL_MODIFICATION_TARGET_REQUIRED",
            "A modified outcome requires a related restriction.",
            status_code=422,
        )
    updated = (
        (
            await session.execute(
                text(
                    "UPDATE safety_appeals SET status=CASE WHEN :outcome='ineligible' THEN 'ineligible' ELSE 'decided' END,"
                    "outcome=:outcome,outcome_message_safe=:message,internal_review_encrypted=:review,"
                    "decided_by=:actor,decided_at=now(),updated_at=now(),version=version+1 WHERE id=:id RETURNING *"
                ),
                {
                    "outcome": payload.outcome,
                    "message": payload.outcome_message,
                    "review": encrypt_sensitive({"review": payload.internal_review}),
                    "actor": reviewer,
                    "id": appeal_id,
                },
            )
        )
        .mappings()
        .one()
    )
    if payload.outcome == "overturned" and updated["restriction_id"]:
        lifted = (
            (
                await session.execute(
                    text(
                        "UPDATE account_restrictions SET status='lifted',lifted_by=:actor,lifted_at=now(),"
                        "lift_reason_encrypted=:reason,version=version+1,updated_at=now() "
                        "WHERE id=:id AND status='active' RETURNING user_id,restriction_type,version"
                    ),
                    {
                        "actor": reviewer,
                        "reason": encrypt_sensitive({"reason": "appeal_overturned"}),
                        "id": updated["restriction_id"],
                    },
                )
            )
            .mappings()
            .first()
        )
        if lifted is not None:
            await _outbox(
                session,
                "safety.restriction.lifted",
                "account_restriction",
                updated["restriction_id"],
                {
                    "user_id": str(lifted["user_id"]),
                    "restriction_type": lifted["restriction_type"],
                    "version": lifted["version"],
                    "appeal_id": str(appeal_id),
                },
            )
        await session.execute(
            text(
                "INSERT INTO safety_remediations (appeal_id,action_manifest,status,executed_by,completed_at) "
                "VALUES (:appeal,CAST(:manifest AS jsonb),'completed',:actor,now()) "
                "ON CONFLICT (appeal_id) DO NOTHING"
            ),
            {
                "appeal": appeal_id,
                "manifest": _json(
                    {
                        "restriction_removed": True,
                        "other_user_blocks_restored": False,
                        "contact_grants_restored": False,
                    }
                ),
                "actor": reviewer,
            },
        )
    elif payload.outcome == "modified" and updated["restriction_id"]:
        modified = (
            (
                await session.execute(
                    text(
                        "UPDATE account_restrictions SET scope_definition=COALESCE(CAST(:scope AS jsonb),scope_definition),"
                        "ends_at=COALESCE(:ends_at,ends_at),version=version+1,updated_at=now() "
                        "WHERE id=:id AND status='active' RETURNING user_id,restriction_type,version"
                    ),
                    {
                        "scope": (
                            _json(payload.modified_scope_definition)
                            if payload.modified_scope_definition is not None
                            else None
                        ),
                        "ends_at": payload.modified_ends_at,
                        "id": updated["restriction_id"],
                    },
                )
            )
            .mappings()
            .first()
        )
        if modified is None:
            raise VavError(
                "SAFETY_RESTRICTION_NOT_ACTIVE",
                "The appealed restriction is no longer active.",
                status_code=409,
            )
        await _outbox(
            session,
            "safety.restriction.updated",
            "account_restriction",
            updated["restriction_id"],
            {
                "user_id": str(modified["user_id"]),
                "restriction_type": modified["restriction_type"],
                "version": modified["version"],
                "appeal_id": str(appeal_id),
            },
        )
        await session.execute(
            text(
                "INSERT INTO safety_remediations (appeal_id,action_manifest,status,executed_by,completed_at) "
                "VALUES (:appeal,CAST(:manifest AS jsonb),'completed',:actor,now()) "
                "ON CONFLICT (appeal_id) DO NOTHING"
            ),
            {
                "appeal": appeal_id,
                "manifest": _json(
                    {
                        "restriction_modified": True,
                        "other_user_blocks_restored": False,
                        "contact_grants_restored": False,
                    }
                ),
                "actor": reviewer,
            },
        )
    await _outbox(
        session,
        f"safety.appeal.{payload.outcome}",
        "safety_appeal",
        appeal_id,
        {"appellant_user_id": str(updated["appellant_user_id"]), "outcome": payload.outcome},
    )
    await session.commit()
    return {"id": str(appeal_id), "status": updated["status"], "outcome": payload.outcome}


async def create_rule(
    session: AsyncSession, *, actor: UUID, payload: RuleCreateRequest
) -> dict[str, Any]:
    definition = payload.condition_definition
    conditions = definition.get("all", [definition]) if isinstance(definition, dict) else []
    try:
        for condition in conditions:
            evaluate_condition(condition, {str(condition.get("signal")): condition.get("value")})
    except (TypeError, ValueError) as exc:
        raise VavError(
            "SAFETY_RULE_DSL_INVALID",
            "Rule conditions must use registered signals and supported operators.",
            status_code=422,
        ) from exc
    action = payload.action_definition.get("action")
    if action not in {
        "allow_with_monitoring",
        "rate_limit",
        "content_hold",
        "interaction_freeze",
        "require_reverification",
        "temporary_restriction",
        "human_review_required",
        "deny",
    }:
        raise VavError(
            "SAFETY_RULE_ACTION_INVALID",
            "Rule actions must use the registered safety action set.",
            status_code=422,
        )
    rule = (
        (
            await session.execute(
                text(
                    "INSERT INTO safety_risk_rules "
                    "(rule_code,semantic_version,category,rule_type,condition_schema,condition_definition,"
                    "action_definition,severity,score_delta,status,applicable_modules,rollout_basis_points,created_by) "
                    "VALUES (:code,:version,:category,:type,CAST(:schema AS jsonb),CAST(:condition AS jsonb),"
                    "CAST(:action AS jsonb),:severity,:score,'pending_approval',CAST(:modules AS jsonb),:rollout,:actor) "
                    "RETURNING id,status"
                ),
                {
                    "code": payload.rule_code,
                    "version": payload.semantic_version,
                    "category": payload.category,
                    "type": payload.rule_type,
                    "schema": _json({"dsl": "registered-signals-v1"}),
                    "condition": _json(payload.condition_definition),
                    "action": _json(payload.action_definition),
                    "severity": payload.severity,
                    "score": payload.score_delta,
                    "modules": _json(payload.applicable_modules),
                    "rollout": payload.rollout_basis_points,
                    "actor": actor,
                },
            )
        )
        .mappings()
        .one()
    )
    await session.commit()
    return {"id": str(rule["id"]), "status": rule["status"]}


async def approve_and_activate_rule(
    session: AsyncSession, *, rule_id: UUID, approver: UUID
) -> dict[str, Any]:
    rule = (
        (
            await session.execute(
                text("SELECT * FROM safety_risk_rules WHERE id=:id FOR UPDATE"), {"id": rule_id}
            )
        )
        .mappings()
        .first()
    )
    if rule is None:
        raise VavError("SAFETY_RULE_NOT_FOUND", "Safety rule was not found.", status_code=404)
    if rule["status"] == "active":
        return {"id": str(rule_id), "status": "active", "idempotent": True}
    if rule["status"] not in {"pending_approval", "approved"}:
        raise VavError(
            "SAFETY_RULE_NOT_APPROVABLE",
            "Only a pending or approved rule can be activated.",
            status_code=409,
        )
    if rule["created_by"] == approver:
        raise VavError(
            "SAFETY_FOUR_EYES_REQUIRED",
            "A different administrator must approve this rule.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE safety_risk_rules SET status='retired',retired_at=now() WHERE rule_code=:code "
            "AND status='active' AND id<>:id"
        ),
        {"code": rule["rule_code"], "id": rule_id},
    )
    await session.execute(
        text(
            "UPDATE safety_risk_rules SET status='active',approved_by=:actor,approved_at=now(),"
            "activated_at=now() WHERE id=:id"
        ),
        {"actor": approver, "id": rule_id},
    )
    await _audit(
        session,
        actor_user_id=approver,
        subject_user_id=None,
        event_type="safety.rule.activated",
        aggregate_type="safety_risk_rule",
        aggregate_id=rule_id,
        metadata={"rule_code": rule["rule_code"], "semantic_version": rule["semantic_version"]},
    )
    await session.commit()
    return {"id": str(rule_id), "status": "active"}


async def rollback_rule(
    session: AsyncSession, *, rule_id: UUID, actor: UUID, reason: str
) -> dict[str, Any]:
    rule = (
        (
            await session.execute(
                text("SELECT * FROM safety_risk_rules WHERE id=:id FOR UPDATE"), {"id": rule_id}
            )
        )
        .mappings()
        .first()
    )
    if rule is None:
        raise VavError("SAFETY_RULE_NOT_FOUND", "Safety rule was not found.", status_code=404)
    if rule["status"] != "active":
        raise VavError(
            "SAFETY_RULE_NOT_ACTIVE", "Only an active rule can be rolled back.", status_code=409
        )
    predecessor = (
        (
            await session.execute(
                text(
                    "SELECT id FROM safety_risk_rules WHERE rule_code=:code AND id<>:id "
                    "AND status IN ('retired','approved') ORDER BY activated_at DESC NULLS LAST,created_at DESC LIMIT 1"
                ),
                {"code": rule["rule_code"], "id": rule_id},
            )
        )
        .mappings()
        .first()
    )
    await session.execute(
        text("UPDATE safety_risk_rules SET status='rolled_back',retired_at=now() WHERE id=:id"),
        {"id": rule_id},
    )
    restored_id: UUID | None = None
    if predecessor is not None:
        restored_id = predecessor["id"]
        await session.execute(
            text(
                "UPDATE safety_risk_rules SET status='active',activated_at=now(),retired_at=NULL WHERE id=:id"
            ),
            {"id": restored_id},
        )
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=None,
        event_type="safety.rule.rolled_back",
        aggregate_type="safety_risk_rule",
        aggregate_id=rule_id,
        metadata={"reason": reason, "restored_rule_id": str(restored_id) if restored_id else None},
    )
    await session.commit()
    return {
        "id": str(rule_id),
        "status": "rolled_back",
        "restored_rule_id": str(restored_id) if restored_id else None,
    }


async def upload_report_evidence(
    session: AsyncSession,
    *,
    reporter: UUID,
    report_id: UUID,
    payload: UserEvidenceUploadRequest,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT cr.safety_case_id FROM safety_reports r JOIN safety_case_reports cr ON cr.report_id=r.id "
                    "WHERE r.id=:report AND r.reporter_user_id=:reporter"
                ),
                {"report": report_id, "reporter": reporter},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("SAFETY_REPORT_NOT_FOUND", "Report was not found.", status_code=404)
    snapshot = {
        "content": payload.content,
        "filename": payload.filename,
        "media_type": payload.media_type,
        "submitted_by_reporter": True,
    }
    checksum = hashlib.sha256(_json(snapshot).encode()).hexdigest()
    evidence_id = (
        await session.execute(
            text(
                "INSERT INTO safety_evidence_items (safety_case_id,evidence_type,source_module,source_reference_id,"
                "evidence_snapshot_encrypted,evidence_checksum_sha256,collection_reason,collected_by_type,"
                "collected_by_user_id,sensitivity,preservation_status,retention_policy_code) VALUES "
                "(:case,:type,'user_report',:report,CAST(:snapshot AS jsonb),:checksum,:reason,'reporter',"
                ":actor,'highly_restricted','active','safety_case_default') RETURNING id"
            ),
            {
                "case": row["safety_case_id"],
                "type": payload.evidence_type,
                "report": report_id,
                "snapshot": _json(encrypt_sensitive(snapshot)),
                "checksum": checksum,
                "reason": payload.collection_reason,
                "actor": reporter,
            },
        )
    ).scalar_one()
    await _audit(
        session,
        actor_user_id=reporter,
        subject_user_id=None,
        event_type="safety.case.evidence_collected",
        aggregate_type="safety_evidence_item",
        aggregate_id=evidence_id,
        metadata={"case_id": str(row["safety_case_id"]), "source_module": "user_report"},
    )
    await session.commit()
    return {"id": str(evidence_id), "checksum_sha256": checksum, "preservation_status": "active"}


async def _case_actor_conflicted(
    session: AsyncSession, *, case_id: UUID, actor: UUID
) -> tuple[bool, dict[str, Any] | None]:
    case = (
        (
            await session.execute(
                text(
                    "SELECT c.*,EXISTS(SELECT 1 FROM safety_case_reports cr JOIN safety_reports r ON r.id=cr.report_id "
                    "WHERE cr.safety_case_id=c.id AND r.reporter_user_id=:actor) AS is_reporter "
                    "FROM safety_cases c WHERE c.id=:case"
                ),
                {"case": case_id, "actor": actor},
            )
        )
        .mappings()
        .first()
    )
    if case is None:
        return False, None
    return bool(case["subject_user_id"] == actor or case["is_reporter"]), dict(case)


async def assign_case(
    session: AsyncSession, *, case_id: UUID, actor: UUID, payload: CaseAssignmentRequest
) -> dict[str, Any]:
    actor_conflicted, _ = await _case_actor_conflicted(session, case_id=case_id, actor=actor)
    if actor_conflicted:
        raise VavError(
            "SAFETY_CASE_CONFLICT",
            "A conflicted operator cannot assign this case.",
            status_code=409,
        )
    conflicted, case = await _case_actor_conflicted(
        session, case_id=case_id, actor=payload.assigned_to
    )
    if case is None:
        raise VavError("SAFETY_CASE_NOT_FOUND", "Safety case was not found.", status_code=404)
    if conflicted:
        raise VavError(
            "SAFETY_CASE_CONFLICT", "A conflicted investigator cannot be assigned.", status_code=409
        )
    row = (
        (
            await session.execute(
                text(
                    "UPDATE safety_cases SET assigned_to=:assignee,assigned_team=:team,assigned_at=now(),"
                    "status=CASE WHEN status IN ('open','triaged','reopened') THEN 'assigned' ELSE status END,"
                    "version=version+1,updated_at=now() WHERE id=:id AND version=:version RETURNING version,status"
                ),
                {
                    "assignee": payload.assigned_to,
                    "team": payload.assigned_team,
                    "id": case_id,
                    "version": payload.expected_version,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "SAFETY_CASE_VERSION_CONFLICT", "The case changed before assignment.", status_code=409
        )
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=case["subject_user_id"],
        event_type="safety.case.assigned",
        aggregate_type="safety_case",
        aggregate_id=case_id,
        metadata={"assigned_to": str(payload.assigned_to), "assigned_team": payload.assigned_team},
    )
    await _outbox(
        session,
        "safety.case.assigned",
        "safety_case",
        case_id,
        {"assigned_to": str(payload.assigned_to), "version": row["version"]},
    )
    await session.commit()
    return {"id": str(case_id), "status": row["status"], "version": row["version"]}


async def get_case_detail(session: AsyncSession, *, case_id: UUID) -> dict[str, Any]:
    case = (
        (
            await session.execute(
                text(
                    "SELECT id,case_number,case_type,status,priority,subject_user_id,risk_level,primary_category,"
                    "source_manifest,rule_hit_manifest,assigned_team,assigned_to,sla_due_at,current_decision_id,"
                    "created_at,resolved_at,closed_at,version FROM safety_cases WHERE id=:id"
                ),
                {"id": case_id},
            )
        )
        .mappings()
        .first()
    )
    if case is None:
        raise VavError("SAFETY_CASE_NOT_FOUND", "Safety case was not found.", status_code=404)
    evidence = list(
        (
            await session.execute(
                text(
                    "SELECT id,evidence_type,source_module,source_reference_id,evidence_checksum_sha256,"
                    "collection_reason,sensitivity,preservation_status,retention_policy_code,created_at,expires_at "
                    "FROM safety_evidence_items WHERE safety_case_id=:case ORDER BY created_at"
                ),
                {"case": case_id},
            )
        ).mappings()
    )
    tasks = list(
        (
            await session.execute(
                text(
                    "SELECT id,task_type,status,assigned_to,due_at,created_at,completed_at FROM safety_case_tasks WHERE safety_case_id=:case ORDER BY created_at"
                ),
                {"case": case_id},
            )
        ).mappings()
    )
    return {
        **dict(case),
        "id": str(case["id"]),
        "evidence": [dict(item) for item in evidence],
        "tasks": [dict(item) for item in tasks],
    }


async def access_evidence(
    session: AsyncSession,
    *,
    evidence_id: UUID,
    actor: UUID,
    permission_code: str,
    payload: EvidenceAccessRequest,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM safety_evidence_items WHERE id=:id"), {"id": evidence_id}
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("SAFETY_EVIDENCE_NOT_FOUND", "Evidence was not found.", status_code=404)
    if (
        row["sensitivity"] == "highly_restricted"
        and permission_code != "safety.evidence.highly_restricted.read"
    ):
        raise VavError(
            "SAFETY_EVIDENCE_PERMISSION_REQUIRED",
            "Highly restricted evidence requires explicit access.",
            status_code=403,
        )
    await session.execute(
        text(
            "INSERT INTO safety_evidence_access_log (evidence_item_id,actor_user_id,purpose_code,access_type) "
            "VALUES (:evidence,:actor,:purpose,:access)"
        ),
        {
            "evidence": evidence_id,
            "actor": actor,
            "purpose": payload.purpose_code,
            "access": payload.access_type,
        },
    )
    from vav.modules.privacy import service as privacy_service

    await privacy_service.audit(
        session,
        "safety.sensitive_evidence.accessed",
        "safety_evidence",
        evidence_id,
        actor_id=actor,
        reason=payload.purpose_code,
        context={
            "case_id": str(row["safety_case_id"]),
            "permission_code": permission_code,
            "data_scope": row["sensitivity"],
        },
    )
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=None,
        event_type="safety.case.evidence_accessed",
        aggregate_type="safety_evidence_item",
        aggregate_id=evidence_id,
        metadata={
            "case_id": str(row["safety_case_id"]),
            "purpose_code": payload.purpose_code,
            "access_type": payload.access_type,
        },
    )
    await session.commit()
    ciphertext = row["evidence_snapshot_encrypted"]
    if not isinstance(ciphertext, str):
        raise VavError(
            "SAFETY_EVIDENCE_INVALID", "Evidence storage format is invalid.", status_code=409
        )
    return {
        "id": str(evidence_id),
        "case_id": str(row["safety_case_id"]),
        "evidence_type": row["evidence_type"],
        "source_module": row["source_module"],
        "checksum_sha256": row["evidence_checksum_sha256"],
        "snapshot": decrypt_sensitive(ciphertext),
    }


def _validated_restriction_payloads(
    case: dict[str, Any], payload: CaseDecisionRequest
) -> list[RestrictionCreateRequest]:
    if payload.restriction_manifest and case["subject_user_id"] is None:
        raise VavError(
            "SAFETY_CASE_SUBJECT_REQUIRED", "Restrictions require a case subject.", status_code=422
        )
    validated: list[RestrictionCreateRequest] = []
    for item in payload.restriction_manifest:
        candidate = dict(item)
        candidate.update(
            {
                "user_id": case["subject_user_id"],
                "source_type": "case",
                "source_reference_id": case["id"],
                "reason_code": candidate.get("reason_code") or payload.reason_codes[0],
                "appeal_allowed": candidate.get("appeal_allowed", payload.appeal_allowed),
            }
        )
        if "starts_at" not in candidate:
            candidate["starts_at"] = datetime.now(UTC)
        try:
            validated.append(RestrictionCreateRequest.model_validate(candidate))
        except ValueError as exc:
            raise VavError(
                "SAFETY_RESTRICTION_MANIFEST_INVALID",
                "The restriction manifest is invalid.",
                status_code=422,
            ) from exc
    return validated


def _decision_high_impact(decision_type: str, restrictions: list[RestrictionCreateRequest]) -> bool:
    if decision_type in {
        "permanent_disable",
        "underage_enforcement",
        "major_fraud",
        "account_termination",
    }:
        return True
    return any(
        requires_second_approval(
            item.restriction_type.value,
            None
            if item.ends_at is None
            else max(1, int((item.ends_at - item.starts_at).total_seconds() // 3600)),
        )
        for item in restrictions
    )


async def _materialize_decision_restrictions(
    session: AsyncSession,
    *,
    source_case_id: UUID,
    imposed_by: UUID,
    approved_by: UUID | None,
    restrictions: list[RestrictionCreateRequest],
) -> list[str]:
    ids: list[str] = []
    for payload in restrictions:
        restriction_id = (
            await session.execute(
                text(
                    "INSERT INTO account_restrictions (user_id,restriction_type,scope_definition,status,source_type,"
                    "source_reference_id,reason_code,user_message_safe,internal_reason_encrypted,starts_at,ends_at,"
                    "appeal_allowed,imposed_by,approved_by) VALUES (:user,:type,CAST(:scope AS jsonb),'active','case',"
                    ":source,:reason,:message,:internal,:starts,:ends,:appeal,:imposed,:approved) RETURNING id"
                ),
                {
                    "user": payload.user_id,
                    "type": payload.restriction_type.value,
                    "scope": _json(payload.scope_definition),
                    "source": source_case_id,
                    "reason": payload.reason_code,
                    "message": payload.user_message,
                    "internal": encrypt_sensitive({"reason": payload.internal_reason})
                    if payload.internal_reason
                    else None,
                    "starts": payload.starts_at,
                    "ends": payload.ends_at,
                    "appeal": payload.appeal_allowed,
                    "imposed": imposed_by,
                    "approved": approved_by,
                },
            )
        ).scalar_one()
        ids.append(str(restriction_id))
        await _outbox(
            session,
            "safety.restriction.created",
            "account_restriction",
            restriction_id,
            {"user_id": str(payload.user_id), "restriction_type": payload.restriction_type.value},
        )
    return ids


async def create_case_decision(
    session: AsyncSession, *, case_id: UUID, actor: UUID, payload: CaseDecisionRequest
) -> dict[str, Any]:
    conflicted, case = await _case_actor_conflicted(session, case_id=case_id, actor=actor)
    if case is None:
        raise VavError("SAFETY_CASE_NOT_FOUND", "Safety case was not found.", status_code=404)
    if conflicted:
        raise VavError(
            "SAFETY_CASE_CONFLICT",
            "A conflicted investigator cannot decide this case.",
            status_code=409,
        )
    if payload.evidence_item_ids:
        count = int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM safety_evidence_items WHERE safety_case_id=:case AND id=ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"case": case_id, "ids": [str(item) for item in payload.evidence_item_ids]},
                )
            ).scalar_one()
        )
        if count != len(set(payload.evidence_item_ids)):
            raise VavError(
                "SAFETY_DECISION_EVIDENCE_INVALID",
                "Every cited evidence item must belong to the case.",
                status_code=422,
            )
    restrictions = _validated_restriction_payloads(case, payload)
    high_impact = _decision_high_impact(payload.decision_type, restrictions)
    decision_id = (
        await session.execute(
            text(
                "INSERT INTO safety_case_decisions (safety_case_id,decision_type,decision_scope,reason_codes,"
                "evidence_item_ids,user_message_safe,internal_rationale_encrypted,restriction_manifest,decided_by,"
                "appeal_allowed) VALUES (:case,:type,CAST(:scope AS jsonb),CAST(:reasons AS jsonb),CAST(:evidence AS jsonb),"
                ":message,:rationale,CAST(:restrictions AS jsonb),:actor,:appeal) RETURNING id"
            ),
            {
                "case": case_id,
                "type": payload.decision_type,
                "scope": _json(payload.decision_scope),
                "reasons": _json(payload.reason_codes),
                "evidence": _json([str(item) for item in payload.evidence_item_ids]),
                "message": payload.user_message,
                "rationale": encrypt_sensitive({"rationale": payload.internal_rationale}),
                "restrictions": _json([item.model_dump(mode="json") for item in restrictions]),
                "actor": actor,
                "appeal": payload.appeal_allowed,
            },
        )
    ).scalar_one()
    restriction_ids: list[str] = []
    if not high_impact:
        restriction_ids = await _materialize_decision_restrictions(
            session,
            source_case_id=case_id,
            imposed_by=actor,
            approved_by=None,
            restrictions=restrictions,
        )
        await session.execute(
            text(
                "UPDATE safety_cases SET current_decision_id=:decision,status='resolved',resolved_at=now(),version=version+1,updated_at=now() WHERE id=:case"
            ),
            {"decision": decision_id, "case": case_id},
        )
    else:
        await session.execute(
            text(
                "UPDATE safety_cases SET status='pending_action',version=version+1,updated_at=now() WHERE id=:case"
            ),
            {"case": case_id},
        )
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=case["subject_user_id"],
        event_type="safety.case.decision_created",
        aggregate_type="safety_case_decision",
        aggregate_id=decision_id,
        metadata={
            "case_id": str(case_id),
            "high_impact": high_impact,
            "evidence_count": len(payload.evidence_item_ids),
        },
    )
    await session.commit()
    return {
        "id": str(decision_id),
        "case_id": str(case_id),
        "status": "pending_approval" if high_impact else "effective",
        "restriction_ids": restriction_ids,
    }


async def approve_case_decision(
    session: AsyncSession, *, case_id: UUID, decision_id: UUID, approver: UUID
) -> dict[str, Any]:
    conflicted, case = await _case_actor_conflicted(session, case_id=case_id, actor=approver)
    if case is None:
        raise VavError("SAFETY_CASE_NOT_FOUND", "Safety case was not found.", status_code=404)
    if conflicted:
        raise VavError(
            "SAFETY_CASE_CONFLICT",
            "A conflicted reviewer cannot approve this decision.",
            status_code=409,
        )
    decision = (
        (
            await session.execute(
                text(
                    "SELECT * FROM safety_case_decisions WHERE id=:id AND safety_case_id=:case FOR UPDATE"
                ),
                {"id": decision_id, "case": case_id},
            )
        )
        .mappings()
        .first()
    )
    if decision is None:
        raise VavError(
            "SAFETY_CASE_DECISION_NOT_FOUND", "Case decision was not found.", status_code=404
        )
    if decision["decided_by"] == approver:
        raise VavError(
            "SAFETY_FOUR_EYES_REQUIRED",
            "A different administrator must approve this decision.",
            status_code=409,
        )
    if decision["approved_by"] is not None:
        return {
            "id": str(decision_id),
            "case_id": str(case_id),
            "status": "effective",
            "idempotent": True,
        }
    raw_manifest = (
        decision["restriction_manifest"]
        if isinstance(decision["restriction_manifest"], list)
        else []
    )
    decision_payload = CaseDecisionRequest(
        decision_type=decision["decision_type"],
        decision_scope=decision["decision_scope"],
        reason_codes=decision["reason_codes"],
        evidence_item_ids=decision["evidence_item_ids"],
        user_message=decision["user_message_safe"],
        internal_rationale="approved encrypted rationale",
        restriction_manifest=raw_manifest,
        appeal_allowed=decision["appeal_allowed"],
    )
    restrictions = _validated_restriction_payloads(case, decision_payload)
    if not _decision_high_impact(decision["decision_type"], restrictions):
        raise VavError(
            "SAFETY_APPROVAL_NOT_REQUIRED",
            "This decision does not require high-impact approval.",
            status_code=409,
        )
    await session.execute(
        text("UPDATE safety_case_decisions SET approved_by=:actor WHERE id=:id"),
        {"actor": approver, "id": decision_id},
    )
    restriction_ids = await _materialize_decision_restrictions(
        session,
        source_case_id=case_id,
        imposed_by=decision["decided_by"],
        approved_by=approver,
        restrictions=restrictions,
    )
    await session.execute(
        text(
            "UPDATE safety_cases SET current_decision_id=:decision,status='resolved',resolved_at=now(),version=version+1,updated_at=now() WHERE id=:case"
        ),
        {"decision": decision_id, "case": case_id},
    )
    await _audit(
        session,
        actor_user_id=approver,
        subject_user_id=case["subject_user_id"],
        event_type="safety.case.decision_approved",
        aggregate_type="safety_case_decision",
        aggregate_id=decision_id,
        metadata={"case_id": str(case_id)},
    )
    await session.commit()
    return {
        "id": str(decision_id),
        "case_id": str(case_id),
        "status": "effective",
        "restriction_ids": restriction_ids,
    }


async def upsert_behavior_aggregate(
    session: AsyncSession, *, actor: UUID, payload: BehaviorAggregateRequest
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO safety_behavior_aggregates (user_id,metric_code,window_type,window_starts_at,"
                    "window_ends_at,event_count,distinct_target_count,aggregation_version) VALUES "
                    "(:user,:metric,:window,:starts,:ends,:count,:targets,:version) ON CONFLICT "
                    "(user_id,metric_code,window_starts_at) DO UPDATE SET event_count=EXCLUDED.event_count,"
                    "distinct_target_count=EXCLUDED.distinct_target_count,window_ends_at=EXCLUDED.window_ends_at,"
                    "aggregation_version=EXCLUDED.aggregation_version,updated_at=now() RETURNING id,event_count"
                ),
                {
                    "user": payload.user_id,
                    "metric": payload.metric_code,
                    "window": payload.window_type,
                    "starts": payload.window_starts_at,
                    "ends": payload.window_ends_at,
                    "count": payload.event_count,
                    "targets": payload.distinct_target_count,
                    "version": payload.aggregation_version,
                },
            )
        )
        .mappings()
        .one()
    )
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=payload.user_id,
        event_type="safety.behavior.aggregate_updated",
        aggregate_type="safety_behavior_aggregate",
        aggregate_id=row["id"],
        metadata={"metric_code": payload.metric_code, "event_count": payload.event_count},
    )
    await session.commit()
    return {"id": str(row["id"]), "event_count": row["event_count"]}


def _contains_forbidden_signal_data(value: Any) -> bool:
    forbidden = {
        "religion",
        "faith",
        "nationality",
        "race",
        "ethnicity",
        "protected_attribute",
        "counseling",
        "counselling",
        "ai_conversation",
        "private_ai_content",
        "biometric",
        "face_search",
    }
    if isinstance(value, dict):
        return any(
            str(key).casefold() in forbidden or _contains_forbidden_signal_data(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_signal_data(item) for item in value)
    return False


async def create_fraud_signal(
    session: AsyncSession, *, actor: UUID, payload: FraudSignalRequest
) -> dict[str, Any]:
    if _contains_forbidden_signal_data(payload.safe_signal_context):
        raise VavError(
            "SAFETY_PROTECTED_SIGNAL_FORBIDDEN",
            "Protected or private-domain attributes are forbidden safety signals.",
            status_code=422,
        )
    snapshot = {
        "signal_context": payload.safe_signal_context,
        "source_reference_type": payload.source_reference_type,
    }
    try:
        signal_id = (
            await session.execute(
                text(
                    "INSERT INTO fraud_signals (subject_user_id,signal_code,signal_source,severity,confidence_basis_points,"
                    "source_reference_type,source_reference_id,signal_snapshot_encrypted,expires_at) VALUES "
                    "(:user,:code,:source,:severity,:confidence,:reference_type,:reference_id,CAST(:snapshot AS jsonb),:expires) "
                    "RETURNING id"
                ),
                {
                    "user": payload.subject_user_id,
                    "code": payload.signal_code,
                    "source": payload.signal_source,
                    "severity": payload.severity,
                    "confidence": payload.confidence_basis_points,
                    "reference_type": payload.source_reference_type,
                    "reference_id": payload.source_reference_id,
                    "snapshot": _json(encrypt_sensitive(snapshot)),
                    "expires": payload.expires_at,
                },
            )
        ).scalar_one()
    except IntegrityError:
        await session.rollback()
        existing = (
            await session.execute(
                text(
                    "SELECT id FROM fraud_signals WHERE subject_user_id=:user AND signal_code=:code AND signal_source=:source AND source_reference_id IS NOT DISTINCT FROM :reference"
                ),
                {
                    "user": payload.subject_user_id,
                    "code": payload.signal_code,
                    "source": payload.signal_source,
                    "reference": payload.source_reference_id,
                },
            )
        ).scalar_one()
        return {"id": str(existing), "status": "active", "idempotent": True}
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=payload.subject_user_id,
        event_type="safety.fraud.signal_created",
        aggregate_type="fraud_signal",
        aggregate_id=signal_id,
        metadata={"signal_code": payload.signal_code, "severity": payload.severity},
    )
    await session.commit()
    return {"id": str(signal_id), "status": "active", "idempotent": False}


async def create_red_team_run(
    session: AsyncSession, *, actor: UUID, payload: RedTeamRunCreateRequest
) -> dict[str, Any]:
    run_id = (
        await session.execute(
            text(
                "INSERT INTO safety_red_team_runs (run_number,policy_version,fixture_manifest,started_by) VALUES (:number,:policy,CAST(:fixtures AS jsonb),:actor) RETURNING id"
            ),
            {
                "number": _number("RTR"),
                "policy": payload.policy_version,
                "fixtures": _json(payload.fixture_manifest),
                "actor": actor,
            },
        )
    ).scalar_one()
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=None,
        event_type="safety.red_team.run_started",
        aggregate_type="safety_red_team_run",
        aggregate_id=run_id,
        metadata={"policy_version": payload.policy_version},
    )
    await session.commit()
    return {"id": str(run_id), "status": "running"}


async def complete_red_team_run(
    session: AsyncSession, *, run_id: UUID, actor: UUID, payload: RedTeamRunCompleteRequest
) -> dict[str, Any]:
    status = (
        "passed"
        if payload.block_bypass_count == 0 and payload.contact_leakage_count == 0
        else "release_blocked"
    )
    row = (
        (
            await session.execute(
                text(
                    "UPDATE safety_red_team_runs SET status=:status,result_manifest=CAST(:results AS jsonb),block_bypass_count=:blocks,contact_leakage_count=:contacts,completed_by=:actor,completed_at=now() WHERE id=:id AND status='running' RETURNING id"
                ),
                {
                    "status": status,
                    "results": _json(payload.result_manifest),
                    "blocks": payload.block_bypass_count,
                    "contacts": payload.contact_leakage_count,
                    "actor": actor,
                    "id": run_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "SAFETY_RED_TEAM_RUN_INVALID",
            "Red-team run is missing or already complete.",
            status_code=409,
        )
    event = "safety.red_team.run_completed" if status == "passed" else "safety.release.blocked"
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=None,
        event_type=event,
        aggregate_type="safety_red_team_run",
        aggregate_id=run_id,
        metadata={
            "block_bypass_count": payload.block_bypass_count,
            "contact_leakage_count": payload.contact_leakage_count,
        },
    )
    await session.commit()
    return {"id": str(run_id), "status": status}


async def approve_red_team_run(
    session: AsyncSession, *, run_id: UUID, approver: UUID
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM safety_red_team_runs WHERE id=:id FOR UPDATE"), {"id": run_id}
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "SAFETY_RED_TEAM_RUN_NOT_FOUND", "Red-team run was not found.", status_code=404
        )
    if row["status"] != "passed" or row["block_bypass_count"] or row["contact_leakage_count"]:
        raise VavError(
            "SAFETY_RELEASE_GATE_FAILED",
            "A failed or incomplete red-team run cannot be approved.",
            status_code=409,
        )
    if approver in {row["started_by"], row["completed_by"]}:
        raise VavError(
            "SAFETY_FOUR_EYES_REQUIRED",
            "An independent administrator must approve the run.",
            status_code=409,
        )
    await session.execute(
        text("UPDATE safety_red_team_runs SET status='approved',approved_by=:actor WHERE id=:id"),
        {"actor": approver, "id": run_id},
    )
    await _audit(
        session,
        actor_user_id=approver,
        subject_user_id=None,
        event_type="safety.red_team.run_approved",
        aggregate_type="safety_red_team_run",
        aggregate_id=run_id,
        metadata={"policy_version": row["policy_version"]},
    )
    await session.commit()
    return {"id": str(run_id), "status": "approved"}


async def transition_case(
    session: AsyncSession, *, case_id: UUID, actor: UUID, target_status: str
) -> dict[str, Any]:
    conflicted, _ = await _case_actor_conflicted(session, case_id=case_id, actor=actor)
    if conflicted:
        raise VavError(
            "SAFETY_CASE_CONFLICT",
            "A conflicted operator cannot transition this case.",
            status_code=409,
        )
    case = (
        (
            await session.execute(
                text("SELECT * FROM safety_cases WHERE id=:id FOR UPDATE"), {"id": case_id}
            )
        )
        .mappings()
        .first()
    )
    if case is None:
        raise VavError("SAFETY_CASE_NOT_FOUND", "Safety case was not found.", status_code=404)
    try:
        validate_transition(str(case["status"]), target_status, CASE_TRANSITIONS)
    except ValueError as exc:
        raise VavError(
            "SAFETY_CASE_TRANSITION_INVALID",
            "The requested case transition is invalid.",
            status_code=409,
        ) from exc
    timestamps = {
        "resolved": "resolved_at=now(),",
        "closed": "closed_at=now(),",
        "reopened": "resolved_at=NULL,closed_at=NULL,",
    }
    # The status is validated against a fixed transition registry before interpolation.
    query = (
        f"UPDATE safety_cases SET status=:status,{timestamps.get(target_status, '')}"
        "version=version+1,updated_at=now() WHERE id=:id RETURNING version"
    )
    version = (
        await session.execute(text(query), {"status": target_status, "id": case_id})
    ).scalar_one()
    await _audit(
        session,
        actor_user_id=actor,
        subject_user_id=case["subject_user_id"],
        event_type="safety.case.transitioned",
        aggregate_type="safety_case",
        aggregate_id=case_id,
        metadata={"from": case["status"], "to": target_status},
    )
    await session.commit()
    return {"id": str(case_id), "status": target_status, "version": version}


async def admin_queue(session: AsyncSession, table: str) -> list[dict[str, Any]]:
    allowed = {
        "reports": (
            "SELECT id,report_number,status,category,immediate_danger_claimed,submitted_at "
            "FROM safety_reports ORDER BY immediate_danger_claimed DESC,submitted_at LIMIT 200"
        ),
        "cases": (
            "SELECT id,case_number,status,priority,risk_level,primary_category,assigned_to,sla_due_at "
            "FROM safety_cases ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 "
            "WHEN 'high' THEN 2 ELSE 3 END,sla_due_at LIMIT 200"
        ),
        "moderation": (
            "SELECT id,target_type,target_reference_id,target_version,status,priority,policy_version,created_at "
            "FROM moderation_tasks ORDER BY priority DESC,created_at LIMIT 200"
        ),
        "restrictions": (
            "SELECT id,user_id,restriction_type,status,reason_code,starts_at,ends_at,appeal_allowed,version "
            "FROM account_restrictions ORDER BY created_at DESC LIMIT 200"
        ),
        "appeals": (
            "SELECT id,appeal_number,appellant_user_id,restriction_id,status,outcome,submitted_at,review_due_at "
            "FROM safety_appeals ORDER BY review_due_at NULLS LAST LIMIT 200"
        ),
        "rules": (
            "SELECT id,rule_code,semantic_version,category,rule_type,severity,status,rollout_basis_points "
            "FROM safety_risk_rules ORDER BY rule_code,created_at DESC LIMIT 200"
        ),
        "harassment": (
            "SELECT id,user_id,metric_code,window_type,event_count,distinct_target_count,"
            "aggregation_version,window_starts_at,window_ends_at,updated_at "
            "FROM safety_behavior_aggregates ORDER BY updated_at DESC LIMIT 200"
        ),
        "fraud": (
            "SELECT id,subject_user_id,signal_code,signal_source,severity,confidence_basis_points,"
            "source_reference_type,source_reference_id,status,detected_at,expires_at "
            "FROM fraud_signals ORDER BY detected_at DESC LIMIT 200"
        ),
        "red-team": (
            "SELECT id,run_number,policy_version,status,block_bypass_count,contact_leakage_count,"
            "started_by,completed_by,approved_by,started_at,completed_at "
            "FROM safety_red_team_runs ORDER BY started_at DESC LIMIT 200"
        ),
        "audit": (
            "SELECT id,actor_user_id,subject_user_id,event_type,aggregate_type,aggregate_id,"
            "safe_metadata,request_id,created_at FROM safety_audit_events "
            "ORDER BY created_at DESC LIMIT 500"
        ),
    }
    if table not in allowed:
        raise VavError("SAFETY_QUEUE_INVALID", "Unknown safety queue.", status_code=404)
    rows = (await session.execute(text(allowed[table]))).mappings()
    return [dict(row) for row in rows]


async def expire_restrictions(session: AsyncSession) -> int:
    rows = list(
        (
            await session.execute(
                text(
                    "UPDATE account_restrictions SET status='expired',version=version+1,updated_at=now() "
                    "WHERE status='active' AND ends_at IS NOT NULL AND ends_at<=now() "
                    "AND restriction_type<>'account_permanently_disabled' RETURNING id,user_id,restriction_type,version"
                )
            )
        ).mappings()
    )
    for row in rows:
        await _outbox(
            session,
            "safety.restriction.expired",
            "account_restriction",
            row["id"],
            {
                "user_id": str(row["user_id"]),
                "restriction_type": row["restriction_type"],
                "version": row["version"],
            },
        )
    await session.commit()
    return len(rows)


async def escalate_overdue_cases(session: AsyncSession) -> int:
    rows = list(
        (
            await session.execute(
                text(
                    "UPDATE safety_cases SET priority=CASE priority WHEN 'low' THEN 'normal' "
                    "WHEN 'normal' THEN 'high' WHEN 'high' THEN 'urgent' ELSE priority END,"
                    "version=version+1,updated_at=now() WHERE status NOT IN ('resolved','closed') "
                    "AND sla_due_at<=now() RETURNING id,priority"
                )
            )
        ).mappings()
    )
    for row in rows:
        await _outbox(
            session,
            "safety.case.escalated",
            "safety_case",
            row["id"],
            {"priority": row["priority"], "sla_breached": True},
        )
    await session.commit()
    return len(rows)
