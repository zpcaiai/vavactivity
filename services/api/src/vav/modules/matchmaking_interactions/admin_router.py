"""Administrator interaction centre.

Everything here is diagnosis and repair. There is no endpoint that likes on a
member's behalf, accepts or declines for them, consents to a contact exchange,
or turns a decline into an acceptance — those routes do not exist, so no
permission misconfiguration can produce them.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.matchmaking_interactions import contact_exchange as exchange_service
from vav.modules.matchmaking_interactions import invalidation, service
from vav.modules.matchmaking_interactions.domain import InvitationStatus, MutualMatchStatus
from vav.modules.matchmaking_interactions.schemas import (
    AdminInvalidateRequest,
    AdminSensitiveReadRequest,
)
from vav.modules.privacy.crypto import decrypt_private

router = APIRouter(prefix="/admin/matchmaking/interactions")


def _anonymous(user_id: UUID | None) -> str | None:
    """Operators see a stable pseudonym, not an identity, by default."""
    return f"user-{str(user_id)[:8]}" if user_id is not None else None


@router.get("/dashboard")
async def dashboard(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.analytics.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Process metrics.

    These describe how the mechanism is running. They are not a measure of
    anybody's relationship quality, and the response says so.
    """
    counts = (
        await session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM matchmaking_likes) AS likes, "
                "(SELECT count(*) FROM matchmaking_likes WHERE status='withdrawn') AS likes_withdrawn, "
                "(SELECT count(*) FROM matchmaking_skips) AS skips, "
                "(SELECT count(*) FROM matchmaking_mutual_matches) AS matches, "
                "(SELECT count(*) FROM matchmaking_mutual_matches WHERE status='safety_frozen') AS matches_frozen, "
                "(SELECT count(*) FROM matchmaking_introduction_invitations) AS invitations, "
                "(SELECT count(*) FROM matchmaking_introduction_invitations WHERE status='accepted') AS invitations_accepted, "
                "(SELECT count(*) FROM matchmaking_introduction_invitations WHERE status='declined') AS invitations_declined, "
                "(SELECT count(*) FROM matchmaking_introduction_invitations WHERE status='expired') AS invitations_expired, "
                "(SELECT count(*) FROM matchmaking_contact_exchange_requests) AS contact_requests, "
                "(SELECT count(*) FROM matchmaking_contact_exchange_requests WHERE status='active') AS contact_active, "
                "(SELECT count(*) FROM matchmaking_contact_exchange_requests WHERE status IN ('revoked','partially_revoked')) AS contact_revoked, "
                "(SELECT count(*) FROM matchmaking_interaction_inbox_events WHERE status='processed') AS events_processed, "
                "(SELECT count(*) FROM matchmaking_interaction_dead_letters WHERE status='open') AS dead_letters"
            )
        )
    ).mappings()
    row = dict(counts.one())
    likes = int(row["likes"] or 0)
    invitations = int(row["invitations"] or 0)
    payload = {
        **{key: int(value or 0) for key, value in row.items()},
        "mutual_match_rate_bps": _rate_bps(int(row["matches"] or 0) * 2, likes),
        "invitation_acceptance_rate_bps": _rate_bps(
            int(row["invitations_accepted"] or 0), invitations
        ),
        "invitation_decline_rate_bps": _rate_bps(
            int(row["invitations_declined"] or 0), invitations
        ),
        "invitation_expiry_rate_bps": _rate_bps(int(row["invitations_expired"] or 0), invitations),
        "note": (
            "These are process metrics for the interaction pipeline. They do not "
            "measure relationship quality or matchmaking success."
        ),
    }
    return success(payload, request_id_from_request(request))


def _rate_bps(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round(numerator * 10_000 / denominator)


@router.get("/pairs")
async def list_pairs(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.interactions.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """List canonical pairs without exposing either member's choices."""
    rows = (
        await session.execute(
            text(
                "SELECT p.id,p.user_low_id,p.user_high_id,p.status,p.pair_version,"
                "p.restriction_version,p.created_at,p.updated_at,"
                "(SELECT count(*) FROM matchmaking_mutual_matches m WHERE m.pair_id=p.id) "
                "AS match_count,(SELECT count(*) FROM matchmaking_introduction_invitations i "
                "WHERE i.pair_id=p.id) AS invitation_count FROM matchmaking_pairs p "
                "ORDER BY p.updated_at DESC LIMIT 300"
            )
        )
    ).mappings()
    return success(
        [
            {
                "pair_id": str(row["id"]),
                "members": [_anonymous(row["user_low_id"]), _anonymous(row["user_high_id"])],
                "status": row["status"],
                "pair_version": row["pair_version"],
                "restriction_version": row["restriction_version"],
                "match_count": int(row["match_count"] or 0),
                "invitation_count": int(row["invitation_count"] or 0),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
        request_id_from_request(request),
    )


@router.get("/pairs/{pair_id}")
async def pair_diagnostics(
    pair_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.interactions.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """The default operator view of a pair.

    It carries statuses, versions and a timeline. It does not carry the list of
    one-sided likes, a skip reason, an invitation body, contact details or
    either member's preferences.
    """
    rows = (
        await session.execute(text("SELECT * FROM matchmaking_pairs WHERE id=:id"), {"id": pair_id})
    ).mappings()
    pair = rows.first()
    if pair is None:
        raise VavError("PAIR_NOT_FOUND", "That pair was not found.", status_code=404)

    match_rows = (
        await session.execute(
            text(
                "SELECT id,status,source,matched_at,closed_at,closure_reason_code,match_version "
                "FROM matchmaking_mutual_matches WHERE pair_id=:pair"
            ),
            {"pair": pair_id},
        )
    ).mappings()
    invitation_rows = (
        await session.execute(
            text(
                "SELECT id,status,sent_at,expires_at,accepted_at,declined_at,cancelled_at,"
                "expired_at,invitation_version FROM matchmaking_introduction_invitations "
                "WHERE pair_id=:pair ORDER BY created_at DESC"
            ),
            {"pair": pair_id},
        )
    ).mappings()
    exchange_rows = (
        await session.execute(
            text(
                "SELECT id,status,policy,consent_version,activated_at,revoked_at "
                "FROM matchmaking_contact_exchange_requests WHERE pair_id=:pair"
            ),
            {"pair": pair_id},
        )
    ).mappings()
    history_rows = (
        await session.execute(
            text(
                "SELECT entity_type,entity_id,action,from_status,to_status,reason_code,"
                "safe_metadata,occurred_at FROM matchmaking_interaction_history "
                "WHERE pair_id=:pair ORDER BY occurred_at DESC LIMIT 200"
            ),
            {"pair": pair_id},
        )
    ).mappings()

    return success(
        {
            "pair_id": str(pair["id"]),
            "members": [
                _anonymous(pair["user_low_id"]),
                _anonymous(pair["user_high_id"]),
            ],
            "status": pair["status"],
            "pair_version": pair["pair_version"],
            "restriction_version": pair["restriction_version"],
            "matches": [dict(row) | {"id": str(row["id"])} for row in match_rows],
            "invitations": [dict(row) | {"id": str(row["id"])} for row in invitation_rows],
            "contact_exchanges": [dict(row) | {"id": str(row["id"])} for row in exchange_rows],
            "timeline": [dict(row) for row in history_rows],
        },
        request_id_from_request(request),
    )


@router.post("/pairs/{pair_id}/sensitive")
async def pair_sensitive_view(
    pair_id: UUID,
    payload: AdminSensitiveReadRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.interactions.sensitive.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Investigation view.

    A purpose is mandatory and every read is written to the platform-wide
    sensitive-access log before the data is returned.
    """
    rows = (
        await session.execute(text("SELECT * FROM matchmaking_pairs WHERE id=:id"), {"id": pair_id})
    ).mappings()
    pair = rows.first()
    if pair is None:
        raise VavError("PAIR_NOT_FOUND", "That pair was not found.", status_code=404)

    for subject in (pair["user_low_id"], pair["user_high_id"]):
        await service.sensitive_access(
            session,
            actor_user_id=principal.user.id,
            subject_user_id=subject,
            asset_code="matchmaking_interaction_pair",
            purpose=payload.purpose,
            permission_code="matchmaking.interactions.sensitive.read",
        )
    await service.audit(
        session,
        event_type="matchmaking.interaction.admin_accessed",
        subject_type="pair",
        subject_id=pair_id,
        actor_id=principal.user.id,
        purpose=payload.purpose,
    )

    like_rows = (
        await session.execute(
            text(
                "SELECT id,actor_user_id,target_user_id,status,source,created_at,"
                "invalidation_reason_code FROM matchmaking_likes WHERE pair_id=:pair "
                "ORDER BY created_at"
            ),
            {"pair": pair_id},
        )
    ).mappings()
    skip_rows = (
        await session.execute(
            text(
                "SELECT id,actor_user_id,skip_type,reason_code,status,cooldown_until,created_at "
                "FROM matchmaking_skips WHERE pair_id=:pair ORDER BY created_at"
            ),
            {"pair": pair_id},
        )
    ).mappings()
    return success(
        {
            "pair_id": str(pair_id),
            "purpose": payload.purpose,
            "likes": [
                {
                    "like_id": str(row["id"]),
                    "actor": _anonymous(row["actor_user_id"]),
                    "target": _anonymous(row["target_user_id"]),
                    "status": row["status"],
                    "source": row["source"],
                    "created_at": row["created_at"],
                    "invalidation_reason_code": row["invalidation_reason_code"],
                }
                for row in like_rows
            ],
            # The reason code is shown; the encrypted free text is not decrypted
            # here, because a code is enough to triage a harassment report.
            "skips": [
                {
                    "skip_id": str(row["id"]),
                    "actor": _anonymous(row["actor_user_id"]),
                    "skip_type": row["skip_type"],
                    "reason_code": row["reason_code"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                }
                for row in skip_rows
            ],
        },
        request_id_from_request(request),
    )


@router.post("/invitations/{invitation_id}/content")
async def invitation_content(
    invitation_id: UUID,
    payload: AdminSensitiveReadRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.invitations.content.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Read one invitation body during an investigation."""
    rows = (
        await session.execute(
            text("SELECT * FROM matchmaking_introduction_invitations WHERE id=:id"),
            {"id": invitation_id},
        )
    ).mappings()
    invitation = rows.first()
    if invitation is None:
        raise VavError("INVITATION_NOT_FOUND", "That introduction was not found.", status_code=404)

    await service.sensitive_access(
        session,
        actor_user_id=principal.user.id,
        subject_user_id=invitation["sender_user_id"],
        asset_code="matchmaking_invitation_message",
        purpose=payload.purpose,
        permission_code="matchmaking.invitations.content.read",
    )
    await service.audit(
        session,
        event_type="matchmaking.interaction.admin_accessed",
        subject_type="invitation",
        subject_id=invitation_id,
        actor_id=principal.user.id,
        purpose=payload.purpose,
    )
    message = (
        decrypt_private(invitation["message_encrypted"])
        if invitation["message_encrypted"] is not None
        else None
    )
    return success(
        {
            "invitation_id": str(invitation_id),
            "status": invitation["status"],
            "message": message,
            "screening": service.jsonb(invitation["message_screening"]),
            "decline_reason_code": invitation["decline_reason_code"],
        },
        request_id_from_request(request),
    )


@router.post("/pairs/{pair_id}/invalidate")
async def invalidate_pair(
    pair_id: UUID,
    payload: AdminInvalidateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.matches.invalidate")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Invalidate every open interaction on a pair."""
    rows = (
        await session.execute(
            text("SELECT user_low_id, user_high_id FROM matchmaking_pairs WHERE id=:id"),
            {"id": pair_id},
        )
    ).mappings()
    pair = rows.first()
    if pair is None:
        raise VavError("PAIR_NOT_FOUND", "That pair was not found.", status_code=404)
    summary = await invalidation.invalidate_pair(
        session,
        user_a_id=pair["user_low_id"],
        user_b_id=pair["user_high_id"],
        reason_code=payload.reason_code,
        actor_user_id=principal.user.id,
    )
    await service.audit(
        session,
        event_type="matchmaking.match.invalidated",
        subject_type="pair",
        subject_id=pair_id,
        actor_id=principal.user.id,
        purpose=payload.purpose,
        reason=payload.reason_code,
    )
    return success(summary.as_dict(), request_id_from_request(request))


@router.post("/contact-exchanges/{exchange_id}/revoke")
async def revoke_contact_exchange(
    exchange_id: UUID,
    payload: AdminInvalidateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.contact_exchange.revoke")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Revoke a contact grant that should not have been issued.

    An administrator can take access away. There is no counterpart that grants
    it — that requires both members.
    """
    rows = (
        await session.execute(
            text("SELECT pair_id FROM matchmaking_contact_exchange_requests WHERE id=:id"),
            {"id": exchange_id},
        )
    ).mappings()
    exchange = rows.first()
    if exchange is None:
        raise VavError(
            "CONTACT_EXCHANGE_NOT_FOUND", "That contact exchange was not found.", status_code=404
        )
    await exchange_service.revoke_for_pair(
        session, pair_id=exchange["pair_id"], reason=payload.reason_code
    )
    await service.audit(
        session,
        event_type="matchmaking.contact_exchange.revoked",
        subject_type="contact_exchange",
        subject_id=exchange_id,
        actor_id=principal.user.id,
        purpose=payload.purpose,
        reason=payload.reason_code,
    )
    return success(
        {"contact_exchange_request_id": str(exchange_id), "status": "revoked"},
        request_id_from_request(request),
    )


@router.get("/dead-letters")
async def list_dead_letters(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.dead_letters.resolve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id,event_type,error_code,status,created_at,resolved_at "
                "FROM matchmaking_interaction_dead_letters ORDER BY created_at DESC LIMIT 200"
            )
        )
    ).mappings()
    return success(
        [dict(row) | {"id": str(row["id"])} for row in rows], request_id_from_request(request)
    )


@router.post("/dead-letters/{dead_letter_id}/resolve")
async def resolve_dead_letter(
    dead_letter_id: UUID,
    payload: AdminSensitiveReadRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.dead_letters.resolve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    updated = (
        await session.execute(
            text(
                "UPDATE matchmaking_interaction_dead_letters SET status='resolved', "
                "resolved_by=:actor, resolution_note=:note, resolved_at=now() "
                "WHERE id=:id AND status='open' RETURNING id"
            ),
            {"id": dead_letter_id, "actor": principal.user.id, "note": payload.purpose},
        )
    ).mappings()
    if updated.first() is None:
        raise VavError("DEAD_LETTER_NOT_OPEN", "That dead letter is not open.", status_code=409)
    await service.audit(
        session,
        event_type="matchmaking.interaction.dead_letter_resolved",
        subject_type="dead_letter",
        subject_id=dead_letter_id,
        actor_id=principal.user.id,
        purpose=payload.purpose,
    )
    return success(
        {"dead_letter_id": str(dead_letter_id), "status": "resolved"},
        request_id_from_request(request),
    )


@router.get("/diagnostics/duplicates")
async def duplicate_diagnostics(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.diagnostics.run")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Look for the invariants the database is supposed to make impossible.

    If any of these ever returns a non-zero count, a constraint has been lost —
    which is worth knowing before the data drifts further.
    """
    row = (
        await session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM (SELECT pair_id FROM matchmaking_mutual_matches "
                "  GROUP BY pair_id HAVING count(*) > 1) d) AS duplicate_matches, "
                "(SELECT count(*) FROM (SELECT actor_user_id,target_user_id FROM matchmaking_likes "
                "  WHERE status IN ('active','matched') GROUP BY actor_user_id,target_user_id "
                "  HAVING count(*) > 1) d) AS duplicate_active_likes, "
                "(SELECT count(*) FROM (SELECT mutual_match_id FROM matchmaking_introduction_invitations "
                "  WHERE status='pending' GROUP BY mutual_match_id HAVING count(*) > 1) d) "
                "  AS duplicate_pending_invitations, "
                "(SELECT count(*) FROM matchmaking_interaction_inbox_events WHERE status='failed') "
                "  AS failed_inbox_events"
            )
        )
    ).mappings()
    return success(
        {key: int(value or 0) for key, value in dict(row.one()).items()},
        request_id_from_request(request),
    )


@router.get("/matches")
async def list_matches(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.matches.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id,pair_id,user_low_id,user_high_id,status,source,matched_at,"
                "closure_reason_code FROM matchmaking_mutual_matches "
                "ORDER BY matched_at DESC LIMIT 300"
            )
        )
    ).mappings()
    return success(
        [
            {
                "mutual_match_id": str(row["id"]),
                "pair_id": str(row["pair_id"]),
                "members": [_anonymous(row["user_low_id"]), _anonymous(row["user_high_id"])],
                "status": row["status"],
                "source": row["source"],
                "matched_at": row["matched_at"],
                "closure_reason_code": row["closure_reason_code"],
            }
            for row in rows
        ],
        request_id_from_request(request),
    )


@router.get("/invitations")
async def list_invitations(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.invitations.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Invitation states without their bodies.

    Reading what somebody wrote requires the separate content permission and a
    stated purpose.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id,mutual_match_id,status,sent_at,expires_at,accepted_at,declined_at,"
                "cancelled_at,expired_at FROM matchmaking_introduction_invitations "
                "ORDER BY created_at DESC LIMIT 300"
            )
        )
    ).mappings()
    return success(
        [
            dict(row) | {"id": str(row["id"]), "mutual_match_id": str(row["mutual_match_id"])}
            for row in rows
        ],
        request_id_from_request(request),
    )


@router.get("/contact-exchanges")
async def list_contact_exchanges(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.contact_exchange.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT r.id,r.mutual_match_id,r.pair_id,r.status,r.policy,r.consent_version,"
                "r.created_at,r.activated_at,r.revoked_at,"
                "(SELECT count(*) FROM matchmaking_contact_exchange_consents c "
                "WHERE c.contact_exchange_request_id=r.id AND c.status='consented') AS consents,"
                "(SELECT count(*) FROM matchmaking_contact_exchange_grants g "
                "WHERE g.contact_exchange_request_id=r.id AND g.status='active') AS active_grants "
                "FROM matchmaking_contact_exchange_requests r ORDER BY r.created_at DESC LIMIT 300"
            )
        )
    ).mappings()
    return success(
        [
            dict(row)
            | {
                "id": str(row["id"]),
                "mutual_match_id": str(row["mutual_match_id"]),
                "pair_id": str(row["pair_id"]),
                "consents": int(row["consents"] or 0),
                "active_grants": int(row["active_grants"] or 0),
            }
            for row in rows
        ],
        request_id_from_request(request),
    )


@router.get("/contact-exchanges/{exchange_id}")
async def contact_exchange_diagnostics(
    exchange_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.contact_exchange.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    request_rows = (
        await session.execute(
            text(
                "SELECT id,mutual_match_id,pair_id,status,policy,policy_version,consent_version,"
                "created_at,activated_at,revoked_at,invalidated_at "
                "FROM matchmaking_contact_exchange_requests WHERE id=:id"
            ),
            {"id": exchange_id},
        )
    ).mappings()
    exchange = request_rows.first()
    if exchange is None:
        raise VavError(
            "CONTACT_EXCHANGE_NOT_FOUND", "That contact exchange was not found.", status_code=404
        )
    consent_rows = (
        await session.execute(
            text(
                "SELECT status,platform_only_preferred,consented_at,withdrawn_at "
                "FROM matchmaking_contact_exchange_consents "
                "WHERE contact_exchange_request_id=:id ORDER BY created_at"
            ),
            {"id": exchange_id},
        )
    ).mappings()
    grant_rows = (
        await session.execute(
            text(
                "SELECT status,granted_at,expires_at,suspended_at,revoked_at,revoke_reason "
                "FROM matchmaking_contact_exchange_grants "
                "WHERE contact_exchange_request_id=:id ORDER BY granted_at"
            ),
            {"id": exchange_id},
        )
    ).mappings()
    return success(
        {
            "exchange": dict(exchange) | {"id": str(exchange["id"])},
            "consents": [dict(row) for row in consent_rows],
            "grants": [dict(row) for row in grant_rows],
            "redaction_notice": (
                "Contact values, selected point identifiers and one-sided consent details are "
                "excluded from routine operations views."
            ),
        },
        request_id_from_request(request),
    )


@router.get("/audit")
async def list_audit(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("matchmaking.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT event_type,subject_type,subject_id,purpose,reason,safe_context,created_at "
                "FROM matchmaking_interaction_audit_events ORDER BY created_at DESC LIMIT 300"
            )
        )
    ).mappings()
    return success([dict(row) for row in rows], request_id_from_request(request))


@router.get("/invalidations")
async def list_invalidations(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.interactions.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT h.pair_id,h.entity_type,h.entity_id,h.action,h.from_status,h.to_status,"
                "h.reason_code,h.safe_metadata,h.occurred_at FROM matchmaking_interaction_history h "
                "WHERE h.action IN ('invalidated','revoked','suspended','frozen') "
                "OR h.to_status IN ('invalidated','revoked','suspended','safety_frozen','restricted') "
                "ORDER BY h.occurred_at DESC LIMIT 300"
            )
        )
    ).mappings()
    return success(
        [dict(row) | {"pair_id": str(row["pair_id"])} for row in rows],
        request_id_from_request(request),
    )


@router.get("/incidents")
async def list_incidents(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("matchmaking.incidents.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT event_type,subject_type,subject_id,purpose,reason,safe_context,created_at "
                "FROM matchmaking_interaction_audit_events WHERE "
                "event_type LIKE 'matchmaking.%invalidated%' OR "
                "event_type LIKE 'matchmaking.%revoked%' OR "
                "event_type LIKE 'matchmaking.%denied%' OR "
                "reason IN ('block_created','restriction_created','high_risk_report',"
                "'moderation_unavailable') ORDER BY created_at DESC LIMIT 300"
            )
        )
    ).mappings()
    return success(
        {
            "incidents": [dict(row) for row in rows],
            "boundary": (
                "This is the Batch 15 interaction incident projection. Full report, block and "
                "investigation ownership remains in Batch 18."
            ),
        },
        request_id_from_request(request),
    )


#: Statuses the admin UI groups as "needs attention". Kept here so the API and
#: the console cannot disagree about what counts as stuck.
ATTENTION_STATUSES = {
    "matches": [MutualMatchStatus.SAFETY_FROZEN.value],
    "invitations": [InvitationStatus.INVALIDATED.value],
}
