# ruff: noqa: B008, E501
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.notifications.crypto import stable_hash
from vav.modules.notifications.schemas import (
    ConsentRequest,
    UpdateNotificationPreferencesRequest,
)
from vav.modules.notifications.service import (
    _audit,
    consume_unsubscribe_token,
    receive_provider_webhook,
)

router = APIRouter()


def _enabled() -> None:
    if not get_settings().notification_enabled:
        raise VavError("NOTIFICATIONS_DISABLED", "Notifications are disabled.", status_code=503)


@router.get("/account/notifications")
async def list_notifications(
    request: Request,
    category: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    page: int = 1,
    page_size: int = 20,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _enabled()
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    clauses = ["user_id=:user_id", "status<>'withdrawn'", "status<>'archived'"]
    params: dict[str, Any] = {
        "user_id": principal.user.id,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    if category:
        clauses.append("category=:category")
        params["category"] = category
    if status:
        if status == "unread":
            clauses.append("read_at IS NULL")
        elif status in {"active", "read", "expired", "archived"}:
            clauses.append("status=:status")
            params["status"] = status
        else:
            raise VavError(
                "NOTIFICATION_FILTER_INVALID",
                "Notification status filter is invalid.",
                status_code=422,
            )
    if priority:
        clauses.append("priority=:priority")
        params["priority"] = priority
    where = " AND ".join(clauses)
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,category,priority,title,body,action_reference,action_url,status,"
                    "available_from,expires_at,read_at,created_at FROM user_notifications WHERE "
                    + where
                    + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    total = await session.scalar(
        text("SELECT count(*) FROM user_notifications WHERE " + where), params
    )
    now = datetime.now(UTC)
    return success(
        {
            "items": [
                {
                    **dict(row),
                    "id": str(row["id"]),
                    "expired": row["expires_at"] is not None and row["expires_at"] <= now,
                    "action_url": None
                    if row["expires_at"] is not None and row["expires_at"] <= now
                    else row["action_url"],
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": int(total or 0),
        },
        request_id_from_request(request),
    )


@router.get("/account/notifications/unread-count")
async def unread_count(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    count = await session.scalar(
        text(
            "SELECT count(*) FROM user_notifications WHERE user_id=:user_id AND read_at IS NULL "
            "AND status='active' AND available_from<=now() AND (expires_at IS NULL OR expires_at>now())"
        ),
        {"user_id": principal.user.id},
    )
    return success(
        {"count": int(count or 0), "source": "database"}, request_id_from_request(request)
    )


@router.get("/account/notifications/{notification_id}")
async def notification_detail(
    notification_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,category,priority,title,body,action_reference,action_url,status,"
                    "available_from,expires_at,read_at,archived_at,withdrawn_at,created_at "
                    "FROM user_notifications WHERE id=:id AND user_id=:user_id"
                ),
                {"id": notification_id, "user_id": principal.user.id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("NOTIFICATION_NOT_FOUND", "Notification was not found.", status_code=404)
    value = dict(row)
    value["id"] = str(value["id"])
    if value["status"] in {"withdrawn", "expired"} or (
        value["expires_at"] is not None and value["expires_at"] <= datetime.now(UTC)
    ):
        value["action_url"] = None
    return success(value, request_id_from_request(request))


@router.post("/account/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "UPDATE user_notifications SET read_at=COALESCE(read_at,now()),"
                    "status=CASE WHEN status='active' THEN 'read' ELSE status END "
                    "WHERE id=:id AND user_id=:user_id RETURNING id,read_at,status"
                ),
                {"id": notification_id, "user_id": principal.user.id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("NOTIFICATION_NOT_FOUND", "Notification was not found.", status_code=404)
    await _audit(
        session,
        "notification.in_app.read",
        "user_notification",
        notification_id,
        actor_id=principal.user.id,
    )
    await session.commit()
    return success(dict(row), request_id_from_request(request))


@router.post("/account/notifications/mark-all-read")
async def mark_all_notifications_read(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await session.execute(
        text(
            "UPDATE user_notifications SET read_at=now(),status='read' WHERE user_id=:user_id "
            "AND status='active' AND read_at IS NULL"
        ),
        {"user_id": principal.user.id},
    )
    await session.commit()
    return success(
        {"updated": int(getattr(result, "rowcount", 0) or 0)},
        request_id_from_request(request),
    )


@router.post("/account/notifications/{notification_id}/archive")
async def archive_notification(
    notification_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE user_notifications SET status='archived',archived_at=COALESCE(archived_at,now()) "
            "WHERE id=:id AND user_id=:user_id AND status<>'withdrawn' RETURNING id"
        ),
        {"id": notification_id, "user_id": principal.user.id},
    )
    if value is None:
        raise VavError("NOTIFICATION_NOT_FOUND", "Notification was not found.", status_code=404)
    await _audit(
        session,
        "notification.in_app.archived",
        "user_notification",
        notification_id,
        actor_id=principal.user.id,
    )
    await session.commit()
    return success(
        {"id": str(notification_id), "status": "archived"}, request_id_from_request(request)
    )


@router.get("/account/notification-preferences")
async def notification_preferences(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT category,channel,enabled,frequency,quiet_hours_enabled,quiet_hours_start,"
                    "quiet_hours_end,quiet_hours_timezone,version,updated_at FROM notification_preferences "
                    "WHERE user_id=:user_id ORDER BY category,channel"
                ),
                {"user_id": principal.user.id},
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "items": [dict(row) for row in rows],
            "mandatory_categories": ["security", "order", "payment"],
        },
        request_id_from_request(request),
    )


@router.put("/account/notification-preferences")
async def update_notification_preferences(
    payload: UpdateNotificationPreferencesRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    mandatory = {"security", "order", "payment"}
    for item in payload.items:
        if item.category.value in mandatory and (
            not item.enabled or item.frequency.value == "disabled"
        ):
            raise VavError(
                "NOTIFICATION_MANDATORY_PREFERENCE",
                "Security and payment notifications cannot be disabled.",
                status_code=409,
            )
        if item.quiet_hours_enabled and (
            item.quiet_hours_start is None
            or item.quiet_hours_end is None
            or item.quiet_hours_timezone is None
        ):
            raise VavError(
                "NOTIFICATION_QUIET_HOURS_INCOMPLETE",
                "Quiet hours require start, end and IANA timezone.",
                status_code=422,
            )
        await session.execute(
            text(
                "INSERT INTO notification_preferences "
                "(user_id,category,channel,enabled,frequency,quiet_hours_enabled,quiet_hours_start,"
                "quiet_hours_end,quiet_hours_timezone,source) VALUES (:user_id,:category,:channel,"
                ":enabled,:frequency,:quiet_enabled,:quiet_start,:quiet_end,:timezone,'user') "
                "ON CONFLICT (user_id,category,channel) DO UPDATE SET enabled=EXCLUDED.enabled,"
                "frequency=EXCLUDED.frequency,quiet_hours_enabled=EXCLUDED.quiet_hours_enabled,"
                "quiet_hours_start=EXCLUDED.quiet_hours_start,quiet_hours_end=EXCLUDED.quiet_hours_end,"
                "quiet_hours_timezone=EXCLUDED.quiet_hours_timezone,source='user',"
                "version=notification_preferences.version+1,updated_at=now()"
            ),
            {
                "user_id": principal.user.id,
                "category": item.category.value,
                "channel": item.channel,
                "enabled": item.enabled,
                "frequency": item.frequency.value,
                "quiet_enabled": item.quiet_hours_enabled,
                "quiet_start": item.quiet_hours_start,
                "quiet_end": item.quiet_hours_end,
                "timezone": item.quiet_hours_timezone,
            },
        )
    await _audit(
        session,
        "notification.preference.updated",
        "user",
        principal.user.id,
        actor_id=principal.user.id,
        context={"item_count": len(payload.items)},
    )
    await session.commit()
    return success({"updated": len(payload.items)}, request_id_from_request(request))


@router.get("/account/notification-consents")
async def notification_consents(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT consent_type,consent_version,status,granted_at,withdrawn_at,source,updated_at "
                    "FROM notification_consents WHERE user_id=:user_id ORDER BY updated_at DESC"
                ),
                {"user_id": principal.user.id},
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


async def _set_consent(
    *,
    consent_type: str,
    granted: bool,
    payload: ConsentRequest,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    if consent_type != "marketing_email":
        raise VavError(
            "NOTIFICATION_CONSENT_TYPE_INVALID", "Consent type is not supported.", status_code=422
        )
    status = "granted" if granted else "withdrawn"
    await session.execute(
        text(
            "INSERT INTO notification_consents "
            "(user_id,consent_type,consent_version,status,granted_at,withdrawn_at,source,evidence) "
            "VALUES (:user_id,:type,:version,:status,CASE WHEN :granted THEN now() END,"
            "CASE WHEN :granted THEN NULL ELSE now() END,'account_settings',CAST(:evidence AS jsonb)) "
            "ON CONFLICT (user_id,consent_type,consent_version) DO UPDATE SET status=EXCLUDED.status,"
            "granted_at=EXCLUDED.granted_at,withdrawn_at=EXCLUDED.withdrawn_at,"
            "source=EXCLUDED.source,evidence=EXCLUDED.evidence,updated_at=now()"
        ),
        {
            "user_id": principal.user.id,
            "type": consent_type,
            "version": payload.consent_version,
            "status": status,
            "granted": granted,
            "evidence": __import__("json").dumps(payload.evidence),
        },
    )
    if not granted:
        await session.execute(
            text(
                "INSERT INTO notification_preferences "
                "(user_id,category,channel,enabled,frequency,source) "
                "VALUES (:user_id,'marketing','email',false,'disabled','consent_withdrawal') "
                "ON CONFLICT (user_id,category,channel) DO UPDATE SET enabled=false,frequency='disabled',"
                "source='consent_withdrawal',version=notification_preferences.version+1,updated_at=now()"
            ),
            {"user_id": principal.user.id},
        )
    await _audit(
        session,
        "notification.consent.granted" if granted else "notification.consent.withdrawn",
        "user",
        principal.user.id,
        actor_id=principal.user.id,
        context={"consent_type": consent_type, "consent_version": payload.consent_version},
    )
    await session.commit()
    return success(
        {"consent_type": consent_type, "status": status}, request_id_from_request(request)
    )


@router.post("/account/notification-consents/{consent_type}/grant")
async def grant_notification_consent(
    consent_type: str,
    payload: ConsentRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _set_consent(
        consent_type=consent_type,
        granted=True,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/account/notification-consents/{consent_type}/withdraw")
async def withdraw_notification_consent(
    consent_type: str,
    payload: ConsentRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _set_consent(
        consent_type=consent_type,
        granted=False,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.get("/public/notifications/unsubscribe/{token}")
async def unsubscribe_preview(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT category,channel,expires_at,consumed_at FROM notification_unsubscribe_tokens "
                    "WHERE token_hash=:token_hash"
                ),
                {"token_hash": stable_hash(token)},
            )
        )
        .mappings()
        .first()
    )
    valid = bool(
        row
        and row["consumed_at"] is None
        and (row["expires_at"] is None or row["expires_at"] > datetime.now(UTC))
    )
    category = row["category"] if row is not None and valid else None
    channel = row["channel"] if row is not None and valid else None
    return success(
        {
            "valid": valid,
            "category": category,
            "channel": channel,
        },
        request_id_from_request(request),
    )


@router.post("/public/notifications/unsubscribe/{token}")
async def unsubscribe(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await consume_unsubscribe_token(session, token)
    return success(result, request_id_from_request(request))


@router.post("/webhooks/email/{provider}", status_code=202)
async def email_provider_webhook(
    provider: str,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    raw_body = await request.body()
    result = await receive_provider_webhook(
        session,
        provider_name=provider,
        headers={key.lower(): value for key, value in request.headers.items()},
        raw_body=raw_body,
    )
    return success(result, request_id_from_request(request))
