# ruff: noqa: B008, E501
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.notifications.crypto import decrypt_notification_data, stable_hash
from vav.modules.notifications.rendering import (
    render_template,
    validate_template_source,
    validate_variable_schema,
)
from vav.modules.notifications.schemas import (
    CampaignActionRequest,
    CampaignRequest,
    IngestNotificationEventRequest,
    ReminderRequest,
    StatusReasonRequest,
    SuppressionRequest,
    TemplateDefinitionRequest,
    TemplatePreviewRequest,
    TemplateReleaseRequest,
)
from vav.modules.notifications.service import (
    _audit,
    consume_outbox_events,
    dispatch_campaign_batch,
    dispatch_digest_window,
    dispatch_due_reminders,
    generate_campaign_audience,
    ingest_event,
    process_due_deliveries,
    replan_reminder,
    validate_campaign_audience,
)

router = APIRouter()


class RegistryStatusRequest(BaseModel):
    status: Literal["active", "disabled"]
    reason: str = Field(min_length=8, max_length=1000)


class TemplateTestSendRequest(BaseModel):
    variables: dict[str, Any]
    recipient: str | None = Field(default=None, max_length=320)


@router.post("/internal/notifications/events", status_code=202)
async def receive_domain_event(
    payload: IngestNotificationEventRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.subscriptions.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await ingest_event(session, payload)
    return success(result, request_id_from_request(request))


@router.get("/admin/notifications/dashboard")
async def notification_dashboard(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.analytics.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    delivery_rows = list(
        (
            await session.execute(
                text("SELECT status,count(*) AS count FROM notification_deliveries GROUP BY status")
            )
        )
        .mappings()
        .all()
    )
    metrics = {str(row["status"]): int(row["count"]) for row in delivery_rows}
    unread = await session.scalar(
        text("SELECT count(*) FROM user_notifications WHERE read_at IS NULL AND status='active'")
    )
    open_dead_letters = await session.scalar(
        text("SELECT count(*) FROM notification_dead_letters WHERE status='open'")
    )
    active_suppressions = await session.scalar(
        text("SELECT count(*) FROM notification_suppressions WHERE status='active'")
    )
    campaign_rows = list(
        (
            await session.execute(
                text("SELECT status,count(*) AS count FROM notification_campaigns GROUP BY status")
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "deliveries": metrics,
            "in_app_unread": int(unread or 0),
            "dead_letters_open": int(open_dead_letters or 0),
            "active_suppressions": int(active_suppressions or 0),
            "campaigns": {str(row["status"]): int(row["count"]) for row in campaign_rows},
            "provider_status": get_settings().notification_email_provider,
            "content_redacted": True,
        },
        request_id_from_request(request),
    )


@router.get("/admin/notifications/templates")
async def list_templates(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.templates.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT d.id,d.template_code,d.internal_name,d.category,d.purpose,d.status,d.updated_at,"
                    "count(r.id) AS release_count,count(r.id) FILTER (WHERE r.status='active') AS active_count "
                    "FROM notification_template_definitions d LEFT JOIN notification_template_releases r "
                    "ON r.template_definition_id=d.id GROUP BY d.id ORDER BY d.template_code"
                )
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


@router.post("/admin/notifications/templates", status_code=201)
async def create_template(
    payload: TemplateDefinitionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.templates.create")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    validate_variable_schema(payload.variable_schema, {}) if not payload.variable_schema.get(
        "required"
    ) else None
    if (
        payload.variable_schema.get("type") != "object"
        or payload.variable_schema.get("additionalProperties") is not False
    ):
        raise VavError(
            "NOTIFICATION_TEMPLATE_SCHEMA_UNSAFE",
            "Template schemas must be closed object schemas.",
            status_code=422,
        )
    value = await session.scalar(
        text(
            "INSERT INTO notification_template_definitions "
            "(template_code,internal_name,category,purpose,variable_schema,required_channels,"
            "supported_channels,status) VALUES (:code,:name,:category,:purpose,CAST(:schema AS jsonb),"
            "CAST(:required AS jsonb),CAST(:supported AS jsonb),'active') RETURNING id"
        ),
        {
            "code": payload.template_code,
            "name": payload.internal_name,
            "category": payload.category.value,
            "purpose": payload.purpose,
            "schema": json.dumps(payload.variable_schema),
            "required": json.dumps(payload.required_channels),
            "supported": json.dumps(payload.supported_channels),
        },
    )
    template_id = UUID(str(value))
    await _audit(
        session,
        "notification.template.created",
        "notification_template",
        template_id,
        actor_id=principal.user.id,
    )
    await session.commit()
    return success({"id": str(template_id)}, request_id_from_request(request))


@router.get("/admin/notifications/templates/{template_id}")
async def template_detail(
    template_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.templates.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    definition = (
        (
            await session.execute(
                text("SELECT * FROM notification_template_definitions WHERE id=:id"),
                {"id": template_id},
            )
        )
        .mappings()
        .first()
    )
    if definition is None:
        raise VavError(
            "NOTIFICATION_TEMPLATE_NOT_FOUND", "Template was not found.", status_code=404
        )
    releases = list(
        (
            await session.execute(
                text(
                    "SELECT id,semantic_version,locale,channel,status,checksum_sha256,created_by,"
                    "approved_by,created_at,approved_at,activated_at FROM notification_template_releases "
                    "WHERE template_definition_id=:id ORDER BY created_at DESC"
                ),
                {"id": template_id},
            )
        )
        .mappings()
        .all()
    )
    return success(
        {"definition": dict(definition), "releases": [dict(row) for row in releases]},
        request_id_from_request(request),
    )


@router.post("/admin/notifications/templates/{template_id}/releases", status_code=201)
async def create_template_release(
    template_id: UUID,
    payload: TemplateReleaseRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.templates.update")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    definition = (
        (
            await session.execute(
                text(
                    "SELECT variable_schema,supported_channels FROM notification_template_definitions WHERE id=:id"
                ),
                {"id": template_id},
            )
        )
        .mappings()
        .first()
    )
    if definition is None:
        raise VavError(
            "NOTIFICATION_TEMPLATE_NOT_FOUND", "Template was not found.", status_code=404
        )
    if payload.channel not in definition["supported_channels"]:
        raise VavError(
            "NOTIFICATION_TEMPLATE_CHANNEL_INVALID",
            "Template channel is unsupported.",
            status_code=422,
        )
    for source in [
        payload.subject_template,
        payload.title_template,
        payload.body_html_template,
        payload.body_text_template,
        payload.action_label_template,
        payload.action_url_template,
    ]:
        validate_template_source(source)
    if payload.channel == "email" and (
        not payload.subject_template
        or not payload.body_html_template
        or not payload.body_text_template
    ):
        raise VavError(
            "NOTIFICATION_EMAIL_TEMPLATE_INCOMPLETE",
            "Email templates require subject, HTML and plain text.",
            status_code=422,
        )
    checksum = hashlib.sha256(
        json.dumps(payload.model_dump(), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    value = await session.scalar(
        text(
            "INSERT INTO notification_template_releases "
            "(template_definition_id,semantic_version,locale,channel,subject_template,title_template,"
            "body_html_template,body_text_template,action_label_template,action_url_template,"
            "checksum_sha256,status,created_by) VALUES (:definition_id,:version,:locale,:channel,"
            ":subject,:title,:html,:text,:action_label,:action_url,:checksum,'draft',:created_by) RETURNING id"
        ),
        {
            "definition_id": template_id,
            "version": payload.semantic_version,
            "locale": payload.locale,
            "channel": payload.channel,
            "subject": payload.subject_template,
            "title": payload.title_template,
            "html": payload.body_html_template,
            "text": payload.body_text_template,
            "action_label": payload.action_label_template,
            "action_url": payload.action_url_template,
            "checksum": checksum,
            "created_by": principal.user.id,
        },
    )
    release_id = UUID(str(value))
    await _audit(
        session,
        "notification.template.release_created",
        "notification_template_release",
        release_id,
        actor_id=principal.user.id,
    )
    await session.commit()
    return success(
        {"id": str(release_id), "checksum_sha256": checksum}, request_id_from_request(request)
    )


async def _template_transition(
    *,
    release_id: UUID,
    target: str,
    allowed: set[str],
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM notification_template_releases WHERE id=:id FOR UPDATE"),
                {"id": release_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "NOTIFICATION_TEMPLATE_RELEASE_NOT_FOUND",
            "Template release was not found.",
            status_code=404,
        )
    if row["status"] not in allowed:
        raise VavError(
            "NOTIFICATION_TEMPLATE_STATE_INVALID",
            "Template release transition is invalid.",
            status_code=409,
        )
    if target == "active":
        if row["status"] != "approved":
            raise VavError(
                "NOTIFICATION_TEMPLATE_NOT_APPROVED",
                "Only approved releases may activate.",
                status_code=409,
            )
        await session.execute(
            text(
                "UPDATE notification_template_releases SET status='superseded' WHERE template_definition_id=:definition_id "
                "AND locale=:locale AND channel=:channel AND status='active'"
            ),
            {
                "definition_id": row["template_definition_id"],
                "locale": row["locale"],
                "channel": row["channel"],
            },
        )
    await session.execute(
        text(
            "UPDATE notification_template_releases SET status=:target,"
            "approved_by=CASE WHEN :target='approved' THEN :actor ELSE approved_by END,"
            "approved_at=CASE WHEN :target='approved' THEN now() ELSE approved_at END,"
            "activated_at=CASE WHEN :target='active' THEN now() ELSE activated_at END WHERE id=:id"
        ),
        {"target": target, "actor": principal.user.id, "id": release_id},
    )
    event = {
        "in_review": "notification.template.updated",
        "approved": "notification.template.approved",
        "active": "notification.template.activated",
        "revoked": "notification.template.rolled_back",
    }[target]
    await _audit(
        session, event, "notification_template_release", release_id, actor_id=principal.user.id
    )
    await session.commit()
    return success({"id": str(release_id), "status": target}, request_id_from_request(request))


@router.post("/admin/notifications/template-releases/{release_id}/submit-review")
async def submit_template_review(
    release_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.templates.update")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _template_transition(
        release_id=release_id,
        target="in_review",
        allowed={"draft"},
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/notifications/template-releases/{release_id}/approve")
async def approve_template_release(
    release_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.templates.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _template_transition(
        release_id=release_id,
        target="approved",
        allowed={"in_review"},
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/notifications/template-releases/{release_id}/activate")
async def activate_template_release(
    release_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.templates.activate")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _template_transition(
        release_id=release_id,
        target="active",
        allowed={"approved"},
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/notifications/template-releases/{release_id}/revoke")
async def revoke_template_release(
    release_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.templates.rollback")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _template_transition(
        release_id=release_id,
        target="revoked",
        allowed={"active", "superseded"},
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/notifications/template-releases/{release_id}/preview")
async def preview_template_release(
    release_id: UUID,
    payload: TemplatePreviewRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.templates.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT r.*,d.variable_schema FROM notification_template_releases r "
                    "JOIN notification_template_definitions d ON d.id=r.template_definition_id WHERE r.id=:id"
                ),
                {"id": release_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "NOTIFICATION_TEMPLATE_RELEASE_NOT_FOUND",
            "Template release was not found.",
            status_code=404,
        )
    rendered = render_template(
        schema=row["variable_schema"],
        variables=payload.variables,
        subject_template=row["subject_template"],
        title_template=row["title_template"],
        body_html_template=row["body_html_template"],
        body_text_template=row["body_text_template"],
        action_label_template=row["action_label_template"],
        action_url_template=row["action_url_template"],
    )
    return success(rendered.__dict__, request_id_from_request(request))


@router.get("/admin/notifications/event-subscriptions")
async def event_subscriptions(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.subscriptions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text("SELECT * FROM notification_event_subscriptions ORDER BY subscription_code")
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


@router.patch("/admin/notifications/event-subscriptions/{subscription_id}")
async def update_event_subscription(
    subscription_id: UUID,
    payload: RegistryStatusRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.subscriptions.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE notification_event_subscriptions SET status=:status,updated_at=now() WHERE id=:id RETURNING id"
        ),
        {"status": payload.status, "id": subscription_id},
    )
    if value is None:
        raise VavError(
            "NOTIFICATION_SUBSCRIPTION_NOT_FOUND",
            "Event subscription was not found.",
            status_code=404,
        )
    await _audit(
        session,
        "notification.subscription.updated",
        "notification_subscription",
        subscription_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"id": str(subscription_id), "status": payload.status}, request_id_from_request(request)
    )


@router.get("/admin/notifications/deliveries")
async def list_deliveries(
    request: Request,
    status: str | None = None,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.deliveries.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    clauses = ["1=1"]
    params: dict[str, Any] = {}
    if status:
        clauses.append("d.status=:status")
        params["status"] = status
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT d.id,d.channel,d.locale,d.status,d.provider,d.provider_message_id,d.attempt_count,"
                    "d.created_at,d.sent_at,d.delivered_at,d.deduplication_key,i.notification_type,"
                    "('user-'||left(d.user_id::text,8)) AS user_anonymous_id FROM notification_deliveries d "
                    "JOIN notification_intents i ON i.id=d.notification_intent_id WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY d.created_at DESC LIMIT 200"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    return success(
        {"items": [dict(row) for row in rows], "content_redacted": True},
        request_id_from_request(request),
    )


@router.get("/admin/notifications/deliveries/{delivery_id}")
async def delivery_detail(
    delivery_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.deliveries.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    delivery = (
        (
            await session.execute(
                text(
                    "SELECT d.id,d.channel,d.locale,d.status,d.provider,d.provider_message_id,d.attempt_count,"
                    "d.created_at,d.updated_at,d.sent_at,d.delivered_at,d.next_attempt_at,d.deduplication_key,"
                    "i.notification_type,i.category,r.semantic_version FROM notification_deliveries d "
                    "JOIN notification_intents i ON i.id=d.notification_intent_id "
                    "JOIN notification_template_releases r ON r.id=d.template_release_id WHERE d.id=:id"
                ),
                {"id": delivery_id},
            )
        )
        .mappings()
        .first()
    )
    if delivery is None:
        raise VavError(
            "NOTIFICATION_DELIVERY_NOT_FOUND", "Delivery was not found.", status_code=404
        )
    attempts = list(
        (
            await session.execute(
                text(
                    "SELECT attempt_number,provider,status,provider_response_code,error_class,error_code,"
                    "error_message_safe,started_at,completed_at FROM notification_delivery_attempts "
                    "WHERE delivery_id=:id ORDER BY attempt_number"
                ),
                {"id": delivery_id},
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "delivery": dict(delivery),
            "attempts": [dict(row) for row in attempts],
            "content_redacted": True,
        },
        request_id_from_request(request),
    )


@router.post("/admin/notifications/deliveries/{delivery_id}/sensitive-view")
async def delivery_content(
    delivery_id: UUID,
    payload: StatusReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.deliveries.content.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT subject_rendered_encrypted,body_html_rendered_encrypted,body_text_rendered_encrypted "
                    "FROM notification_deliveries WHERE id=:id"
                ),
                {"id": delivery_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "NOTIFICATION_DELIVERY_NOT_FOUND", "Delivery was not found.", status_code=404
        )
    await _audit(
        session,
        "notification.delivery.content_viewed",
        "notification_delivery",
        delivery_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {
            "subject": decrypt_notification_data(row["subject_rendered_encrypted"]),
            "html": decrypt_notification_data(row["body_html_rendered_encrypted"]),
            "text": decrypt_notification_data(row["body_text_rendered_encrypted"]),
        },
        request_id_from_request(request),
    )


@router.post("/admin/notifications/deliveries/{delivery_id}/retry")
async def retry_delivery(
    delivery_id: UUID,
    payload: StatusReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.deliveries.retry")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE notification_deliveries SET status='failed_retryable',next_attempt_at=now(),updated_at=now() "
            "WHERE id=:id AND status IN ('failed_final','failed_retryable','deferred') "
            "AND (expires_at IS NULL OR expires_at>now()) RETURNING id"
        ),
        {"id": delivery_id},
    )
    if value is None:
        raise VavError(
            "NOTIFICATION_DELIVERY_RETRY_INVALID", "Delivery cannot be retried.", status_code=409
        )
    await _audit(
        session,
        "notification.delivery.retried",
        "notification_delivery",
        delivery_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"id": str(delivery_id), "status": "failed_retryable"}, request_id_from_request(request)
    )


@router.post("/admin/notifications/workers/deliveries/run")
async def run_delivery_worker(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.deliveries.retry")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    results = await process_due_deliveries(session)
    return success({"items": results, "processed": len(results)}, request_id_from_request(request))


@router.post("/admin/notifications/workers/outbox/run")
async def run_outbox_consumer(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.subscriptions.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    results = await consume_outbox_events(session)
    return success({"items": results, "processed": len(results)}, request_id_from_request(request))


@router.post("/admin/notifications/workers/digests/{frequency}/{window_key}/run")
async def run_digest_worker(
    frequency: str,
    window_key: str,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.reminders.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await dispatch_digest_window(session, frequency=frequency, window_key=window_key)
    return success(result, request_id_from_request(request))


@router.get("/admin/notifications/dead-letters")
async def dead_letters(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.dead_letters.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text("SELECT * FROM notification_dead_letters ORDER BY created_at DESC LIMIT 200")
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


@router.post("/admin/notifications/dead-letters/{dead_letter_id}/resolve")
async def resolve_dead_letter(
    dead_letter_id: UUID,
    payload: StatusReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.dead_letters.resolve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE notification_dead_letters SET status='resolved',resolved_at=now(),"
            "resolution_reason=:reason WHERE id=:id AND status='open' RETURNING id"
        ),
        {"reason": payload.reason, "id": dead_letter_id},
    )
    if value is None:
        raise VavError(
            "NOTIFICATION_DEAD_LETTER_NOT_OPEN", "Dead Letter is not open.", status_code=409
        )
    await _audit(
        session,
        "notification.dead_letter.resolved",
        "notification_dead_letter",
        dead_letter_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"id": str(dead_letter_id), "status": "resolved"}, request_id_from_request(request)
    )


@router.get("/admin/notifications/reminders")
async def reminders(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.reminders.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text("SELECT * FROM notification_reminders ORDER BY trigger_at DESC LIMIT 200")
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


@router.post("/admin/notifications/reminders", status_code=201)
async def create_reminder(
    payload: ReminderRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.reminders.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await replan_reminder(
        session,
        reminder_type=payload.reminder_type,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        recipient_user_id=payload.recipient_user_id,
        template_code=payload.template_code,
        category=payload.category.value,
        trigger_at=payload.trigger_at,
        timezone_name=payload.timezone,
        reference_version=payload.trigger_reference_version,
        deduplication_key=payload.deduplication_key,
    )
    return success({"id": str(value), "status": "scheduled"}, request_id_from_request(request))


@router.post("/admin/notifications/reminders/{reminder_id}/cancel")
async def cancel_reminder(
    reminder_id: UUID,
    payload: StatusReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.reminders.cancel")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE notification_reminders SET status='cancelled',updated_at=now() WHERE id=:id AND status IN ('planned','scheduled') RETURNING id"
        ),
        {"id": reminder_id},
    )
    if value is None:
        raise VavError(
            "NOTIFICATION_REMINDER_CANCEL_INVALID", "Reminder cannot be cancelled.", status_code=409
        )
    await _audit(
        session,
        "notification.reminder.cancelled",
        "notification_reminder",
        reminder_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"id": str(reminder_id), "status": "cancelled"}, request_id_from_request(request)
    )


@router.post("/admin/notifications/workers/reminders/run")
async def run_reminder_worker(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.reminders.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    results = await dispatch_due_reminders(session)
    return success({"items": results, "processed": len(results)}, request_id_from_request(request))


@router.get("/admin/notifications/campaigns")
async def campaigns(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.campaigns.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text("SELECT * FROM notification_campaigns ORDER BY created_at DESC LIMIT 200")
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


@router.post("/admin/notifications/campaigns", status_code=201)
async def create_campaign(
    payload: CampaignRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.campaigns.create")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    validate_campaign_audience(payload.audience_definition)
    if payload.category.value != "marketing" and "marketing_consent" in payload.audience_definition:
        raise VavError(
            "NOTIFICATION_CAMPAIGN_CATEGORY_INVALID",
            "Consent filters must match campaign purpose.",
            status_code=422,
        )
    value = await session.scalar(
        text(
            "INSERT INTO notification_campaigns "
            "(campaign_code,internal_name,campaign_type,category,status,template_code,template_release_manifest,"
            "audience_definition,channel_policy,scheduled_at,rate_limit_per_minute,batch_size,created_by) "
            "VALUES (:code,:name,:type,:category,'draft',:template,'{}'::jsonb,CAST(:audience AS jsonb),"
            "CAST(:channels AS jsonb),:scheduled,:rate,:batch,:actor) RETURNING id"
        ),
        {
            "code": payload.campaign_code,
            "name": payload.internal_name,
            "type": payload.campaign_type,
            "category": payload.category.value,
            "template": payload.template_code,
            "audience": json.dumps(payload.audience_definition),
            "channels": json.dumps(payload.channel_policy),
            "scheduled": payload.scheduled_at,
            "rate": payload.rate_limit_per_minute,
            "batch": payload.batch_size,
            "actor": principal.user.id,
        },
    )
    campaign_id = UUID(str(value))
    await _audit(
        session,
        "notification.campaign.created",
        "notification_campaign",
        campaign_id,
        actor_id=principal.user.id,
    )
    await session.commit()
    return success({"id": str(campaign_id), "status": "draft"}, request_id_from_request(request))


@router.post("/admin/notifications/campaigns/{campaign_id}/test-send")
async def campaign_test_send(
    campaign_id: UUID,
    payload: CampaignActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.campaigns.update")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE notification_campaigns SET test_send_completed_at=now() WHERE id=:id AND status='draft' RETURNING id"
        ),
        {"id": campaign_id},
    )
    if value is None:
        raise VavError(
            "NOTIFICATION_CAMPAIGN_TEST_INVALID",
            "Campaign test send is unavailable.",
            status_code=409,
        )
    await _audit(
        session,
        "notification.template.test_sent",
        "notification_campaign",
        campaign_id,
        actor_id=principal.user.id,
        reason=payload.reason,
        context={"recipient": "verified-current-admin", "test_marker": "[TEST]"},
    )
    await session.commit()
    return success(
        {"id": str(campaign_id), "test_send": "recorded", "subject_prefix": "[TEST]"},
        request_id_from_request(request),
    )


@router.post("/admin/notifications/campaigns/{campaign_id}/submit-review")
async def submit_campaign_review(
    campaign_id: UUID,
    payload: CampaignActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.campaigns.update")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE notification_campaigns SET status='in_review',release_reason=:reason WHERE id=:id AND status='draft' AND test_send_completed_at IS NOT NULL RETURNING id"
        ),
        {"reason": payload.reason, "id": campaign_id},
    )
    if value is None:
        raise VavError(
            "NOTIFICATION_CAMPAIGN_REVIEW_INVALID",
            "Campaign needs a test send before review.",
            status_code=409,
        )
    await session.commit()
    return success(
        {"id": str(campaign_id), "status": "in_review"}, request_id_from_request(request)
    )


@router.post("/admin/notifications/campaigns/{campaign_id}/approve")
async def approve_campaign(
    campaign_id: UUID,
    payload: CampaignActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.campaigns.approve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    campaign = (
        (
            await session.execute(
                text("SELECT * FROM notification_campaigns WHERE id=:id FOR UPDATE"),
                {"id": campaign_id},
            )
        )
        .mappings()
        .first()
    )
    if campaign is None or campaign["status"] != "in_review":
        raise VavError(
            "NOTIFICATION_CAMPAIGN_APPROVAL_INVALID",
            "Campaign is not awaiting approval.",
            status_code=409,
        )
    if campaign["created_by"] == principal.user.id and get_settings().environment != "development":
        raise VavError(
            "NOTIFICATION_CAMPAIGN_SELF_APPROVAL_FORBIDDEN",
            "Campaign creators cannot approve their own campaign.",
            status_code=403,
        )
    await session.execute(
        text(
            "UPDATE notification_campaigns SET status='approved',approved_by=:actor,approved_at=now() WHERE id=:id"
        ),
        {"actor": principal.user.id, "id": campaign_id},
    )
    await _audit(
        session,
        "notification.campaign.approved",
        "notification_campaign",
        campaign_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"id": str(campaign_id), "status": "approved"}, request_id_from_request(request))


@router.post("/admin/notifications/campaigns/{campaign_id}/audience")
async def create_campaign_audience(
    campaign_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.campaigns.schedule")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await generate_campaign_audience(session, campaign_id, actor_id=principal.user.id)
    return success(result, request_id_from_request(request))


async def _campaign_state_action(
    *,
    campaign_id: UUID,
    payload: CampaignActionRequest,
    target: str,
    allowed: set[str],
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    campaign = (
        (
            await session.execute(
                text(
                    "SELECT campaign_code,status FROM notification_campaigns WHERE id=:id FOR UPDATE"
                ),
                {"id": campaign_id},
            )
        )
        .mappings()
        .first()
    )
    if campaign is None or campaign["status"] not in allowed:
        raise VavError(
            "NOTIFICATION_CAMPAIGN_STATE_INVALID",
            "Campaign state transition is invalid.",
            status_code=409,
        )
    if (
        target in {"sending", "cancelled"}
        and payload.confirmation_code != campaign["campaign_code"]
    ):
        raise VavError(
            "NOTIFICATION_CAMPAIGN_CONFIRMATION_INVALID",
            "Campaign code confirmation is required.",
            status_code=409,
        )
    timestamp_column = {
        "sending": "started_at",
        "paused": "paused_at",
        "cancelled": "cancelled_at",
    }[target]
    await session.execute(
        text(
            f"UPDATE notification_campaigns SET status=:target,{timestamp_column}=now() WHERE id=:id"
        ),
        {"target": target, "id": campaign_id},
    )
    if target == "cancelled":
        await session.execute(
            text(
                "UPDATE notification_campaign_recipients SET status='cancelled' WHERE audience_id=(SELECT audience_snapshot_id FROM notification_campaigns WHERE id=:id) AND status='pending'"
            ),
            {"id": campaign_id},
        )
    await _audit(
        session,
        f"notification.campaign.{ {'sending': 'started', 'paused': 'paused', 'cancelled': 'cancelled'}[target] }",
        "notification_campaign",
        campaign_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"id": str(campaign_id), "status": target, "delivered_email_recalled": False},
        request_id_from_request(request),
    )


@router.post("/admin/notifications/campaigns/{campaign_id}/start")
async def start_campaign(
    campaign_id: UUID,
    payload: CampaignActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.campaigns.start")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _campaign_state_action(
        campaign_id=campaign_id,
        payload=payload,
        target="sending",
        allowed={"ready", "paused"},
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/notifications/campaigns/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: UUID,
    payload: CampaignActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.campaigns.pause")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _campaign_state_action(
        campaign_id=campaign_id,
        payload=payload,
        target="paused",
        allowed={"sending"},
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/notifications/campaigns/{campaign_id}/cancel")
async def cancel_campaign(
    campaign_id: UUID,
    payload: CampaignActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.campaigns.cancel")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _campaign_state_action(
        campaign_id=campaign_id,
        payload=payload,
        target="cancelled",
        allowed={"draft", "in_review", "approved", "ready", "scheduled", "sending", "paused"},
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/notifications/workers/campaigns/{campaign_id}/run")
async def run_campaign_worker(
    campaign_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.campaigns.start")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    result = await dispatch_campaign_batch(session, campaign_id)
    return success(result, request_id_from_request(request))


@router.get("/admin/notifications/suppressions")
async def suppressions(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.suppressions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,destination_type,left(destination_hash,12) AS destination_anonymous_hash,channel,suppression_reason,source,status,created_at,expires_at,lifted_at,lift_reason FROM notification_suppressions ORDER BY created_at DESC LIMIT 200"
                )
            )
        )
        .mappings()
        .all()
    )
    return success({"items": [dict(row) for row in rows]}, request_id_from_request(request))


@router.post("/admin/notifications/suppressions", status_code=201)
async def create_suppression(
    payload: SuppressionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.suppressions.create")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "INSERT INTO notification_suppressions (destination_type,destination_hash,channel,suppression_reason,source,status) VALUES ('email',:hash,:channel,:reason,'admin','active') RETURNING id"
        ),
        {
            "hash": stable_hash(payload.destination),
            "channel": payload.channel,
            "reason": payload.reason,
        },
    )
    suppression_id = UUID(str(value))
    await _audit(
        session,
        "notification.suppression.created",
        "notification_suppression",
        suppression_id,
        actor_id=principal.user.id,
        reason=payload.explanation,
    )
    await session.commit()
    return success(
        {"id": str(suppression_id), "status": "active"}, request_id_from_request(request)
    )


@router.post("/admin/notifications/suppressions/{suppression_id}/lift")
async def lift_suppression(
    suppression_id: UUID,
    payload: StatusReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("notifications.suppressions.lift")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    value = await session.scalar(
        text(
            "UPDATE notification_suppressions SET status='lifted',lifted_at=now(),lifted_by=:actor,lift_reason=:reason WHERE id=:id AND status='active' RETURNING id"
        ),
        {"actor": principal.user.id, "reason": payload.reason, "id": suppression_id},
    )
    if value is None:
        raise VavError(
            "NOTIFICATION_SUPPRESSION_NOT_ACTIVE", "Suppression is not active.", status_code=409
        )
    await _audit(
        session,
        "notification.suppression.lifted",
        "notification_suppression",
        suppression_id,
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(
        {"id": str(suppression_id), "status": "lifted"}, request_id_from_request(request)
    )


@router.get("/admin/notifications/providers")
async def providers(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.providers.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text("SELECT * FROM notification_provider_health ORDER BY provider")
            )
        )
        .mappings()
        .all()
    )
    return success(
        {
            "configured_provider": get_settings().notification_email_provider,
            "items": [dict(row) for row in rows],
        },
        request_id_from_request(request),
    )


@router.get("/admin/notifications/provider-events")
async def provider_events(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.providers.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,provider,provider_event_id,event_type,provider_message_id,signature_verified,processing_status,received_at,processed_at FROM notification_provider_events ORDER BY received_at DESC LIMIT 200"
                )
            )
        )
        .mappings()
        .all()
    )
    return success(
        {"items": [dict(row) for row in rows], "payload_redacted": True},
        request_id_from_request(request),
    )


@router.get("/admin/notifications/audit")
async def notification_audit(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("notifications.audit.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                text("SELECT * FROM notification_audit_events ORDER BY created_at DESC LIMIT 200")
            )
        )
        .mappings()
        .all()
    )
    return success(
        {"items": [dict(row) for row in rows], "sensitive_content_excluded": True},
        request_id_from_request(request),
    )
