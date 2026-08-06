"""Mutually confirmed contact exchange.

Agreeing to be contactable is its own decision, made separately by each
member, about specific verified channels, and revocable. One side consenting
reveals nothing. The platform can stop future access; it cannot un-remember
what the other member already wrote down, and it says so rather than implying
a guarantee it cannot keep.
"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.matchmaking_interactions import invitations as invitation_service
from vav.modules.matchmaking_interactions import matches as match_service
from vav.modules.matchmaking_interactions import service
from vav.modules.matchmaking_interactions.domain import (
    ConsentStatus,
    ContactExchangePolicy,
    ContactExchangeStatus,
    GrantStatus,
    MutualMatchStatus,
)
from vav.modules.matchmaking_interactions.gateways import (
    EventGateway,
    OutboxEvent,
    PrivacyGateway,
)
from vav.modules.privacy.crypto import decrypt_private, mask_email, mask_phone

#: What a member is told before they choose. Plain, and honest about the
#: limit of what revocation can do.
EXCHANGE_DISCLOSURES = (
    "Contact details are shared only after both of you confirm.",
    "You can choose a single verified channel, or none at all.",
    "You can withdraw access later, but the platform cannot delete information "
    "the other member has already saved elsewhere.",
)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _contact_hash(contact_type: str, value_hmac: str) -> str:
    """Bind a consent to the exact value that was agreed to.

    ``value_hmac`` already identifies the contact value without exposing it,
    so hashing type plus hmac gives a fingerprint that changes the moment the
    member replaces the number — which is what makes the old consent stale
    instead of silently covering the new value.
    """
    return hashlib.sha256(f"{contact_type}:{value_hmac}".encode()).hexdigest()


def _mask(contact_type: str, plaintext: str) -> str:
    if contact_type == "email":
        return mask_email(plaintext)
    if contact_type in {"phone", "mobile"}:
        return mask_phone(plaintext)
    return f"{plaintext[:2]}***"


async def request_exchange(
    session: AsyncSession,
    *,
    user_id: UUID,
    match_id: UUID,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Open an exchange for an accepted introduction."""
    service.enabled()
    settings = get_settings()
    policy = ContactExchangePolicy(settings.matchmaking_contact_exchange_policy)
    if policy is ContactExchangePolicy.PLATFORM_ONLY:
        raise VavError(
            "CONTACT_EXCHANGE_DISABLED",
            "Contact exchange is not available; please keep talking on the platform.",
            status_code=403,
        )

    match = await match_service.member_match(session, user_id=user_id, match_id=match_id)
    if str(match["status"]) != MutualMatchStatus.INTRODUCTION_ACCEPTED.value:
        # Before acceptance there is nothing to exchange. This is the gate the
        # whole flow depends on.
        raise VavError(
            "INTRODUCTION_NOT_ACCEPTED",
            "Contact exchange becomes available after an introduction is accepted.",
            status_code=409,
        )
    invitation = await invitation_service.active_invitation_for_match(session, match_id)
    if invitation is None:
        raise VavError(
            "INTRODUCTION_NOT_ACCEPTED",
            "Contact exchange becomes available after an introduction is accepted.",
            status_code=409,
        )

    other_user_id = match_service.other_member(match, user_id)
    eligibility = await service.check_interaction_allowed(
        session,
        actor_user_id=user_id,
        target_user_id=other_user_id,
        # Contact exchange happens inside an accepted introduction, so the
        # relationship that acceptance created must not disqualify it.
        reject_existing_relationship=False,
    )
    eligibility.raise_for_member()

    privacy = PrivacyGateway(session)
    for member in (user_id, other_user_id):
        if not await privacy.allows_contact_exchange(member):
            # A member whose privacy settings do not permit exchange is not
            # named: the requester is told only that it is unavailable.
            raise VavError(
                "CONTACT_EXCHANGE_NOT_AVAILABLE",
                "Contact exchange is not available for this introduction.",
                status_code=403,
            )

    inserted = (
        await session.execute(
            text(
                "INSERT INTO matchmaking_contact_exchange_requests "
                "(mutual_match_id,invitation_id,pair_id,requested_by_user_id,status,"
                "policy_version,policy) VALUES "
                "(:match,:invitation,:pair,:user,:status,:policy_version,:policy) "
                "ON CONFLICT (mutual_match_id) DO NOTHING RETURNING *"
            ),
            {
                "match": match_id,
                "invitation": invitation["id"],
                "pair": match["pair_id"],
                "user": user_id,
                "status": ContactExchangeStatus.REQUESTED.value,
                "policy_version": "batch-15-v1",
                "policy": policy.value,
            },
        )
    ).mappings()
    created = inserted.first()
    if created is None:
        existing = await _request_for_match(session, match_id)
        if existing is None:  # pragma: no cover
            raise VavError(
                "CONTACT_EXCHANGE_UNAVAILABLE", "Contact exchange is unavailable.", status_code=409
            )
        return await member_view(session, request=existing, user_id=user_id)
    exchange = dict(created)

    for member in (match["user_low_id"], match["user_high_id"]):
        await session.execute(
            text(
                "INSERT INTO matchmaking_contact_exchange_consents "
                "(contact_exchange_request_id,user_id,status) VALUES (:request,:user,:status) "
                "ON CONFLICT (contact_exchange_request_id,user_id) DO NOTHING"
            ),
            {"request": exchange["id"], "user": member, "status": ConsentStatus.PENDING.value},
        )

    await service.append_history(
        session,
        pair_id=match["pair_id"],
        entity_type="contact_exchange",
        entity_id=exchange["id"],
        action="requested",
        actor_user_id=user_id,
        to_status=ContactExchangeStatus.REQUESTED.value,
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.contact_exchange.requested",
        subject_type="contact_exchange",
        subject_id=exchange["id"],
        actor_id=user_id,
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.contact_exchange.requested",
            aggregate_type="matchmaking_contact_exchange",
            aggregate_id=exchange["id"],
            payload={
                "contact_exchange_request_id": str(exchange["id"]),
                "recipient_user_ids": [str(other_user_id)],
            },
        )
    )
    return await member_view(session, request=exchange, user_id=user_id)


async def _request_for_match(session: AsyncSession, match_id: UUID) -> dict[str, Any] | None:
    rows = (
        await session.execute(
            text("SELECT * FROM matchmaking_contact_exchange_requests WHERE mutual_match_id=:m"),
            {"m": match_id},
        )
    ).mappings()
    found = rows.first()
    return dict(found) if found is not None else None


async def _locked_request(session: AsyncSession, request_id: UUID) -> dict[str, Any]:
    rows = (
        await session.execute(
            text("SELECT * FROM matchmaking_contact_exchange_requests WHERE id=:id FOR UPDATE"),
            {"id": request_id},
        )
    ).mappings()
    found = rows.first()
    if found is None:
        raise VavError(
            "CONTACT_EXCHANGE_NOT_FOUND", "That contact exchange was not found.", status_code=404
        )
    return dict(found)


async def _member_of(
    session: AsyncSession, request: dict[str, Any], user_id: UUID
) -> dict[str, Any]:
    match = await match_service.member_match(
        session, user_id=user_id, match_id=request["mutual_match_id"]
    )
    return match


async def submit_consent(
    session: AsyncSession,
    *,
    user_id: UUID,
    exchange_id: UUID,
    selected_contact_point_ids: list[UUID],
    platform_only: bool,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Record one member's decision.

    Nothing is revealed here. A grant is created only when the second member
    consents, and only for channels each of them chose for themselves.
    """
    service.enabled()
    settings = get_settings()
    exchange = await _locked_request(session, exchange_id)
    match = await _member_of(session, exchange, user_id)
    other_user_id = match_service.other_member(match, user_id)

    if str(exchange["status"]) in {
        ContactExchangeStatus.REVOKED.value,
        ContactExchangeStatus.INVALIDATED.value,
    }:
        raise VavError(
            "CONTACT_EXCHANGE_CLOSED", "This contact exchange is closed.", status_code=409
        )

    eligibility = await service.check_interaction_allowed(
        session,
        actor_user_id=user_id,
        target_user_id=other_user_id,
        # Contact exchange happens inside an accepted introduction, so the
        # relationship that acceptance created must not disqualify it.
        reject_existing_relationship=False,
    )
    eligibility.raise_for_member()

    if platform_only:
        selected: list[dict[str, Any]] = []
    else:
        selected = await _validate_selection(
            session, user_id=user_id, selected_contact_point_ids=selected_contact_point_ids
        )
        if not selected and settings.matchmaking_contact_exchange_require_verified_contact:
            raise VavError(
                "CONTACT_POINT_REQUIRED",
                "Choose at least one verified channel, or choose to stay on the platform.",
                status_code=422,
            )

    hashes = {
        str(item["id"]): _contact_hash(item["contact_type"], item["value_hmac"])
        for item in selected
    }
    await session.execute(
        text(
            "UPDATE matchmaking_contact_exchange_consents SET status=:status, "
            "selected_contact_point_ids=CAST(:ids AS jsonb), "
            "contact_point_hash_snapshot=CAST(:hashes AS jsonb), "
            "platform_only_preferred=:platform_only, consented_at=now(), withdrawn_at=NULL, "
            "updated_at=now() WHERE contact_exchange_request_id=:request AND user_id=:user"
        ),
        {
            "request": exchange_id,
            "user": user_id,
            "status": (
                ConsentStatus.PLATFORM_ONLY.value
                if platform_only
                else ConsentStatus.CONSENTED.value
            ),
            "ids": json.dumps([str(item["id"]) for item in selected]),
            "hashes": json.dumps(hashes),
            "platform_only": platform_only,
        },
    )
    await service.audit(
        session,
        event_type="matchmaking.contact_exchange.consented",
        subject_type="contact_exchange",
        subject_id=exchange_id,
        actor_id=user_id,
        safe_context={"channel_count": len(selected), "platform_only": platform_only},
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.contact_exchange.consent_updated",
            aggregate_type="matchmaking_contact_exchange",
            aggregate_id=exchange_id,
            payload={
                "contact_exchange_request_id": str(exchange_id),
                "recipient_user_ids": [str(other_user_id)],
            },
        )
    )
    await _reconcile(
        session, exchange_id=exchange_id, pair_id=exchange["pair_id"], request_id=request_id
    )
    refreshed = await _locked_request(session, exchange_id)
    return await member_view(session, request=refreshed, user_id=user_id)


async def _validate_selection(
    session: AsyncSession, *, user_id: UUID, selected_contact_point_ids: list[UUID]
) -> list[dict[str, Any]]:
    """Only the member's own verified contact points may be selected."""
    if not selected_contact_point_ids:
        return []
    verified = {
        item["id"]: item for item in await PrivacyGateway(session).verified_contact_points(user_id)
    }
    selected: list[dict[str, Any]] = []
    for contact_point_id in selected_contact_point_ids:
        item = verified.get(contact_point_id)
        if item is None:
            raise VavError(
                "CONTACT_POINT_NOT_VERIFIED",
                "You can only share a verified contact channel that belongs to you.",
                status_code=422,
            )
        selected.append(item)
    return selected


async def _consents(session: AsyncSession, exchange_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_contact_exchange_consents "
                "WHERE contact_exchange_request_id=:id ORDER BY created_at"
            ),
            {"id": exchange_id},
        )
    ).mappings()
    return [dict(row) for row in rows]


async def _reconcile(
    session: AsyncSession,
    *,
    exchange_id: UUID,
    pair_id: UUID,
    request_id: UUID | None = None,
) -> None:
    """Move the exchange to the state both consents currently justify."""
    consents = await _consents(session, exchange_id)
    consented = [c for c in consents if str(c["status"]) == ConsentStatus.CONSENTED.value]
    platform_only = [c for c in consents if str(c["status"]) == ConsentStatus.PLATFORM_ONLY.value]

    if len(consented) == 2:
        await _activate(
            session,
            exchange_id=exchange_id,
            consents=consented,
            pair_id=pair_id,
            request_id=request_id,
        )
        return

    if platform_only:
        # Someone chose to stay on the platform. That is a complete answer,
        # not a pending state, and it opens nothing.
        await _revoke_grants(session, exchange_id, reason="platform_only_preferred")
        await _set_status(session, exchange_id, ContactExchangeStatus.REQUESTED)
        return

    status = (
        ContactExchangeStatus.ONE_SIDE_CONSENTED
        if len(consented) == 1
        else ContactExchangeStatus.REQUESTED
    )
    await _set_status(session, exchange_id, status)


async def _set_status(
    session: AsyncSession, exchange_id: UUID, status: ContactExchangeStatus
) -> None:
    # ``is_active`` is passed separately rather than comparing :status inside
    # the CASE: reusing one parameter in a VARCHAR column and a text comparison
    # makes asyncpg unable to deduce a single type for it.
    await session.execute(
        text(
            "UPDATE matchmaking_contact_exchange_requests SET status=:status, "
            "consent_version=consent_version+1, updated_at=now(), "
            "activated_at=CASE WHEN :is_active THEN COALESCE(activated_at,now()) "
            "ELSE activated_at END WHERE id=:id"
        ),
        {
            "id": exchange_id,
            "status": status.value,
            "is_active": status is ContactExchangeStatus.ACTIVE,
        },
    )


async def _activate(
    session: AsyncSession,
    *,
    exchange_id: UUID,
    consents: list[dict[str, Any]],
    pair_id: UUID,
    request_id: UUID | None = None,
) -> None:
    """Create one grant per direction, scoped to what its owner chose."""
    for consent in consents:
        owner_user_id = consent["user_id"]
        viewer = next(c for c in consents if c["user_id"] != owner_user_id)
        ids = service.jsonb(consent["selected_contact_point_ids"]) or []
        hashes = service.jsonb(consent["contact_point_hash_snapshot"]) or {}
        settings = get_settings()
        expires_at = None
        if settings.matchmaking_contact_grant_default_ttl_days > 0:
            expires_at = service.now() + timedelta(
                days=settings.matchmaking_contact_grant_default_ttl_days
            )
        await session.execute(
            text(
                "INSERT INTO matchmaking_contact_exchange_grants "
                "(contact_exchange_request_id,viewer_user_id,owner_user_id,contact_point_ids,"
                "contact_hash_snapshot,status,expires_at) VALUES "
                "(:request,:viewer,:owner,CAST(:ids AS jsonb),CAST(:hashes AS jsonb),:status,:expires) "
                "ON CONFLICT (contact_exchange_request_id,viewer_user_id,owner_user_id) DO UPDATE SET "
                "contact_point_ids=EXCLUDED.contact_point_ids, "
                "contact_hash_snapshot=EXCLUDED.contact_hash_snapshot, "
                "status='active', suspended_at=NULL, revoked_at=NULL, revoke_reason=NULL, "
                "granted_at=now()"
            ),
            {
                "request": exchange_id,
                "viewer": viewer["user_id"],
                "owner": owner_user_id,
                "ids": json.dumps([str(i) for i in ids]),
                "hashes": json.dumps(hashes),
                "status": GrantStatus.ACTIVE.value,
                "expires": expires_at,
            },
        )
    await _set_status(session, exchange_id, ContactExchangeStatus.ACTIVE)
    await service.append_history(
        session,
        pair_id=pair_id,
        entity_type="contact_exchange",
        entity_id=exchange_id,
        action="activated",
        to_status=ContactExchangeStatus.ACTIVE.value,
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.contact_exchange.activated",
        subject_type="contact_exchange",
        subject_id=exchange_id,
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.contact_exchange.activated",
            aggregate_type="matchmaking_contact_exchange",
            aggregate_id=exchange_id,
            payload={
                "contact_exchange_request_id": str(exchange_id),
                "recipient_user_ids": [str(c["user_id"]) for c in consents],
            },
        )
    )


async def withdraw_consent(
    session: AsyncSession,
    *,
    user_id: UUID,
    exchange_id: UUID,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Stop future access to this member's channels."""
    service.enabled()
    exchange = await _locked_request(session, exchange_id)
    await _member_of(session, exchange, user_id)

    await session.execute(
        text(
            "UPDATE matchmaking_contact_exchange_consents SET status=:status, "
            "withdrawn_at=now(), selected_contact_point_ids='[]'::jsonb, "
            "contact_point_hash_snapshot='{}'::jsonb, updated_at=now() "
            "WHERE contact_exchange_request_id=:request AND user_id=:user"
        ),
        {"request": exchange_id, "user": user_id, "status": ConsentStatus.WITHDRAWN.value},
    )
    # Only this member's channels close. The other member's decision is theirs
    # to change, not this member's to revoke on their behalf.
    await _revoke_grants(session, exchange_id, reason="consent_withdrawn", owner_user_id=user_id)
    remaining = (
        await session.execute(
            text(
                "SELECT count(*) FROM matchmaking_contact_exchange_grants "
                "WHERE contact_exchange_request_id=:id AND status='active'"
            ),
            {"id": exchange_id},
        )
    ).scalar_one()
    await _set_status(
        session,
        exchange_id,
        ContactExchangeStatus.PARTIALLY_REVOKED
        if int(remaining or 0) > 0
        else ContactExchangeStatus.REVOKED,
    )
    await service.append_history(
        session,
        pair_id=exchange["pair_id"],
        entity_type="contact_exchange",
        entity_id=exchange_id,
        action="consent_withdrawn",
        actor_user_id=user_id,
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.contact_exchange.withdrawn",
        subject_type="contact_exchange",
        subject_id=exchange_id,
        actor_id=user_id,
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.contact_exchange.revoked",
            aggregate_type="matchmaking_contact_exchange",
            aggregate_id=exchange_id,
            payload={
                "contact_exchange_request_id": str(exchange_id),
                "note": "contact_exchange_authorisation_updated",
            },
        )
    )
    refreshed = await _locked_request(session, exchange_id)
    return await member_view(session, request=refreshed, user_id=user_id)


async def _revoke_grants(
    session: AsyncSession,
    exchange_id: UUID,
    *,
    reason: str,
    owner_user_id: UUID | None = None,
) -> None:
    """Revoke grants and kill every token they issued.

    Tokens are invalidated in the same statement batch as the grant, so a
    token handed out a second ago cannot be redeemed after revocation.
    """
    params: dict[str, Any] = {"id": exchange_id, "reason": reason}
    owner_clause = ""
    if owner_user_id is not None:
        owner_clause = " AND owner_user_id=:owner"
        params["owner"] = owner_user_id
    await session.execute(
        text(
            "UPDATE matchmaking_contact_reveal_tokens SET status='invalidated', "
            "invalidated_at=now() WHERE status='issued' AND grant_id IN "
            "(SELECT id FROM matchmaking_contact_exchange_grants "
            " WHERE contact_exchange_request_id=:id" + owner_clause + ")"
        ),
        params,
    )
    await session.execute(
        text(
            "UPDATE matchmaking_contact_exchange_grants SET status='revoked', "
            "revoked_at=now(), revoke_reason=:reason "
            "WHERE contact_exchange_request_id=:id AND status<>'revoked'" + owner_clause
        ),
        params,
    )


async def revoke_for_pair(session: AsyncSession, *, pair_id: UUID, reason: str) -> None:
    """Safety-driven revocation for every exchange on a pair."""
    rows = (
        await session.execute(
            text("SELECT id FROM matchmaking_contact_exchange_requests WHERE pair_id=:pair"),
            {"pair": pair_id},
        )
    ).mappings()
    for row in rows:
        await _revoke_grants(session, row["id"], reason=reason)
        await _set_status(session, row["id"], ContactExchangeStatus.INVALIDATED)


# --------------------------------------------------------------------------
# Reading contact details
# --------------------------------------------------------------------------


async def member_view(
    session: AsyncSession, *, request: dict[str, Any], user_id: UUID
) -> dict[str, Any]:
    """Masked values only. Plaintext needs a separate, audited reveal."""
    consents = await _consents(session, request["id"])
    own = next((c for c in consents if c["user_id"] == user_id), None)
    grant_rows = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_contact_exchange_grants "
                "WHERE contact_exchange_request_id=:id AND viewer_user_id=:viewer"
            ),
            {"id": request["id"], "viewer": user_id},
        )
    ).mappings()
    grant = grant_rows.first()

    contacts: list[dict[str, Any]] = []
    if grant is not None and str(grant["status"]) == GrantStatus.ACTIVE.value:
        privacy = PrivacyGateway(session)
        for contact_point_id in service.jsonb(grant["contact_point_ids"]) or []:
            point = await privacy.contact_point(
                UUID(str(contact_point_id)), owner_user_id=grant["owner_user_id"]
            )
            if point is None:
                continue
            stored_hash = (service.jsonb(grant["contact_hash_snapshot"]) or {}).get(
                str(contact_point_id)
            )
            current_hash = _contact_hash(str(point["contact_type"]), str(point["value_hmac"]))
            if stored_hash != current_hash:
                # The value changed after consent. Nothing is shown until its
                # owner confirms the new one.
                contacts.append(
                    {
                        "contact_point_id": str(contact_point_id),
                        "type": point["contact_type"],
                        "state": "awaiting_reconfirmation",
                    }
                )
                continue
            contacts.append(
                {
                    "contact_point_id": str(contact_point_id),
                    "type": point["contact_type"],
                    "state": "available",
                    "masked_value": _mask(
                        str(point["contact_type"]), decrypt_private(point["value_encrypted"])
                    ),
                }
            )

    return {
        "contact_exchange_request_id": str(request["id"]),
        "mutual_match_id": str(request["mutual_match_id"]),
        "status": request["status"],
        "policy": request["policy"],
        "consent_version": request["consent_version"],
        "your_consent": {
            "status": own["status"] if own else ConsentStatus.PENDING.value,
            "platform_only_preferred": bool(own["platform_only_preferred"]) if own else False,
            "selected_contact_point_ids": service.jsonb(own["selected_contact_point_ids"])
            if own
            else [],
        },
        # The other member's choice is reported as a state, never as a list of
        # what they picked before both sides agreed.
        "other_member_has_consented": any(
            c["user_id"] != user_id and str(c["status"]) == ConsentStatus.CONSENTED.value
            for c in consents
        ),
        "contacts": contacts,
        "disclosures": list(EXCHANGE_DISCLOSURES),
    }


async def get_exchange(
    session: AsyncSession, *, user_id: UUID, exchange_id: UUID
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text("SELECT * FROM matchmaking_contact_exchange_requests WHERE id=:id"),
            {"id": exchange_id},
        )
    ).mappings()
    found = rows.first()
    if found is None:
        raise VavError(
            "CONTACT_EXCHANGE_NOT_FOUND", "That contact exchange was not found.", status_code=404
        )
    request = dict(found)
    await _member_of(session, request, user_id)
    return await member_view(session, request=request, user_id=user_id)


async def issue_reveal_token(
    session: AsyncSession,
    *,
    user_id: UUID,
    exchange_id: UUID,
    contact_point_id: UUID,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Issue a short-lived, viewer-bound token for one channel."""
    service.enabled()
    settings = get_settings()
    exchange = await _locked_request(session, exchange_id)
    match = await _member_of(session, exchange, user_id)
    other_user_id = match_service.other_member(match, user_id)

    eligibility = await service.check_interaction_allowed(
        session,
        actor_user_id=user_id,
        target_user_id=other_user_id,
        # Contact exchange happens inside an accepted introduction, so the
        # relationship that acceptance created must not disqualify it.
        reject_existing_relationship=False,
    )
    eligibility.raise_for_member()

    grant_rows = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_contact_exchange_grants "
                "WHERE contact_exchange_request_id=:id AND viewer_user_id=:viewer "
                "AND status='active' FOR UPDATE"
            ),
            {"id": exchange_id, "viewer": user_id},
        )
    ).mappings()
    grant = grant_rows.first()
    if grant is None:
        raise VavError(
            "CONTACT_ACCESS_NOT_GRANTED",
            "You do not have access to this member's contact details.",
            status_code=403,
        )
    allowed_ids = {str(i) for i in (service.jsonb(grant["contact_point_ids"]) or [])}
    if str(contact_point_id) not in allowed_ids:
        raise VavError(
            "CONTACT_ACCESS_NOT_GRANTED",
            "That channel was not shared with you.",
            status_code=403,
        )

    point = await PrivacyGateway(session).contact_point(
        contact_point_id, owner_user_id=grant["owner_user_id"]
    )
    if point is None or str(point["status"]) != "verified":
        raise VavError("CONTACT_POINT_UNAVAILABLE", "That channel is unavailable.", status_code=409)
    stored_hash = (service.jsonb(grant["contact_hash_snapshot"]) or {}).get(str(contact_point_id))
    if stored_hash != _contact_hash(str(point["contact_type"]), str(point["value_hmac"])):
        await session.execute(
            text(
                "UPDATE matchmaking_contact_exchange_grants SET status='suspended', "
                "suspended_at=now() WHERE id=:id"
            ),
            {"id": grant["id"]},
        )
        raise VavError(
            "CONTACT_CONSENT_STALE",
            "This channel changed and needs to be confirmed again by its owner.",
            status_code=409,
        )

    token = secrets.token_urlsafe(32)
    expires_at = service.now() + timedelta(
        seconds=settings.matchmaking_contact_reveal_token_ttl_seconds
    )
    await session.execute(
        text(
            "INSERT INTO matchmaking_contact_reveal_tokens "
            "(grant_id,viewer_user_id,token_hash,contact_point_id,expires_at) VALUES "
            "(:grant,:viewer,:hash,:point,:expires)"
        ),
        {
            "grant": grant["id"],
            "viewer": user_id,
            "hash": _token_hash(token),
            "point": contact_point_id,
            "expires": expires_at,
        },
    )
    return {"reveal_token": token, "expires_at": expires_at}


async def reveal(
    session: AsyncSession,
    *,
    user_id: UUID,
    exchange_id: UUID,
    reveal_token: str,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Exchange a token for one plaintext value, once, with an audit row."""
    service.enabled()
    exchange = await _locked_request(session, exchange_id)
    match = await _member_of(session, exchange, user_id)
    other_user_id = match_service.other_member(match, user_id)

    rows = (
        await session.execute(
            text(
                "SELECT t.*, g.owner_user_id, g.status AS grant_status, "
                "g.contact_hash_snapshot "
                "FROM matchmaking_contact_reveal_tokens t "
                "JOIN matchmaking_contact_exchange_grants g ON g.id = t.grant_id "
                "WHERE t.token_hash=:hash AND g.contact_exchange_request_id=:exchange "
                "FOR UPDATE OF t"
            ),
            {"hash": _token_hash(reveal_token), "exchange": exchange_id},
        )
    ).mappings()
    token_row = rows.first()
    if token_row is None or token_row["viewer_user_id"] != user_id:
        # A token belonging to the other member is simply not valid here.
        await service.sensitive_access(
            session,
            actor_user_id=user_id,
            subject_user_id=other_user_id,
            asset_code="contact_point",
            purpose="member_contact_reveal",
            permission_code="member_self_service",
            result="denied",
            request_id=request_id,
        )
        raise VavError("REVEAL_TOKEN_INVALID", "That reveal link is not valid.", status_code=403)
    if str(token_row["status"]) != "issued" or token_row["expires_at"] <= service.now():
        raise VavError("REVEAL_TOKEN_EXPIRED", "That reveal link has expired.", status_code=409)
    if str(token_row["grant_status"]) != GrantStatus.ACTIVE.value:
        raise VavError(
            "CONTACT_ACCESS_REVOKED", "Access to this channel has ended.", status_code=403
        )

    point = await PrivacyGateway(session).contact_point(
        token_row["contact_point_id"], owner_user_id=token_row["owner_user_id"]
    )
    if point is None or str(point["status"]) != "verified":
        raise VavError("CONTACT_POINT_UNAVAILABLE", "That channel is unavailable.", status_code=409)

    stored_hash = (service.jsonb(token_row["contact_hash_snapshot"]) or {}).get(
        str(token_row["contact_point_id"])
    )
    current_hash = _contact_hash(str(point["contact_type"]), str(point["value_hmac"]))
    if stored_hash != current_hash:
        # A reveal token authorises only the exact value that both members
        # confirmed.  Re-check at consumption time so a token issued before a
        # contact edit can never expose the replacement value.
        await session.execute(
            text(
                "UPDATE matchmaking_contact_exchange_grants SET status='suspended', "
                "suspended_at=now() WHERE id=:grant"
            ),
            {"grant": token_row["grant_id"]},
        )
        await session.execute(
            text(
                "UPDATE matchmaking_contact_reveal_tokens SET status='invalidated', "
                "invalidated_at=now() WHERE id=:id AND status='issued'"
            ),
            {"id": token_row["id"]},
        )
        raise VavError(
            "CONTACT_CONSENT_STALE",
            "This channel changed and needs to be confirmed again by its owner.",
            status_code=409,
        )

    await session.execute(
        text(
            "UPDATE matchmaking_contact_reveal_tokens SET status='consumed', consumed_at=now() "
            "WHERE id=:id AND status='issued'"
        ),
        {"id": token_row["id"]},
    )
    await service.sensitive_access(
        session,
        actor_user_id=user_id,
        subject_user_id=token_row["owner_user_id"],
        asset_code="contact_point",
        purpose="member_contact_reveal",
        permission_code="member_self_service",
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.contact_exchange.revealed",
        subject_type="contact_exchange",
        subject_id=exchange_id,
        actor_id=user_id,
        safe_context={"contact_type": point["contact_type"]},
    )
    return {
        "type": point["contact_type"],
        "value": decrypt_private(point["value_encrypted"]),
        "disclosure": EXCHANGE_DISCLOSURES[2],
    }
