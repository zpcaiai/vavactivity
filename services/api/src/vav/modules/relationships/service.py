"""Transactional relationship journey service.

All member writes lock the journey row. This makes a stage decision, pause,
resume or ending a single serial transition even when two devices submit at
the same time. Private text is encrypted and never placed in history/outbox.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.privacy.crypto import decrypt_private, encrypt_private
from vav.modules.relationships.domain import (
    JourneyStatus,
    PauseStatus,
    StageProposalStatus,
    other_participant,
    validate_transition,
)


def enabled() -> None:
    if not get_settings().relationship_journeys_enabled:
        raise VavError(
            "RELATIONSHIP_JOURNEYS_DISABLED",
            "Relationship journeys are not enabled.",
            status_code=503,
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _member_safe(row: dict[str, Any], actor_id: UUID) -> dict[str, Any]:
    partner = other_participant(
        user_low_id=row["user_low_id"], user_high_id=row["user_high_id"], actor_id=actor_id
    )
    return {
        "journey_id": str(row["id"]),
        "journey_number": row["journey_number"],
        "partner_user_id": str(partner),
        "status": row["status"],
        "current_stage_code": row["current_stage_code"],
        "started_at": row["started_at"],
        "paused_at": row["paused_at"],
        "ended_at": row["ended_at"],
        "version": row["version"],
    }


async def _publish(
    session: AsyncSession, topic: str, aggregate_id: UUID, payload: dict[str, Any]
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) VALUES (:topic,'relationship_journey',:id,CAST(:payload AS jsonb))"
        ),
        {"topic": topic, "id": str(aggregate_id), "payload": _json(payload)},
    )


async def _history(
    session: AsyncSession,
    *,
    journey_id: UUID,
    event_type: str,
    actor_id: UUID | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    from_stage: str | None = None,
    to_stage: str | None = None,
    reason_code: str | None = None,
    source_event_id: UUID | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO relationship_status_history (journey_id,actor_user_id,event_type,from_status,to_status,from_stage_code,to_stage_code,reason_code,source_event_id) VALUES (:journey,:actor,:event,:from_status,:to_status,:from_stage,:to_stage,:reason,:source)"
        ),
        {
            "journey": journey_id,
            "actor": actor_id,
            "event": event_type,
            "from_status": from_status,
            "to_status": to_status,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "reason": reason_code,
            "source": source_event_id,
        },
    )


async def create_from_handoff(
    session: AsyncSession,
    *,
    relationship_handoff_id: UUID,
    mutual_match_id: UUID,
    invitation_id: UUID,
    pair_id: UUID,
    user_low_id: UUID,
    user_high_id: UUID,
) -> dict[str, Any]:
    """Materialise the Batch 15 handoff once, inside its acceptance transaction."""
    enabled()
    journey_id = uuid4()
    number = f"RJ-{datetime.now(UTC):%Y%m%d}-{str(journey_id)[:8].upper()}"
    inserted = (
        (
            await session.execute(
                text(
                    "INSERT INTO relationship_journeys (id,journey_number,matchmaking_pair_id,mutual_match_id,introduction_invitation_id,relationship_handoff_id,user_low_id,user_high_id,status,current_stage_code,stage_registry_version,policy_version) VALUES (:id,:number,:pair,:match,:invitation,:handoff,:low,:high,'active','introduction_accepted',:registry,:policy) ON CONFLICT (relationship_handoff_id) DO NOTHING RETURNING *"
                ),
                {
                    "id": journey_id,
                    "number": number,
                    "pair": pair_id,
                    "match": mutual_match_id,
                    "invitation": invitation_id,
                    "handoff": relationship_handoff_id,
                    "low": user_low_id,
                    "high": user_high_id,
                    "registry": get_settings().relationship_default_stage_registry,
                    "policy": get_settings().relationship_default_policy_version,
                },
            )
        )
        .mappings()
        .first()
    )
    if inserted is None:
        inserted = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM relationship_journeys WHERE relationship_handoff_id=:handoff"
                    ),
                    {"handoff": relationship_handoff_id},
                )
            )
            .mappings()
            .one()
        )
        return dict(inserted)
    journey = dict(inserted)
    for user_id in (user_low_id, user_high_id):
        await session.execute(
            text(
                "INSERT INTO relationship_participants (journey_id,user_id) VALUES (:journey,:user) ON CONFLICT DO NOTHING"
            ),
            {"journey": journey_id, "user": user_id},
        )
    await _history(
        session,
        journey_id=journey_id,
        event_type="journey_created",
        to_status="active",
        to_stage="introduction_accepted",
        source_event_id=relationship_handoff_id,
    )
    await _publish(
        session,
        "relationships.journey.created",
        journey_id,
        {
            "journey_id": str(journey_id),
            "recipient_user_ids": [str(user_low_id), str(user_high_id)],
        },
    )
    return journey


async def ingest_handoff(
    session: AsyncSession, *, source_event_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Public idempotent inbox entry for replayable outbox consumers."""
    await session.execute(
        text(
            "INSERT INTO relationship_inbox_events (source_module,source_event_id,event_type,payload) VALUES ('matchmaking_interactions',:id,'matchmaking.relationship_handoff.created',CAST(:payload AS jsonb)) ON CONFLICT (source_module,source_event_id) DO NOTHING"
        ),
        {"id": source_event_id, "payload": _json(payload)},
    )
    journey = await create_from_handoff(
        session,
        relationship_handoff_id=UUID(payload["relationship_handoff_id"]),
        mutual_match_id=UUID(payload["mutual_match_id"]),
        invitation_id=UUID(payload["invitation_id"]),
        pair_id=UUID(payload["pair_id"]),
        user_low_id=UUID(payload["user_low_id"]),
        user_high_id=UUID(payload["user_high_id"]),
    )
    await session.execute(
        text(
            "UPDATE relationship_inbox_events SET status='processed',processed_at=now() WHERE source_module='matchmaking_interactions' AND source_event_id=:id"
        ),
        {"id": source_event_id},
    )
    return journey


async def _journey(
    session: AsyncSession, journey_id: UUID, actor_id: UUID, *, lock: bool = False
) -> dict[str, Any]:
    enabled()
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM relationship_journeys WHERE id=:id AND :actor IN (user_low_id,user_high_id)"
                    + suffix
                ),
                {"id": journey_id, "actor": actor_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "RELATIONSHIP_NOT_FOUND", "That relationship journey was not found.", status_code=404
        )
    return dict(row)


async def list_journeys(session: AsyncSession, actor_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT * FROM relationship_journeys WHERE :actor IN (user_low_id,user_high_id) ORDER BY updated_at DESC"
            ),
            {"actor": actor_id},
        )
    ).mappings()
    return [_member_safe(dict(row), actor_id) for row in rows]


async def get_journey(session: AsyncSession, journey_id: UUID, actor_id: UUID) -> dict[str, Any]:
    return _member_safe(await _journey(session, journey_id, actor_id), actor_id)


async def create_stage_proposal(
    session: AsyncSession,
    *,
    journey_id: UUID,
    actor_id: UUID,
    to_stage: str,
    message: str | None,
    idempotency_key: str,
) -> dict[str, Any]:
    journey = await _journey(session, journey_id, actor_id, lock=True)
    if journey["status"] != JourneyStatus.ACTIVE.value:
        raise VavError(
            "RELATIONSHIP_NOT_ACTIVE", "Stage changes require an active journey.", status_code=409
        )
    try:
        validate_transition(
            journey["current_stage_code"],
            to_stage,
            allow_skip=get_settings().relationship_allow_stage_skip_forward,
        )
    except ValueError as exc:
        raise VavError("RELATIONSHIP_STAGE_INVALID", str(exc), status_code=422) from exc
    recipient = other_participant(
        user_low_id=journey["user_low_id"], user_high_id=journey["user_high_id"], actor_id=actor_id
    )
    proposal_id = uuid4()
    try:
        row = (
            (
                await session.execute(
                    text(
                        "INSERT INTO relationship_stage_proposals (id,journey_id,proposer_user_id,recipient_user_id,from_stage_code,to_stage_code,message_encrypted,policy_snapshot,idempotency_key,expires_at) VALUES (:id,:journey,:proposer,:recipient,:from_stage,:to_stage,:message,CAST(:policy AS jsonb),:key,:expires) ON CONFLICT (proposer_user_id,idempotency_key) DO UPDATE SET updated_at=relationship_stage_proposals.updated_at RETURNING *"
                    ),
                    {
                        "id": proposal_id,
                        "journey": journey_id,
                        "proposer": actor_id,
                        "recipient": recipient,
                        "from_stage": journey["current_stage_code"],
                        "to_stage": to_stage,
                        "message": encrypt_private(message) if message else None,
                        "policy": _json(
                            {
                                "mutual_confirmation": True,
                                "policy_version": journey["policy_version"],
                            }
                        ),
                        "key": idempotency_key,
                        "expires": datetime.now(UTC)
                        + timedelta(days=get_settings().relationship_stage_proposal_ttl_days),
                    },
                )
            )
            .mappings()
            .one()
        )
    except IntegrityError as exc:
        raise VavError(
            "RELATIONSHIP_STAGE_PROPOSAL_PENDING",
            "A stage proposal is already awaiting a response.",
            status_code=409,
        ) from exc
    await _history(
        session,
        journey_id=journey_id,
        actor_id=actor_id,
        event_type="stage_proposed",
        from_stage=journey["current_stage_code"],
        to_stage=to_stage,
    )
    await _publish(
        session,
        "relationships.stage.proposed",
        journey_id,
        {
            "journey_id": str(journey_id),
            "proposal_id": str(row["id"]),
            "recipient_user_ids": [str(recipient)],
        },
    )
    return {
        "proposal_id": str(row["id"]),
        "status": row["status"],
        "from_stage_code": row["from_stage_code"],
        "to_stage_code": row["to_stage_code"],
        "expires_at": row["expires_at"],
        "version": row["version"],
    }


async def list_stage_proposals(
    session: AsyncSession, journey_id: UUID, actor_id: UUID
) -> list[dict[str, Any]]:
    await _journey(session, journey_id, actor_id)
    rows = (
        await session.execute(
            text(
                "SELECT id,proposer_user_id,recipient_user_id,from_stage_code,to_stage_code,status,proposed_at,expires_at,version FROM relationship_stage_proposals WHERE journey_id=:journey ORDER BY proposed_at DESC"
            ),
            {"journey": journey_id},
        )
    ).mappings()
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "proposer_user_id": str(row["proposer_user_id"]),
            "recipient_user_id": str(row["recipient_user_id"]),
        }
        for row in rows
    ]


async def decide_stage_proposal(
    session: AsyncSession,
    *,
    proposal_id: UUID,
    actor_id: UUID,
    accept: bool,
    expected_version: int | None = None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    proposal = (
        (
            await session.execute(
                text(
                    "SELECT p.*,j.status AS journey_status,j.current_stage_code FROM relationship_stage_proposals p JOIN relationship_journeys j ON j.id=p.journey_id WHERE p.id=:id FOR UPDATE OF p,j"
                ),
                {"id": proposal_id},
            )
        )
        .mappings()
        .first()
    )
    if proposal is None or proposal["recipient_user_id"] != actor_id:
        raise VavError(
            "RELATIONSHIP_PROPOSAL_NOT_FOUND", "That proposal was not found.", status_code=404
        )
    if proposal["status"] != StageProposalStatus.PENDING.value or (
        expected_version is not None and proposal["version"] != expected_version
    ):
        raise VavError(
            "RELATIONSHIP_PROPOSAL_STATE_CHANGED",
            "That proposal is no longer pending.",
            status_code=409,
        )
    if proposal["expires_at"] <= datetime.now(UTC):
        await session.execute(
            text(
                "UPDATE relationship_stage_proposals SET status='expired',version=version+1,updated_at=now() WHERE id=:id"
            ),
            {"id": proposal_id},
        )
        raise VavError(
            "RELATIONSHIP_PROPOSAL_EXPIRED", "That proposal has expired.", status_code=409
        )
    if (
        proposal["journey_status"] != JourneyStatus.ACTIVE.value
        or proposal["current_stage_code"] != proposal["from_stage_code"]
    ):
        await session.execute(
            text(
                "UPDATE relationship_stage_proposals SET status='invalidated',invalidated_at=now(),version=version+1,updated_at=now() WHERE id=:id"
            ),
            {"id": proposal_id},
        )
        raise VavError(
            "RELATIONSHIP_PROPOSAL_STATE_CHANGED",
            "The relationship state changed.",
            status_code=409,
        )
    status = "accepted" if accept else "declined"
    timestamp = "accepted_at" if accept else "declined_at"
    await session.execute(
        text(
            f"UPDATE relationship_stage_proposals SET status=:status,{timestamp}=now(),decline_reason_code=:reason,version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"id": proposal_id, "status": status, "reason": reason_code},
    )
    if accept:
        await session.execute(
            text(
                "UPDATE relationship_journeys SET current_stage_code=:stage,version=version+1,updated_at=now() WHERE id=:id"
            ),
            {"id": proposal["journey_id"], "stage": proposal["to_stage_code"]},
        )
    await _history(
        session,
        journey_id=proposal["journey_id"],
        actor_id=actor_id,
        event_type=f"stage_proposal_{status}",
        from_stage=proposal["from_stage_code"],
        to_stage=proposal["to_stage_code"] if accept else proposal["from_stage_code"],
        reason_code=reason_code,
    )
    await _publish(
        session,
        f"relationships.stage.{status}",
        proposal["journey_id"],
        {
            "journey_id": str(proposal["journey_id"]),
            "proposal_id": str(proposal_id),
            "recipient_user_ids": [str(proposal["proposer_user_id"])],
        },
    )
    return {
        "proposal_id": str(proposal_id),
        "status": status,
        "current_stage_code": proposal["to_stage_code"] if accept else proposal["from_stage_code"],
    }


async def cancel_stage_proposal(
    session: AsyncSession, *, proposal_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    proposal = (
        (
            await session.execute(
                text("SELECT * FROM relationship_stage_proposals WHERE id=:id FOR UPDATE"),
                {"id": proposal_id},
            )
        )
        .mappings()
        .first()
    )
    if proposal is None or proposal["proposer_user_id"] != actor_id:
        raise VavError(
            "RELATIONSHIP_PROPOSAL_NOT_FOUND", "That proposal was not found.", status_code=404
        )
    if proposal["status"] != "pending":
        raise VavError(
            "RELATIONSHIP_PROPOSAL_STATE_CHANGED",
            "That proposal is no longer pending.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE relationship_stage_proposals SET status='cancelled',cancelled_at=now(),version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"id": proposal_id},
    )
    await _history(
        session,
        journey_id=proposal["journey_id"],
        actor_id=actor_id,
        event_type="stage_proposal_cancelled",
    )
    return {"proposal_id": str(proposal_id), "status": "cancelled"}


async def pause(
    session: AsyncSession,
    *,
    journey_id: UUID,
    actor_id: UUID,
    private_reason: str | None,
    visible_message: str | None,
) -> dict[str, Any]:
    journey = await _journey(session, journey_id, actor_id, lock=True)
    if journey["status"] not in (JourneyStatus.ACTIVE.value, JourneyStatus.SAFETY_FROZEN.value):
        raise VavError(
            "RELATIONSHIP_PAUSE_INVALID",
            "This journey cannot be paused from its current state.",
            status_code=409,
        )
    pause_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO relationship_pauses (id,journey_id,initiated_by_user_id,private_reason_encrypted,user_visible_message_encrypted,policy_snapshot) VALUES (:id,:journey,:actor,:private,:visible,CAST(:policy AS jsonb))"
        ),
        {
            "id": pause_id,
            "journey": journey_id,
            "actor": actor_id,
            "private": encrypt_private(private_reason) if private_reason else None,
            "visible": encrypt_private(visible_message) if visible_message else None,
            "policy": _json({"immediate": True, "resume_requires_mutual_confirmation": True}),
        },
    )
    await session.execute(
        text(
            "UPDATE relationship_journeys SET status='paused',paused_at=now(),current_pause_id=:pause,version=version+1,updated_at=now() WHERE id=:journey"
        ),
        {"journey": journey_id, "pause": pause_id},
    )
    await session.execute(
        text(
            "UPDATE relationship_stage_proposals SET status='invalidated',invalidated_at=now(),version=version+1,updated_at=now() WHERE journey_id=:journey AND status='pending'"
        ),
        {"journey": journey_id},
    )
    await _history(
        session,
        journey_id=journey_id,
        actor_id=actor_id,
        event_type="journey_paused",
        from_status=journey["status"],
        to_status="paused",
    )
    partner = other_participant(
        user_low_id=journey["user_low_id"], user_high_id=journey["user_high_id"], actor_id=actor_id
    )
    await _publish(
        session,
        "relationships.journey.paused",
        journey_id,
        {
            "journey_id": str(journey_id),
            "pause_id": str(pause_id),
            "recipient_user_ids": [str(partner)],
        },
    )
    return {"journey_id": str(journey_id), "pause_id": str(pause_id), "status": "paused"}


async def request_resume(
    session: AsyncSession, *, journey_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    journey = await _journey(session, journey_id, actor_id, lock=True)
    if journey["status"] != "paused" or journey["current_pause_id"] is None:
        raise VavError(
            "RELATIONSHIP_RESUME_INVALID", "This journey is not paused.", status_code=409
        )
    pause_row = (
        (
            await session.execute(
                text("SELECT * FROM relationship_pauses WHERE id=:id FOR UPDATE"),
                {"id": journey["current_pause_id"]},
            )
        )
        .mappings()
        .one()
    )
    if pause_row["status"] != PauseStatus.ACTIVE.value:
        raise VavError(
            "RELATIONSHIP_RESUME_STATE_CHANGED", "A resume request already exists.", status_code=409
        )
    await session.execute(
        text(
            "UPDATE relationship_pauses SET status='resume_requested',resume_requested_by_user_id=:actor,resume_requested_at=now(),version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"id": pause_row["id"], "actor": actor_id},
    )
    partner = other_participant(
        user_low_id=journey["user_low_id"], user_high_id=journey["user_high_id"], actor_id=actor_id
    )
    await _publish(
        session,
        "relationships.resume.requested",
        journey_id,
        {
            "journey_id": str(journey_id),
            "pause_id": str(pause_row["id"]),
            "recipient_user_ids": [str(partner)],
        },
    )
    return {"pause_id": str(pause_row["id"]), "status": "resume_requested"}


async def decide_resume(
    session: AsyncSession,
    *,
    pause_id: UUID,
    actor_id: UUID,
    accept: bool,
    expected_version: int | None = None,
) -> dict[str, Any]:
    pause_row = (
        (
            await session.execute(
                text(
                    "SELECT p.*,j.user_low_id,j.user_high_id,j.status AS journey_status FROM relationship_pauses p JOIN relationship_journeys j ON j.id=p.journey_id WHERE p.id=:id FOR UPDATE OF p,j"
                ),
                {"id": pause_id},
            )
        )
        .mappings()
        .first()
    )
    if pause_row is None or actor_id not in (pause_row["user_low_id"], pause_row["user_high_id"]):
        raise VavError("RELATIONSHIP_PAUSE_NOT_FOUND", "That pause was not found.", status_code=404)
    if pause_row["resume_requested_by_user_id"] == actor_id:
        raise VavError(
            "RELATIONSHIP_RESUME_REQUIRES_PARTNER",
            "The other participant must decide the resume request.",
            status_code=403,
        )
    if pause_row["status"] != "resume_requested" or (
        expected_version is not None and pause_row["version"] != expected_version
    ):
        raise VavError(
            "RELATIONSHIP_RESUME_STATE_CHANGED",
            "That resume request is no longer pending.",
            status_code=409,
        )
    if accept:
        await session.execute(
            text(
                "UPDATE relationship_pauses SET status='resumed',resume_accepted_by_user_id=:actor,resumed_at=now(),version=version+1,updated_at=now() WHERE id=:id"
            ),
            {"id": pause_id, "actor": actor_id},
        )
        await session.execute(
            text(
                "UPDATE relationship_journeys SET status='active',paused_at=NULL,current_pause_id=NULL,version=version+1,updated_at=now() WHERE id=:id"
            ),
            {"id": pause_row["journey_id"]},
        )
        await _history(
            session,
            journey_id=pause_row["journey_id"],
            actor_id=actor_id,
            event_type="journey_resumed",
            from_status="paused",
            to_status="active",
        )
        return {"pause_id": str(pause_id), "status": "resumed"}
    await session.execute(
        text(
            "UPDATE relationship_pauses SET status='active',resume_requested_by_user_id=NULL,resume_requested_at=NULL,version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"id": pause_id},
    )
    return {"pause_id": str(pause_id), "status": "active"}


async def end_journey(
    session: AsyncSession,
    *,
    journey_id: UUID,
    actor_id: UUID,
    confirmed: bool,
    reason_code: str | None,
    private_reason: str | None,
    visible_message: str | None,
    ending_type: str = "member_ended",
    authorize_participant: bool = True,
) -> dict[str, Any]:
    if not confirmed:
        raise VavError(
            "RELATIONSHIP_END_CONFIRMATION_REQUIRED",
            "Ending must be explicitly confirmed.",
            status_code=422,
        )
    if authorize_participant:
        journey = await _journey(session, journey_id, actor_id, lock=True)
    else:
        found = (
            (
                await session.execute(
                    text("SELECT * FROM relationship_journeys WHERE id=:id FOR UPDATE"),
                    {"id": journey_id},
                )
            )
            .mappings()
            .first()
        )
        if found is None:
            raise VavError(
                "RELATIONSHIP_NOT_FOUND",
                "That relationship journey was not found.",
                status_code=404,
            )
        journey = dict(found)
    if journey["status"] in ("ended", "archived", "deletion_pending"):
        raise VavError(
            "RELATIONSHIP_ALREADY_ENDED",
            "This relationship journey has already ended.",
            status_code=409,
        )
    ending_id = uuid4()
    effects = {
        "stage_proposals_cancelled": True,
        "reminders_cancelled": True,
        "contact_access_revoked": get_settings().relationship_end_contact_access_on_end,
        "pair_cooldown_days": get_settings().relationship_ended_pair_cooldown_days,
    }
    await session.execute(
        text(
            "INSERT INTO relationship_endings (id,journey_id,ended_by_user_id,status,ending_type,reason_code,private_reason_encrypted,user_visible_message_encrypted,policy_snapshot,downstream_effects,processing_started_at,completed_at) VALUES (:id,:journey,:actor,'completed',:type,:reason,:private,:visible,CAST(:policy AS jsonb),CAST(:effects AS jsonb),now(),now())"
        ),
        {
            "id": ending_id,
            "journey": journey_id,
            "actor": actor_id,
            "type": ending_type,
            "reason": reason_code,
            "private": encrypt_private(private_reason) if private_reason else None,
            "visible": encrypt_private(visible_message) if visible_message else None,
            "policy": _json({"other_party_approval": False, "confirmation_required": True}),
            "effects": _json(effects),
        },
    )
    await session.execute(
        text(
            "UPDATE relationship_journeys SET status='ended',ended_at=now(),ending_record_id=:ending,current_pause_id=NULL,version=version+1,updated_at=now() WHERE id=:journey"
        ),
        {"journey": journey_id, "ending": ending_id},
    )
    await session.execute(
        text(
            "UPDATE relationship_stage_proposals SET status='invalidated',invalidated_at=now(),version=version+1,updated_at=now() WHERE journey_id=:journey AND status='pending'"
        ),
        {"journey": journey_id},
    )
    await session.execute(
        text(
            "UPDATE relationship_pauses SET status='ended',ended_at=now(),version=version+1,updated_at=now() WHERE journey_id=:journey AND status IN ('active','resume_requested')"
        ),
        {"journey": journey_id},
    )
    await session.execute(
        text(
            "UPDATE relationship_reminder_plans SET status='cancelled',updated_at=now() WHERE journey_id=:journey AND status='active'"
        ),
        {"journey": journey_id},
    )
    await session.execute(
        text(
            "UPDATE matchmaking_contact_exchange_grants g SET status='revoked',revoked_at=now(),revoke_reason='relationship_ended' FROM matchmaking_contact_exchange_requests r WHERE g.contact_exchange_request_id=r.id AND r.pair_id=:pair AND g.status='active'"
        ),
        {"pair": journey["matchmaking_pair_id"]},
    )
    await session.execute(
        text(
            "UPDATE matchmaking_mutual_matches SET status='closed',closed_at=now(),closure_reason_code='relationship_ended',match_version=match_version+1,updated_at=now() WHERE id=:match"
        ),
        {"match": journey["mutual_match_id"]},
    )
    await session.execute(
        text(
            "INSERT INTO matchmaking_pair_cooldowns (pair_id,cooldown_type,reason_code,expires_at) VALUES (:pair,'relationship_ended','relationship_ended',now()+make_interval(days => :days)) ON CONFLICT DO NOTHING"
        ),
        {
            "pair": journey["matchmaking_pair_id"],
            "days": get_settings().relationship_ended_pair_cooldown_days,
        },
    )
    await _history(
        session,
        journey_id=journey_id,
        actor_id=actor_id,
        event_type="journey_ended",
        from_status=journey["status"],
        to_status="ended",
        reason_code=reason_code,
    )
    recipients = [str(journey["user_low_id"]), str(journey["user_high_id"])]
    if authorize_participant:
        recipients = [
            str(
                other_participant(
                    user_low_id=journey["user_low_id"],
                    user_high_id=journey["user_high_id"],
                    actor_id=actor_id,
                )
            )
        ]
    await _publish(
        session,
        "relationships.journey.ended",
        journey_id,
        {
            "journey_id": str(journey_id),
            "ending_id": str(ending_id),
            "recipient_user_ids": recipients,
            "effects": effects,
        },
    )
    return {
        "journey_id": str(journey_id),
        "ending_id": str(ending_id),
        "status": "ended",
        "downstream_effects": effects,
    }


async def timeline(session: AsyncSession, journey_id: UUID, actor_id: UUID) -> list[dict[str, Any]]:
    await _journey(session, journey_id, actor_id)
    rows = (
        await session.execute(
            text(
                "SELECT id,event_type,from_status,to_status,from_stage_code,to_stage_code,occurred_at FROM relationship_status_history WHERE journey_id=:journey ORDER BY occurred_at,id"
            ),
            {"journey": journey_id},
        )
    ).mappings()
    return [{**dict(row), "id": str(row["id"])} for row in rows]


async def create_milestone(
    session: AsyncSession,
    *,
    journey_id: UUID,
    actor_id: UUID,
    milestone_type: str,
    title: str,
    description: str | None,
    visibility: str,
    occurred_on: Any,
) -> dict[str, Any]:
    await _journey(session, journey_id, actor_id)
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO relationship_milestones (journey_id,created_by_user_id,milestone_type,title,description_encrypted,visibility,occurred_on) VALUES (:journey,:actor,:type,:title,:description,:visibility,:occurred) RETURNING *"
                ),
                {
                    "journey": journey_id,
                    "actor": actor_id,
                    "type": milestone_type,
                    "title": title,
                    "description": encrypt_private(description) if description else None,
                    "visibility": visibility,
                    "occurred": occurred_on,
                },
            )
        )
        .mappings()
        .one()
    )
    await _history(
        session, journey_id=journey_id, actor_id=actor_id, event_type="milestone_created"
    )
    return {
        "milestone_id": str(row["id"]),
        "title": row["title"],
        "visibility": row["visibility"],
        "occurred_on": row["occurred_on"],
        "version": row["version"],
    }


async def update_milestone(
    session: AsyncSession, *, milestone_id: UUID, actor_id: UUID, values: dict[str, Any]
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT m.*,j.user_low_id,j.user_high_id FROM relationship_milestones m JOIN relationship_journeys j ON j.id=m.journey_id WHERE m.id=:id FOR UPDATE"
                ),
                {"id": milestone_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["created_by_user_id"] != actor_id:
        raise VavError(
            "RELATIONSHIP_MILESTONE_NOT_FOUND", "That milestone was not found.", status_code=404
        )
    expected = values.pop("expected_version", None)
    if expected is not None and row["version"] != expected:
        raise VavError(
            "RELATIONSHIP_MILESTONE_STATE_CHANGED", "That milestone changed.", status_code=409
        )
    title = values.get("title") or row["title"]
    visibility = values.get("visibility") or row["visibility"]
    description = (
        encrypt_private(values["description"])
        if values.get("description") is not None
        else row["description_encrypted"]
    )
    occurred = (
        values.get("occurred_on")
        if "occurred_on" in values and values["occurred_on"] is not None
        else row["occurred_on"]
    )
    updated = (
        (
            await session.execute(
                text(
                    "UPDATE relationship_milestones SET title=:title,visibility=:visibility,description_encrypted=:description,occurred_on=:occurred,version=version+1,updated_at=now() WHERE id=:id RETURNING id,title,visibility,occurred_on,version"
                ),
                {
                    "id": milestone_id,
                    "title": title,
                    "visibility": visibility,
                    "description": description,
                    "occurred": occurred,
                },
            )
        )
        .mappings()
        .one()
    )
    return {**dict(updated), "id": str(updated["id"])}


async def delete_milestone(
    session: AsyncSession, *, milestone_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    result = await session.execute(
        text(
            "UPDATE relationship_milestones SET status='deleted',deleted_at=now(),version=version+1,updated_at=now() WHERE id=:id AND created_by_user_id=:actor AND status='active' RETURNING journey_id"
        ),
        {"id": milestone_id, "actor": actor_id},
    )
    row = result.mappings().first()
    if row is None:
        raise VavError(
            "RELATIONSHIP_MILESTONE_NOT_FOUND", "That milestone was not found.", status_code=404
        )
    await _history(
        session, journey_id=row["journey_id"], actor_id=actor_id, event_type="milestone_deleted"
    )
    return {"milestone_id": str(milestone_id), "status": "deleted"}


async def list_milestones(
    session: AsyncSession, journey_id: UUID, actor_id: UUID
) -> list[dict[str, Any]]:
    await _journey(session, journey_id, actor_id)
    rows = (
        await session.execute(
            text(
                "SELECT id,created_by_user_id,milestone_type,title,description_encrypted,visibility,occurred_on,created_at,version FROM relationship_milestones WHERE journey_id=:journey AND status='active' AND (visibility='shared' OR created_by_user_id=:actor) ORDER BY COALESCE(occurred_on,created_at::date),created_at"
            ),
            {"journey": journey_id, "actor": actor_id},
        )
    ).mappings()
    return [
        {
            "milestone_id": str(row["id"]),
            "created_by_user_id": str(row["created_by_user_id"]),
            "milestone_type": row["milestone_type"],
            "title": row["title"],
            "description": decrypt_private(row["description_encrypted"])
            if row["description_encrypted"]
            else None,
            "visibility": row["visibility"],
            "occurred_on": row["occurred_on"],
            "created_at": row["created_at"],
            "version": row["version"],
        }
        for row in rows
    ]


async def create_checkin(
    session: AsyncSession,
    *,
    journey_id: UUID,
    actor_id: UUID,
    visibility: str,
    responses: dict[str, Any],
) -> dict[str, Any]:
    await _journey(session, journey_id, actor_id)
    checkin = (
        await session.execute(
            text(
                "INSERT INTO relationship_checkins (journey_id,initiated_by_user_id,visibility,status,completed_at) VALUES (:journey,:actor,:visibility,'completed',now()) RETURNING id"
            ),
            {"journey": journey_id, "actor": actor_id, "visibility": visibility},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO relationship_checkin_responses (checkin_id,respondent_user_id,response_encrypted) VALUES (:checkin,:actor,:response)"
        ),
        {"checkin": checkin, "actor": actor_id, "response": encrypt_private(responses)},
    )
    await _history(
        session, journey_id=journey_id, actor_id=actor_id, event_type="checkin_completed"
    )
    return {"checkin_id": str(checkin), "status": "completed", "visibility": visibility}


async def create_reflection(
    session: AsyncSession,
    *,
    journey_id: UUID,
    actor_id: UUID,
    reflection: str,
    ai_processing_consent_id: str | None,
) -> dict[str, Any]:
    await _journey(session, journey_id, actor_id)
    consent_uuid = UUID(ai_processing_consent_id) if ai_processing_consent_id else None
    if consent_uuid is not None:
        consent_allowed = await session.scalar(
            text(
                "SELECT count(*) FROM user_consents c "
                "JOIN consent_definitions d ON d.id=c.consent_definition_id "
                "JOIN ai_memory_preferences p ON p.user_id=c.user_id "
                "WHERE c.id=:consent AND c.user_id=:actor AND c.status='granted' "
                "AND (c.expires_at IS NULL OR c.expires_at>now()) "
                "AND d.consent_code='ai_long_term_memory' "
                "AND p.long_term_memory_enabled=true "
                "AND p.allow_relationship_context=true"
            ),
            {"consent": consent_uuid, "actor": actor_id},
        )
        if int(consent_allowed or 0) == 0:
            raise VavError(
                "RELATIONSHIP_AI_CONSENT_REQUIRED",
                "AI processing requires active relationship-context consent.",
                status_code=409,
            )
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO relationship_reflections (journey_id,author_user_id,reflection_encrypted,ai_processing_consent_id) VALUES (:journey,:actor,:reflection,:consent) RETURNING id,created_at"
                ),
                {
                    "journey": journey_id,
                    "actor": actor_id,
                    "reflection": encrypt_private(reflection),
                    "consent": consent_uuid,
                },
            )
        )
        .mappings()
        .one()
    )
    return {
        "reflection_id": str(row["id"]),
        "created_at": row["created_at"],
        "private": True,
        "ai_processing_enabled": consent_uuid is not None,
    }


async def list_reflections(
    session: AsyncSession, journey_id: UUID, actor_id: UUID
) -> list[dict[str, Any]]:
    await _journey(session, journey_id, actor_id)
    rows = (
        await session.execute(
            text(
                "SELECT id,reflection_encrypted,ai_processing_consent_id,created_at FROM relationship_reflections WHERE journey_id=:journey AND author_user_id=:actor AND status='active' ORDER BY created_at DESC"
            ),
            {"journey": journey_id, "actor": actor_id},
        )
    ).mappings()
    return [
        {
            "reflection_id": str(row["id"]),
            "reflection": decrypt_private(row["reflection_encrypted"]),
            "created_at": row["created_at"],
            "private": True,
            "ai_processing_enabled": row["ai_processing_consent_id"] is not None,
        }
        for row in rows
    ]


async def create_action_item(
    session: AsyncSession,
    *,
    journey_id: UUID,
    actor_id: UUID,
    assigned_to_user_id: UUID,
    title: str,
    details: str | None,
) -> dict[str, Any]:
    journey = await _journey(session, journey_id, actor_id)
    if assigned_to_user_id not in (journey["user_low_id"], journey["user_high_id"]):
        raise VavError(
            "RELATIONSHIP_ACTION_ASSIGNEE_INVALID",
            "An action item can only belong to a journey participant.",
            status_code=422,
        )
    status = "open" if assigned_to_user_id == actor_id else "proposed"
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO relationship_action_items (journey_id,created_by_user_id,assigned_to_user_id,title,details_encrypted,status) VALUES (:journey,:actor,:assignee,:title,:details,:status) RETURNING id,status,created_at"
                ),
                {
                    "journey": journey_id,
                    "actor": actor_id,
                    "assignee": assigned_to_user_id,
                    "title": title,
                    "details": encrypt_private(details) if details else None,
                    "status": status,
                },
            )
        )
        .mappings()
        .one()
    )
    await _history(
        session, journey_id=journey_id, actor_id=actor_id, event_type="action_item_created"
    )
    return {
        "action_item_id": str(row["id"]),
        "status": row["status"],
        "created_at": row["created_at"],
    }


async def list_action_items(
    session: AsyncSession, journey_id: UUID, actor_id: UUID
) -> list[dict[str, Any]]:
    await _journey(session, journey_id, actor_id)
    rows = (
        await session.execute(
            text(
                "SELECT id,created_by_user_id,assigned_to_user_id,title,details_encrypted,status,accepted_at,completed_at,created_at FROM relationship_action_items WHERE journey_id=:journey AND :actor IN (created_by_user_id,assigned_to_user_id) ORDER BY created_at DESC"
            ),
            {"journey": journey_id, "actor": actor_id},
        )
    ).mappings()
    return [
        {
            "action_item_id": str(row["id"]),
            "created_by_user_id": str(row["created_by_user_id"]),
            "assigned_to_user_id": str(row["assigned_to_user_id"]),
            "title": row["title"],
            "details": decrypt_private(row["details_encrypted"])
            if row["details_encrypted"]
            else None,
            "status": row["status"],
            "accepted_at": row["accepted_at"],
            "completed_at": row["completed_at"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


async def decide_action_item(
    session: AsyncSession, *, action_item_id: UUID, actor_id: UUID, accept: bool
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM relationship_action_items WHERE id=:id FOR UPDATE"),
                {"id": action_item_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["assigned_to_user_id"] != actor_id:
        raise VavError(
            "RELATIONSHIP_ACTION_NOT_FOUND", "That action item was not found.", status_code=404
        )
    if row["status"] != "proposed" or row["created_by_user_id"] == actor_id:
        raise VavError(
            "RELATIONSHIP_ACTION_STATE_CHANGED",
            "That proposal is no longer pending.",
            status_code=409,
        )
    status = "open" if accept else "declined"
    await session.execute(
        text(
            "UPDATE relationship_action_items SET status=:status,accepted_at=CASE WHEN :accept THEN now() ELSE NULL END,updated_at=now() WHERE id=:id"
        ),
        {"id": action_item_id, "status": status, "accept": accept},
    )
    await _history(
        session,
        journey_id=row["journey_id"],
        actor_id=actor_id,
        event_type=f"action_item_{'accepted' if accept else 'declined'}",
    )
    return {"action_item_id": str(action_item_id), "status": status}


async def complete_action_item(
    session: AsyncSession, *, action_item_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "UPDATE relationship_action_items SET status='completed',completed_at=now(),updated_at=now() WHERE id=:id AND assigned_to_user_id=:actor AND status='open' RETURNING journey_id"
                ),
                {"id": action_item_id, "actor": actor_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "RELATIONSHIP_ACTION_STATE_CHANGED",
            "That action item cannot be completed.",
            status_code=409,
        )
    await _history(
        session, journey_id=row["journey_id"], actor_id=actor_id, event_type="action_item_completed"
    )
    return {"action_item_id": str(action_item_id), "status": "completed"}


async def create_reminder_plan(
    session: AsyncSession,
    *,
    journey_id: UUID,
    actor_id: UUID,
    reminder_type: str,
    cadence_days: int,
    opted_in: bool,
) -> dict[str, Any]:
    journey = await _journey(session, journey_id, actor_id)
    if not opted_in or not get_settings().relationship_reminders_enabled:
        raise VavError(
            "RELATIONSHIP_REMINDER_OPT_IN_REQUIRED",
            "Reminders require explicit opt-in.",
            status_code=422,
        )
    if journey["status"] not in ("active", "paused"):
        raise VavError(
            "RELATIONSHIP_REMINDER_UNAVAILABLE",
            "Reminders are unavailable for this journey.",
            status_code=409,
        )
    allowed = {
        "first_reflection",
        "voluntary_checkin",
        "accepted_action_due",
        "private_pause_reflection",
        "optional_support",
        "private_ending_reflection",
    }
    if reminder_type not in allowed:
        raise VavError(
            "RELATIONSHIP_REMINDER_TYPE_INVALID",
            "That reminder type is not supported.",
            status_code=422,
        )
    dedup = f"{journey_id}:{actor_id}:{reminder_type}"
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO relationship_reminder_plans (journey_id,participant_user_id,reminder_type,status,cadence_days,next_due_at,opt_in_recorded_at,dedup_key,policy_snapshot) VALUES (:journey,:actor,:type,'active',:cadence,now()+make_interval(days => :cadence),now(),:dedup,CAST(:policy AS jsonb)) ON CONFLICT (participant_user_id,dedup_key) DO UPDATE SET status='active',cadence_days=EXCLUDED.cadence_days,next_due_at=EXCLUDED.next_due_at,opt_in_recorded_at=now(),updated_at=now() RETURNING id,status,next_due_at"
                ),
                {
                    "journey": journey_id,
                    "actor": actor_id,
                    "type": reminder_type,
                    "cadence": cadence_days,
                    "dedup": dedup,
                    "policy": _json(
                        {
                            "opt_in": True,
                            "neutral_content": True,
                            "maximum_per_month": get_settings().relationship_reminder_max_per_month,
                        }
                    ),
                },
            )
        )
        .mappings()
        .one()
    )
    await _publish(
        session,
        "relationships.reminder.created",
        journey_id,
        {
            "journey_id": str(journey_id),
            "reminder_plan_id": str(row["id"]),
            "recipient_user_ids": [str(actor_id)],
        },
    )
    return {
        "reminder_plan_id": str(row["id"]),
        "status": row["status"],
        "next_due_at": row["next_due_at"],
    }


async def list_reminder_plans(
    session: AsyncSession, journey_id: UUID, actor_id: UUID
) -> list[dict[str, Any]]:
    await _journey(session, journey_id, actor_id)
    rows = (
        await session.execute(
            text(
                "SELECT id,reminder_type,status,cadence_days,next_due_at,last_sent_at,sent_this_month,opt_in_recorded_at FROM relationship_reminder_plans WHERE journey_id=:journey AND participant_user_id=:actor ORDER BY created_at DESC"
            ),
            {"journey": journey_id, "actor": actor_id},
        )
    ).mappings()
    return [{**dict(row), "id": str(row["id"])} for row in rows]


async def cancel_reminder_plan(
    session: AsyncSession, *, reminder_plan_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "UPDATE relationship_reminder_plans SET status='cancelled',updated_at=now() WHERE id=:id AND participant_user_id=:actor AND status IN ('active','paused') RETURNING journey_id"
                ),
                {"id": reminder_plan_id, "actor": actor_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "RELATIONSHIP_REMINDER_NOT_FOUND", "That reminder plan was not found.", status_code=404
        )
    await _publish(
        session,
        "relationships.reminder.cancelled",
        row["journey_id"],
        {
            "journey_id": str(row["journey_id"]),
            "reminder_plan_id": str(reminder_plan_id),
            "recipient_user_ids": [str(actor_id)],
        },
    )
    return {"reminder_plan_id": str(reminder_plan_id), "status": "cancelled"}


async def safety_transition(
    session: AsyncSession,
    *,
    journey_id: UUID,
    actor_id: UUID,
    freeze: bool,
    reason_code: str,
    purpose: str,
) -> dict[str, Any]:
    journey = (
        (
            await session.execute(
                text("SELECT * FROM relationship_journeys WHERE id=:id FOR UPDATE"),
                {"id": journey_id},
            )
        )
        .mappings()
        .first()
    )
    if journey is None:
        raise VavError(
            "RELATIONSHIP_NOT_FOUND", "That relationship journey was not found.", status_code=404
        )
    target = "safety_frozen" if freeze else "active"
    if not freeze and journey["status"] != "safety_frozen":
        raise VavError(
            "RELATIONSHIP_SAFETY_STATE_INVALID",
            "Only a safety-frozen journey can be unfrozen.",
            status_code=409,
        )
    await session.execute(
        text(
            "UPDATE relationship_journeys SET status=:status,version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"id": journey_id, "status": target},
    )
    await session.execute(
        text(
            "INSERT INTO relationship_audit_events (event_type,actor_id,journey_id,subject_type,subject_id,purpose,reason) VALUES (:event,:actor,:journey,'relationship_journey',:journey,:purpose,:reason)"
        ),
        {
            "event": "relationship.safety_frozen" if freeze else "relationship.safety_unfrozen",
            "actor": actor_id,
            "journey": journey_id,
            "purpose": purpose,
            "reason": reason_code,
        },
    )
    await _history(
        session,
        journey_id=journey_id,
        actor_id=actor_id,
        event_type="safety_frozen" if freeze else "safety_unfrozen",
        from_status=journey["status"],
        to_status=target,
        reason_code=reason_code,
    )
    return {"journey_id": str(journey_id), "status": target}
