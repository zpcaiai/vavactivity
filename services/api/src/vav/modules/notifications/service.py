# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import random
import secrets
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.notifications.crypto import (
    decrypt_notification_data,
    encrypt_notification_data,
    stable_hash,
)
from vav.modules.notifications.providers import EmailSendRequest, configured_email_provider
from vav.modules.notifications.rendering import render_template, route_from_reference
from vav.modules.notifications.schemas import IngestNotificationEventRequest, PreferencePolicy

MANDATORY_POLICIES = {
    PreferencePolicy.MANDATORY_SECURITY.value,
    PreferencePolicy.TRANSACTIONAL_REQUIRED.value,
    PreferencePolicy.SERVICE_REQUIRED.value,
}
DIGEST_CATEGORIES = {"course", "activity", "marketing", "platform"}
SENSITIVE_AUDIENCE_FIELDS = {
    "counseling_content",
    "counseling_notes",
    "ai_conversation",
    "ai_risk",
    "risk_referral",
    "dating_preferences",
    "religion",
    "health",
    "private_reflection",
}
SAFE_AUDIENCE_FIELDS = {
    "locale",
    "region",
    "account_status",
    "membership_tier",
    "course_id",
    "course_completion_status",
    "activity_participated",
    "counseling_service_status",
    "marketing_consent",
    "last_active_from",
    "created_from",
}
EVENT_MESSAGES: dict[str, dict[str, str]] = {
    "verify-email": {
        "zh-CN": "请验证邮箱以完成账户启用。",
        "zh-TW": "請驗證電郵以完成帳戶啟用。",
        "en": "Verify your email to activate your account.",
    },
    "password-changed": {
        "zh-CN": "你的账户密码已更改。",
        "zh-TW": "你的帳戶密碼已變更。",
        "en": "Your account password was changed.",
    },
    "password-reset-completed": {
        "zh-CN": "你的密码重置已完成。",
        "zh-TW": "你的密碼重設已完成。",
        "en": "Your password reset is complete.",
    },
    "suspicious-session": {
        "zh-CN": "检测到可疑会话，已采取保护措施。",
        "zh-TW": "偵測到可疑工作階段，已採取保護措施。",
        "en": "A suspicious session was detected and protected.",
    },
    "order-created": {
        "zh-CN": "订单已建立，请核对付款状态。",
        "zh-TW": "訂單已建立，請核對付款狀態。",
        "en": "Your order was created. Review its payment status.",
    },
    "payment-succeeded": {
        "zh-CN": "付款已成功核验。",
        "zh-TW": "付款已成功核驗。",
        "en": "Your payment was verified successfully.",
    },
    "payment-failed": {
        "zh-CN": "付款未完成，请检查订单。",
        "zh-TW": "付款未完成，請檢查訂單。",
        "en": "Payment was not completed. Review your order.",
    },
    "refund-succeeded": {
        "zh-CN": "退款已完成。",
        "zh-TW": "退款已完成。",
        "en": "Your refund is complete.",
    },
    "registration-confirmed": {
        "zh-CN": "活动报名已确认。",
        "zh-TW": "活動報名已確認。",
        "en": "Your activity registration is confirmed.",
    },
    "waitlist-promotion": {
        "zh-CN": "你收到限时候补递补邀请。",
        "zh-TW": "你收到限時候補遞補邀請。",
        "en": "You received a time-limited waitlist offer.",
    },
    "activity-cancelled": {
        "zh-CN": "活动已取消，请查看后续安排。",
        "zh-TW": "活動已取消，請查看後續安排。",
        "en": "The activity was cancelled. Review next steps.",
    },
    "enrollment-activated": {
        "zh-CN": "课程访问已开通。",
        "zh-TW": "課程存取已開通。",
        "en": "Your course access is active.",
    },
    "content-released": {
        "zh-CN": "课程有新内容可学习。",
        "zh-TW": "課程有新內容可學習。",
        "en": "New course content is available.",
    },
    "appointment-confirmed": {
        "zh-CN": "辅导预约已确认。",
        "zh-TW": "輔導預約已確認。",
        "en": "Your counseling appointment is confirmed.",
    },
    "appointment-cancelled": {
        "zh-CN": "辅导预约已取消。",
        "zh-TW": "輔導預約已取消。",
        "en": "Your counseling appointment was cancelled.",
    },
    "appointment-reminder": {
        "zh-CN": "辅导预约即将开始，请核对时间。",
        "zh-TW": "輔導預約即將開始，請核對時間。",
        "en": "Your counseling appointment starts soon.",
    },
    "referral-created": {
        "zh-CN": "人工转介已建立，可在平台查看状态。",
        "zh-TW": "人工轉介已建立，可在平台查看狀態。",
        "en": "A human referral was created. You can review its status.",
    },
    "referral-assigned": {
        "zh-CN": "人工转介已由团队接手。",
        "zh-TW": "人工轉介已由團隊接手。",
        "en": "A team member has accepted your referral.",
    },
}


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


async def _audit(
    session: AsyncSession,
    event_type: str,
    subject_type: str,
    subject_id: UUID | None,
    *,
    actor_id: UUID | None = None,
    reason: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO notification_audit_events "
            "(event_type,actor_id,subject_type,subject_id,reason,safe_context) "
            "VALUES (:event_type,:actor_id,:subject_type,:subject_id,:reason,CAST(:context AS jsonb))"
        ),
        {
            "event_type": event_type,
            "actor_id": actor_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "reason": reason,
            "context": _json(context or {}),
        },
    )


async def _recipient_user_id(
    session: AsyncSession, resolver: str, payload: dict[str, Any]
) -> UUID | None:
    direct = payload.get("user_id")
    if resolver in {"event_user", "ai_referral_user"} and direct:
        return UUID(str(direct))
    resolver_queries = {
        "order_owner": ("orders", "order_id"),
        "subscription_owner": ("subscriptions", "subscription_id"),
        "activity_registration_user": ("activity_registrations", "registration_id"),
        "activity_waitlist_user": ("activity_waitlist_entries", "waitlist_entry_id"),
        "course_enrollment_user": ("course_enrollments", "enrollment_id"),
        "counseling_appointment_user": ("counseling_appointments", "appointment_id"),
    }
    pair = resolver_queries.get(resolver)
    if pair is None:
        return UUID(str(direct)) if direct else None
    table_name, payload_key = pair
    reference = payload.get(payload_key)
    if reference is None:
        return UUID(str(direct)) if direct else None
    query = text(f"SELECT user_id FROM {table_name} WHERE id=:id")
    value = await session.scalar(query, {"id": UUID(str(reference))})
    return UUID(str(value)) if value else None


async def _active_user(session: AsyncSession, user_id: UUID) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,email,status,email_verified_at,preferred_locale,timezone,deleted_at "
                    "FROM users WHERE id=:id"
                ),
                {"id": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["status"] != "active" or row["deleted_at"] is not None:
        return None
    return dict(row)


def _safe_variables(
    payload: dict[str, Any], template_code: str, locale: str, user: dict[str, Any]
) -> dict[str, Any]:
    localized = EVENT_MESSAGES.get(template_code, {})
    message = localized.get(locale) or localized.get("zh-CN") or "你有一条新的服务通知。"
    variables: dict[str, Any] = {
        "user_display_name": str(
            payload.get("user_display_name") or str(user["email"]).split("@")[0]
        ),
        "message": message,
        "reference_id": str(
            payload.get("order_id")
            or payload.get("registration_id")
            or payload.get("enrollment_id")
            or payload.get("appointment_id")
            or payload.get("referral_id")
            or ""
        ),
    }
    return variables


async def _active_release(
    session: AsyncSession, template_code: str, locale: str, channel: str
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT r.id,r.subject_template,r.title_template,r.body_html_template,"
                    "r.body_text_template,r.action_label_template,r.action_url_template,"
                    "d.variable_schema FROM notification_template_releases r "
                    "JOIN notification_template_definitions d ON d.id=r.template_definition_id "
                    "WHERE d.template_code=:code AND r.locale=:locale AND r.channel=:channel "
                    "AND r.status='active' ORDER BY r.activated_at DESC NULLS LAST,r.created_at DESC LIMIT 1"
                ),
                {"code": template_code, "locale": locale, "channel": channel},
            )
        )
        .mappings()
        .first()
    )
    if row is None and locale != get_settings().notification_default_locale:
        return await _active_release(
            session, template_code, get_settings().notification_default_locale, channel
        )
    if row is None:
        raise VavError(
            "NOTIFICATION_TEMPLATE_RELEASE_MISSING",
            "No active notification template release is available.",
            status_code=409,
        )
    return dict(row)


async def _has_marketing_consent(session: AsyncSession, user_id: UUID) -> bool:
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM notification_consents WHERE user_id=:user_id "
                "AND consent_type='marketing_email' AND status='granted' "
                "AND withdrawn_at IS NULL)"
            ),
            {"user_id": user_id},
        )
    )


def quiet_hours_end(
    *, now: datetime, start: time, end: time, timezone_name: str
) -> datetime | None:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise VavError(
            "NOTIFICATION_TIMEZONE_INVALID",
            "Notification quiet hours require an IANA timezone.",
            status_code=422,
        ) from exc
    local = now.astimezone(zone)
    current = local.timetz().replace(tzinfo=None)
    inside = start <= current < end if start < end else current >= start or current < end
    if not inside:
        return None
    end_date: date = local.date()
    if start >= end and current >= start:
        end_date += timedelta(days=1)
    local_end = datetime.combine(end_date, end, zone)
    return local_end.astimezone(UTC)


async def _delivery_policy(
    session: AsyncSession,
    *,
    user_id: UUID,
    category: str,
    channel: str,
    policy: str,
    priority: str,
    now: datetime,
) -> tuple[str, datetime | None]:
    if policy == PreferencePolicy.MARKETING_OPT_IN.value and not await _has_marketing_consent(
        session, user_id
    ):
        return "suppressed", None
    row = (
        (
            await session.execute(
                text(
                    "SELECT enabled,frequency,quiet_hours_enabled,quiet_hours_start,quiet_hours_end,"
                    "quiet_hours_timezone FROM notification_preferences "
                    "WHERE user_id=:user_id AND category=:category AND channel=:channel"
                ),
                {"user_id": user_id, "category": category, "channel": channel},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return (
            ("immediate", None)
            if policy != PreferencePolicy.MARKETING_OPT_IN.value
            else ("suppressed", None)
        )
    if not row["enabled"] and policy not in MANDATORY_POLICIES:
        return "suppressed", None
    frequency = "immediate" if policy in MANDATORY_POLICIES else str(row["frequency"])
    if frequency == "disabled" and policy not in MANDATORY_POLICIES:
        return "suppressed", None
    if frequency in {"daily_digest", "weekly_digest"} and category in DIGEST_CATEGORIES:
        return frequency, None
    if (
        row["quiet_hours_enabled"]
        and priority not in {"urgent", "high"}
        and policy
        not in {
            PreferencePolicy.MANDATORY_SECURITY.value,
            PreferencePolicy.TRANSACTIONAL_REQUIRED.value,
        }
        and row["quiet_hours_start"] is not None
        and row["quiet_hours_end"] is not None
    ):
        scheduled = quiet_hours_end(
            now=now,
            start=row["quiet_hours_start"],
            end=row["quiet_hours_end"],
            timezone_name=row["quiet_hours_timezone"]
            or get_settings().notification_default_timezone,
        )
        if scheduled:
            return "scheduled", scheduled
    return "immediate", None


async def ingest_event(
    session: AsyncSession, payload: IngestNotificationEventRequest
) -> dict[str, Any]:
    if not get_settings().notification_enabled:
        raise VavError("NOTIFICATIONS_DISABLED", "Notifications are disabled.", status_code=503)
    encrypted = encrypt_notification_data(payload.payload)
    inserted = (
        await session.execute(
            text(
                "INSERT INTO notification_events "
                "(source_event_id,source_module,event_type,event_version,subject_type,subject_id,"
                "payload_encrypted,payload_hash,occurred_at,processing_status) "
                "VALUES (:source_event_id,:source_module,:event_type,:event_version,:subject_type,"
                ":subject_id,CAST(:encrypted AS jsonb),:payload_hash,:occurred_at,'received') "
                "ON CONFLICT (source_module,source_event_id) DO NOTHING RETURNING id"
            ),
            {
                "source_event_id": payload.source_event_id,
                "source_module": payload.source_module,
                "event_type": payload.event_type,
                "event_version": payload.event_version,
                "subject_type": payload.subject_type,
                "subject_id": payload.subject_id,
                "encrypted": _json(encrypted),
                "payload_hash": hashlib.sha256(_json(payload.payload).encode()).hexdigest(),
                "occurred_at": payload.occurred_at,
            },
        )
    ).scalar_one_or_none()
    if inserted is None:
        existing = await session.scalar(
            text(
                "SELECT id FROM notification_events WHERE source_module=:source_module "
                "AND source_event_id=:source_event_id"
            ),
            {"source_module": payload.source_module, "source_event_id": payload.source_event_id},
        )
        await _audit(
            session,
            "notification.event.duplicate_ignored",
            "notification_event",
            UUID(str(existing)),
        )
        await session.commit()
        return {"status": "duplicate", "event_id": str(existing), "intent_ids": []}
    event_id = UUID(str(inserted))
    await _audit(session, "notification.event.received", "notification_event", event_id)
    subscriptions = list(
        (
            await session.execute(
                text(
                    "SELECT * FROM notification_event_subscriptions "
                    "WHERE source_event_type=:event_type AND source_event_version=:version "
                    "AND status='active' ORDER BY subscription_code"
                ),
                {"event_type": payload.event_type, "version": payload.event_version},
            )
        )
        .mappings()
        .all()
    )
    if not subscriptions:
        await session.execute(
            text(
                "UPDATE notification_events SET processing_status='dead_letter',processed_at=now(),"
                "error_code='UNKNOWN_EVENT_VERSION' WHERE id=:id"
            ),
            {"id": event_id},
        )
        await session.execute(
            text(
                "INSERT INTO notification_dead_letters "
                "(source_type,source_id,failure_stage,error_code,safe_error_context) "
                "VALUES ('notification_event',:id,'event_subscription','UNKNOWN_EVENT_VERSION',"
                "CAST(:context AS jsonb)) ON CONFLICT DO NOTHING"
            ),
            {
                "id": event_id,
                "context": _json(
                    {"event_type": payload.event_type, "event_version": payload.event_version}
                ),
            },
        )
        await _audit(
            session,
            "notification.event.dead_lettered",
            "notification_event",
            event_id,
            context={"error_code": "UNKNOWN_EVENT_VERSION"},
        )
        await session.commit()
        return {"status": "dead_letter", "event_id": str(event_id), "intent_ids": []}

    intent_ids: list[str] = []
    for subscription in subscriptions:
        user_id = await _recipient_user_id(
            session, str(subscription["recipient_resolver_code"]), payload.payload
        )
        user = await _active_user(session, user_id) if user_id else None
        if user_id is None or user is None:
            await session.execute(
                text(
                    "INSERT INTO notification_dead_letters "
                    "(source_type,source_id,failure_stage,error_code,safe_error_context) "
                    "VALUES ('notification_event',:id,'recipient_resolution','RECIPIENT_INELIGIBLE',"
                    "CAST(:context AS jsonb)) ON CONFLICT DO NOTHING"
                ),
                {
                    "id": event_id,
                    "context": _json({"resolver": subscription["recipient_resolver_code"]}),
                },
            )
            continue
        policy = subscription["deduplication_policy"]
        format_value = str(policy.get("format", "{event_type}:{event_id}:{user_id}"))
        safe_tokens = {
            "event_type": payload.event_type,
            "event_id": str(event_id),
            "user_id": str(user_id),
            **{
                key: str(value)
                for key, value in payload.payload.items()
                if isinstance(value, str | int)
            },
        }
        try:
            dedup_key = format_value.format_map(_StrictFormatMap(safe_tokens))
        except KeyError as exc:
            raise VavError(
                "NOTIFICATION_DEDUPLICATION_POLICY_INVALID",
                "The event subscription deduplication policy is invalid.",
                status_code=409,
            ) from exc
        locale = str(user["preferred_locale"] or get_settings().notification_default_locale)
        variables = _safe_variables(
            payload.payload, str(subscription["template_code"]), locale, user
        )
        action_reference = payload.payload.get("action_reference")
        if action_reference is not None:
            route_from_reference(action_reference)
        intent_id = (
            await session.execute(
                text(
                    "INSERT INTO notification_intents "
                    "(notification_event_id,notification_type,category,priority,recipient_type,"
                    "recipient_reference_id,template_code,channel_policy,preference_policy,"
                    "template_variables_encrypted,action_reference,deduplication_key,expires_at,status) "
                    "VALUES (:event_id,:notification_type,:category,:priority,'user',:user_id,"
                    ":template_code,CAST(:channels AS jsonb),:preference_policy,:variables,"
                    "CAST(:action_reference AS jsonb),:dedup_key,:expires_at,'created') "
                    "ON CONFLICT (deduplication_key) DO NOTHING RETURNING id"
                ),
                {
                    "event_id": event_id,
                    "notification_type": subscription["notification_type"],
                    "category": subscription["category"],
                    "priority": subscription["priority"],
                    "user_id": user_id,
                    "template_code": subscription["template_code"],
                    "channels": _json(subscription["channel_policy"]),
                    "preference_policy": subscription["preference_policy"],
                    "variables": encrypt_notification_data(variables),
                    "action_reference": _json(action_reference),
                    "dedup_key": dedup_key,
                    "expires_at": payload.payload.get("expires_at"),
                },
            )
        ).scalar_one_or_none()
        if intent_id is None:
            continue
        intent_uuid = UUID(str(intent_id))
        await _materialize_intent(
            session,
            intent_id=intent_uuid,
            user=user,
            subscription=dict(subscription),
            variables=variables,
            action_reference=action_reference,
            expires_at=payload.payload.get("expires_at"),
            dedup_key=dedup_key,
        )
        intent_ids.append(str(intent_uuid))
        await _audit(session, "notification.intent.created", "notification_intent", intent_uuid)

    await session.execute(
        text(
            "UPDATE notification_events SET processing_status='processed',processed_at=now() WHERE id=:id"
        ),
        {"id": event_id},
    )
    await session.commit()
    return {"status": "processed", "event_id": str(event_id), "intent_ids": intent_ids}


class _StrictFormatMap(dict[str, str]):
    def __missing__(self, key: str) -> str:
        raise KeyError(key)


async def _materialize_intent(
    session: AsyncSession,
    *,
    intent_id: UUID,
    user: dict[str, Any],
    subscription: dict[str, Any],
    variables: dict[str, Any],
    action_reference: dict[str, Any] | None,
    expires_at: Any,
    dedup_key: str,
) -> None:
    channel_policy = subscription["channel_policy"]
    channels = list(channel_policy.get("required", [])) + list(channel_policy.get("optional", []))
    channels = list(dict.fromkeys(str(value) for value in channels))
    locale = str(user["preferred_locale"] or get_settings().notification_default_locale)
    now = _now()
    for channel in channels:
        decision, scheduled_at = await _delivery_policy(
            session,
            user_id=UUID(str(user["id"])),
            category=str(subscription["category"]),
            channel=channel,
            policy=str(subscription["preference_policy"]),
            priority=str(subscription["priority"]),
            now=now,
        )
        if decision == "suppressed":
            await _audit(
                session,
                "notification.intent.suppressed",
                "notification_intent",
                intent_id,
                context={"channel": channel},
            )
            continue
        if decision in {"daily_digest", "weekly_digest"}:
            window = (
                now.strftime("%Y-%m-%d") if decision == "daily_digest" else now.strftime("%G-W%V")
            )
            await session.execute(
                text(
                    "INSERT INTO notification_digest_items "
                    "(user_id,category,notification_intent_id,digest_frequency,digest_window_key) "
                    "VALUES (:user_id,:category,:intent_id,:frequency,:window) ON CONFLICT DO NOTHING"
                ),
                {
                    "user_id": user["id"],
                    "category": subscription["category"],
                    "intent_id": intent_id,
                    "frequency": decision,
                    "window": window,
                },
            )
            continue
        release = await _active_release(
            session, str(subscription["template_code"]), locale, channel
        )
        rendered = render_template(
            schema=release["variable_schema"],
            variables=variables,
            subject_template=release["subject_template"],
            title_template=release["title_template"],
            body_html_template=release["body_html_template"],
            body_text_template=release["body_text_template"],
            action_label_template=release["action_label_template"],
            action_url_template=release["action_url_template"],
        )
        action_url = (
            route_from_reference(action_reference) if action_reference else rendered.action_url
        )
        checksum_source = "|".join(
            value or ""
            for value in [
                rendered.subject,
                rendered.title,
                rendered.body_html,
                rendered.body_text,
                action_url,
            ]
        )
        checksum = hashlib.sha256(checksum_source.encode()).hexdigest()
        if channel == "in_app" and get_settings().notification_in_app_enabled:
            await session.execute(
                text(
                    "INSERT INTO user_notifications "
                    "(user_id,notification_intent_id,category,priority,title,body,action_type,"
                    "action_reference,action_url,status,available_from,expires_at,template_release_id,rendering_snapshot) "
                    "VALUES (:user_id,:intent_id,:category,:priority,:title,:body,'route',"
                    "CAST(:action_reference AS jsonb),:action_url,'active',:available_from,:expires_at,"
                    ":release_id,CAST(:snapshot AS jsonb)) ON CONFLICT DO NOTHING"
                ),
                {
                    "user_id": user["id"],
                    "intent_id": intent_id,
                    "category": subscription["category"],
                    "priority": subscription["priority"],
                    "title": rendered.title or rendered.subject or "VAV",
                    "body": rendered.body_text,
                    "action_reference": _json(action_reference),
                    "action_url": action_url,
                    "available_from": scheduled_at or now,
                    "expires_at": expires_at,
                    "release_id": release["id"],
                    "snapshot": _json({"checksum": checksum, "locale": locale}),
                },
            )
            await _audit(session, "notification.in_app.created", "notification_intent", intent_id)
        elif channel == "email" and get_settings().notification_email_enabled:
            if user["email_verified_at"] is None:
                continue
            destination = str(user["email"])
            destination_hash = stable_hash(destination)
            suppressed = await session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM notification_suppressions WHERE destination_hash=:hash "
                    "AND channel='email' AND status='active' AND (expires_at IS NULL OR expires_at>now()))"
                ),
                {"hash": destination_hash},
            )
            if suppressed:
                continue
            await session.execute(
                text(
                    "INSERT INTO notification_deliveries "
                    "(notification_intent_id,user_id,channel,priority,destination_encrypted,destination_hash,"
                    "template_release_id,locale,subject_rendered_encrypted,body_html_rendered_encrypted,"
                    "body_text_rendered_encrypted,rendering_checksum,status,provider,scheduled_at,next_attempt_at,"
                    "expires_at,deduplication_key) VALUES (:intent_id,:user_id,'email',:priority,:destination,"
                    ":destination_hash,:release_id,:locale,:subject,:html,:text,:checksum,:status,:provider,"
                    ":scheduled_at,:next_attempt_at,:expires_at,:dedup_key) ON CONFLICT DO NOTHING"
                ),
                {
                    "intent_id": intent_id,
                    "user_id": user["id"],
                    "priority": subscription["priority"],
                    "destination": encrypt_notification_data(destination),
                    "destination_hash": destination_hash,
                    "release_id": release["id"],
                    "locale": locale,
                    "subject": encrypt_notification_data(
                        rendered.subject or rendered.title or "VAV"
                    ),
                    "html": encrypt_notification_data(
                        rendered.body_html or f"<p>{rendered.body_text}</p>"
                    ),
                    "text": encrypt_notification_data(rendered.body_text),
                    "checksum": checksum,
                    "status": "scheduled" if scheduled_at else "pending",
                    "provider": get_settings().notification_email_provider,
                    "scheduled_at": scheduled_at,
                    "next_attempt_at": scheduled_at or now,
                    "expires_at": expires_at,
                    "dedup_key": dedup_key,
                },
            )
            await _audit(session, "notification.delivery.created", "notification_intent", intent_id)


async def process_due_deliveries(
    session: AsyncSession, *, limit: int | None = None
) -> list[dict[str, Any]]:
    settings = get_settings()
    batch_size = min(limit or settings.notification_worker_batch_size, 1000)
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT d.id FROM notification_deliveries d WHERE d.status IN "
                    "('pending','scheduled','failed_retryable') AND d.next_attempt_at<=now() "
                    "AND (d.expires_at IS NULL OR d.expires_at>now()) "
                    "ORDER BY CASE d.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,d.created_at "
                    "FOR UPDATE SKIP LOCKED LIMIT :limit"
                ),
                {"limit": batch_size},
            )
        )
        .scalars()
        .all()
    )
    results: list[dict[str, Any]] = []
    for value in rows:
        delivery_id = UUID(str(value))
        result = await _send_delivery(session, delivery_id)
        results.append(result)
    await session.commit()
    return results


async def _send_delivery(session: AsyncSession, delivery_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT d.*,i.notification_type,i.category,i.preference_policy,u.email,u.email_verified_at,"
                    "u.status AS user_status,u.deleted_at FROM notification_deliveries d "
                    "JOIN notification_intents i ON i.id=d.notification_intent_id "
                    "JOIN users u ON u.id=d.user_id WHERE d.id=:id FOR UPDATE"
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
    if row["status"] not in {"pending", "scheduled", "failed_retryable"}:
        return {"delivery_id": str(delivery_id), "status": str(row["status"]), "duplicate": True}
    if row["expires_at"] is not None and row["expires_at"] <= _now():
        await session.execute(
            text(
                "UPDATE notification_deliveries SET status='cancelled',updated_at=now() WHERE id=:id"
            ),
            {"id": delivery_id},
        )
        return {"delivery_id": str(delivery_id), "status": "cancelled", "duplicate": False}
    destination = str(row["email"])
    if (
        row["user_status"] != "active"
        or row["deleted_at"] is not None
        or row["email_verified_at"] is None
        or stable_hash(destination) != row["destination_hash"]
    ):
        await _final_failure(
            session, delivery_id, "POLICY_REVALIDATION_FAILED", "policy_suppression"
        )
        return {"delivery_id": str(delivery_id), "status": "suppressed", "duplicate": False}
    suppressed = await session.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM notification_suppressions WHERE destination_hash=:hash "
            "AND channel='email' AND status='active' AND (expires_at IS NULL OR expires_at>now()))"
        ),
        {"hash": row["destination_hash"]},
    )
    if suppressed:
        await session.execute(
            text(
                "UPDATE notification_deliveries SET status='suppressed',updated_at=now() WHERE id=:id"
            ),
            {"id": delivery_id},
        )
        return {"delivery_id": str(delivery_id), "status": "suppressed", "duplicate": False}
    if row[
        "preference_policy"
    ] == PreferencePolicy.MARKETING_OPT_IN.value and not await _has_marketing_consent(
        session, UUID(str(row["user_id"]))
    ):
        await session.execute(
            text(
                "UPDATE notification_deliveries SET status='suppressed',updated_at=now() WHERE id=:id"
            ),
            {"id": delivery_id},
        )
        return {"delivery_id": str(delivery_id), "status": "suppressed", "duplicate": False}
    attempt_number = int(row["attempt_count"]) + 1
    provider = configured_email_provider()
    await session.execute(
        text(
            "UPDATE notification_deliveries SET status='processing',attempt_count=:attempt,"
            "first_attempt_at=COALESCE(first_attempt_at,now()),updated_at=now() WHERE id=:id"
        ),
        {"attempt": attempt_number, "id": delivery_id},
    )
    attempt_id = await session.scalar(
        text(
            "INSERT INTO notification_delivery_attempts "
            "(delivery_id,attempt_number,provider,status,request_metadata,started_at) "
            "VALUES (:delivery_id,:attempt,:provider,'started',CAST(:metadata AS jsonb),now()) RETURNING id"
        ),
        {
            "delivery_id": delivery_id,
            "attempt": attempt_number,
            "provider": provider.name,
            "metadata": _json(
                {
                    "delivery_id": str(delivery_id),
                    "notification_type": row["notification_type"],
                    "environment": get_settings().environment,
                }
            ),
        },
    )
    request = EmailSendRequest(
        from_address=get_settings().notification_email_from_address,
        from_name=get_settings().notification_email_from_name,
        to_address=destination,
        reply_to=get_settings().notification_email_reply_to or None,
        subject=str(decrypt_notification_data(row["subject_rendered_encrypted"])),
        html_body=str(decrypt_notification_data(row["body_html_rendered_encrypted"])),
        text_body=str(decrypt_notification_data(row["body_text_rendered_encrypted"])),
        headers={"X-VAV-Delivery-ID": str(delivery_id)},
        tags={
            "delivery_id": str(delivery_id),
            "notification_type": str(row["notification_type"]),
            "environment": get_settings().environment,
        },
        idempotency_key=str(row["deduplication_key"]),
    )
    try:
        result = await provider.send(request)
    except VavError as exc:
        retryable = exc.code in {
            "NOTIFICATION_PROVIDER_TEMPORARY",
            "NOTIFICATION_PROVIDER_RATE_LIMIT",
        }
        await _record_send_failure(
            session,
            delivery_id=delivery_id,
            attempt_id=UUID(str(attempt_id)),
            attempt_number=attempt_number,
            error_code=exc.code,
            retryable=retryable,
        )
        return {
            "delivery_id": str(delivery_id),
            "status": "failed_retryable" if retryable else "failed_final",
            "duplicate": False,
        }
    await session.execute(
        text(
            "UPDATE notification_delivery_attempts SET status='accepted',provider_message_id=:message_id,"
            "provider_response_code=:code,response_metadata=CAST(:metadata AS jsonb),completed_at=now() "
            "WHERE id=:id"
        ),
        {
            "message_id": result.provider_message_id,
            "code": result.response_code,
            "metadata": _json({"status": result.status}),
            "id": attempt_id,
        },
    )
    await session.execute(
        text(
            "UPDATE notification_deliveries SET status='sent',provider=:provider,"
            "provider_message_id=:message_id,sent_at=now(),updated_at=now() WHERE id=:id"
        ),
        {"provider": provider.name, "message_id": result.provider_message_id, "id": delivery_id},
    )
    await _audit(session, "notification.delivery.sent", "notification_delivery", delivery_id)
    return {"delivery_id": str(delivery_id), "status": "sent", "duplicate": False}


def retry_delay(attempt_number: int, *, jitter: float | None = None) -> int:
    schedule = [0, 60, 300, 1800, 7200, 43200]
    base = schedule[min(max(attempt_number, 1) - 1, len(schedule) - 1)]
    ratio = jitter if jitter is not None else random.uniform(0.9, 1.1)
    return min(int(base * ratio), get_settings().notification_retry_max_seconds)


async def _record_send_failure(
    session: AsyncSession,
    *,
    delivery_id: UUID,
    attempt_id: UUID,
    attempt_number: int,
    error_code: str,
    retryable: bool,
) -> None:
    final = not retryable or attempt_number >= get_settings().notification_max_delivery_attempts
    status = "failed_final" if final else "failed_retryable"
    next_attempt = None if final else _now() + timedelta(seconds=retry_delay(attempt_number + 1))
    await session.execute(
        text(
            "UPDATE notification_delivery_attempts SET status='failed',error_class=:error_class,"
            "error_code=:error_code,error_message_safe='Provider request failed.',completed_at=now() "
            "WHERE id=:id"
        ),
        {
            "error_class": "provider_temporary" if retryable else "unknown",
            "error_code": error_code,
            "id": attempt_id,
        },
    )
    await session.execute(
        text(
            "UPDATE notification_deliveries SET status=:status,next_attempt_at=:next_attempt,"
            "updated_at=now() WHERE id=:id"
        ),
        {"status": status, "next_attempt": next_attempt, "id": delivery_id},
    )
    if final:
        await session.execute(
            text(
                "INSERT INTO notification_dead_letters "
                "(source_type,source_id,failure_stage,error_code,safe_error_context) "
                "VALUES ('delivery',:id,'provider_send',:error_code,CAST(:context AS jsonb)) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "id": delivery_id,
                "error_code": error_code,
                "context": _json({"attempt_number": attempt_number}),
            },
        )
    await _audit(
        session,
        "notification.delivery.failed",
        "notification_delivery",
        delivery_id,
        context={"retryable": not final, "error_code": error_code},
    )


async def _final_failure(
    session: AsyncSession, delivery_id: UUID, error_code: str, error_class: str
) -> None:
    await session.execute(
        text(
            "UPDATE notification_deliveries SET status='suppressed',updated_at=now() WHERE id=:id"
        ),
        {"id": delivery_id},
    )
    await _audit(
        session,
        "notification.delivery.failed",
        "notification_delivery",
        delivery_id,
        context={"error_code": error_code, "error_class": error_class},
    )


async def create_unsubscribe_token(
    session: AsyncSession, *, user_id: UUID, category: str, channel: str = "email"
) -> str:
    if category != "marketing":
        raise VavError(
            "NOTIFICATION_UNSUBSCRIBE_CATEGORY_FORBIDDEN",
            "Only optional marketing categories use public unsubscribe tokens.",
            status_code=422,
        )
    token = secrets.token_urlsafe(32)
    await session.execute(
        text(
            "INSERT INTO notification_unsubscribe_tokens "
            "(user_id,category,channel,token_hash,expires_at) "
            "VALUES (:user_id,:category,:channel,:token_hash,:expires_at)"
        ),
        {
            "user_id": user_id,
            "category": category,
            "channel": channel,
            "token_hash": stable_hash(token),
            "expires_at": _now() + timedelta(days=365),
        },
    )
    await session.commit()
    return token


async def consume_unsubscribe_token(session: AsyncSession, token: str) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM notification_unsubscribe_tokens WHERE token_hash=:hash FOR UPDATE"
                ),
                {"hash": stable_hash(token)},
            )
        )
        .mappings()
        .first()
    )
    if (
        row is None
        or row["consumed_at"] is not None
        or (row["expires_at"] is not None and row["expires_at"] <= _now())
    ):
        raise VavError(
            "NOTIFICATION_UNSUBSCRIBE_TOKEN_INVALID",
            "The unsubscribe link is invalid or expired.",
            status_code=400,
        )
    if row["category"] != "marketing":
        raise VavError(
            "NOTIFICATION_UNSUBSCRIBE_CATEGORY_FORBIDDEN",
            "This notification category cannot be disabled by a marketing link.",
            status_code=409,
        )
    await session.execute(
        text("UPDATE notification_unsubscribe_tokens SET consumed_at=now() WHERE id=:id"),
        {"id": row["id"]},
    )
    await session.execute(
        text(
            "INSERT INTO notification_preferences "
            "(user_id,category,channel,enabled,frequency,source) "
            "VALUES (:user_id,'marketing',:channel,false,'disabled','unsubscribe') "
            "ON CONFLICT (user_id,category,channel) DO UPDATE SET enabled=false,frequency='disabled',"
            "source='unsubscribe',version=notification_preferences.version+1,updated_at=now()"
        ),
        {"user_id": row["user_id"], "channel": row["channel"]},
    )
    await session.execute(
        text(
            "UPDATE notification_consents SET status='withdrawn',withdrawn_at=now(),updated_at=now() "
            "WHERE user_id=:user_id AND consent_type='marketing_email' AND status='granted'"
        ),
        {"user_id": row["user_id"]},
    )
    await _audit(
        session,
        "notification.unsubscribed",
        "user",
        UUID(str(row["user_id"])),
        context={"category": "marketing", "channel": row["channel"]},
    )
    await session.commit()
    return {"status": "unsubscribed", "category": "marketing", "channel": row["channel"]}


def validate_campaign_audience(definition: dict[str, Any]) -> None:
    keys = set(definition)
    forbidden = keys & SENSITIVE_AUDIENCE_FIELDS
    unknown = keys - SAFE_AUDIENCE_FIELDS
    if forbidden or unknown:
        raise VavError(
            "NOTIFICATION_CAMPAIGN_AUDIENCE_UNSAFE",
            "Campaign audience contains unsupported or sensitive fields.",
            details=[{"forbidden": sorted(forbidden), "unknown": sorted(unknown)}],
            status_code=422,
        )


async def dispatch_due_reminders(
    session: AsyncSession, *, limit: int | None = None
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT * FROM notification_reminders WHERE status='scheduled' AND trigger_at<=now() "
                    "ORDER BY trigger_at FOR UPDATE SKIP LOCKED LIMIT :limit"
                ),
                {"limit": min(limit or get_settings().notification_worker_batch_size, 1000)},
            )
        )
        .mappings()
        .all()
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        user = await _active_user(session, UUID(str(row["recipient_user_id"])))
        if user is None:
            await session.execute(
                text(
                    "UPDATE notification_reminders SET status='cancelled',updated_at=now() WHERE id=:id"
                ),
                {"id": row["id"]},
            )
            results.append({"reminder_id": str(row["id"]), "status": "cancelled"})
            continue
        template_code = str(row["template_code"])
        locale = str(user["preferred_locale"] or get_settings().notification_default_locale)
        variables = _safe_variables({}, template_code, locale, user)
        intent_id = await session.scalar(
            text(
                "INSERT INTO notification_intents "
                "(notification_type,category,priority,recipient_type,recipient_reference_id,template_code,"
                "channel_policy,preference_policy,template_variables_encrypted,deduplication_key,status) "
                "VALUES (:notification_type,:category,'normal','user',:user_id,:template_code,"
                '\'{"required":["in_app"],"optional":["email"]}\'::jsonb,'
                "'service_optional',:variables,:dedup_key,'created') "
                "ON CONFLICT (deduplication_key) DO NOTHING RETURNING id"
            ),
            {
                "notification_type": row["reminder_type"],
                "category": row["category"],
                "user_id": row["recipient_user_id"],
                "template_code": template_code,
                "variables": encrypt_notification_data(variables),
                "dedup_key": row["deduplication_key"],
            },
        )
        if intent_id is not None:
            await _materialize_intent(
                session,
                intent_id=UUID(str(intent_id)),
                user=user,
                subscription={
                    "template_code": template_code,
                    "category": row["category"],
                    "priority": "normal",
                    "preference_policy": "service_optional",
                    "channel_policy": {"required": ["in_app"], "optional": ["email"]},
                },
                variables=variables,
                action_reference=None,
                expires_at=None,
                dedup_key=str(row["deduplication_key"]),
            )
        await session.execute(
            text(
                "UPDATE notification_reminders SET status='dispatched',dispatched_intent_id=:intent_id,"
                "updated_at=now() WHERE id=:id"
            ),
            {"intent_id": intent_id, "id": row["id"]},
        )
        await _audit(
            session,
            "notification.reminder.dispatched",
            "notification_reminder",
            UUID(str(row["id"])),
        )
        results.append({"reminder_id": str(row["id"]), "status": "dispatched"})
    await session.commit()
    return results


async def replan_reminder(
    session: AsyncSession,
    *,
    reminder_type: str,
    subject_type: str,
    subject_id: UUID,
    recipient_user_id: UUID,
    template_code: str,
    category: str,
    trigger_at: datetime,
    timezone_name: str,
    reference_version: int,
    deduplication_key: str,
) -> UUID:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise VavError(
            "NOTIFICATION_TIMEZONE_INVALID", "Reminder timezone is invalid.", status_code=422
        ) from exc
    await session.execute(
        text(
            "UPDATE notification_reminders SET status='cancelled',updated_at=now() "
            "WHERE subject_type=:subject_type AND subject_id=:subject_id AND reminder_type=:reminder_type "
            "AND status IN ('planned','scheduled') AND trigger_reference_version<>:version"
        ),
        {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "reminder_type": reminder_type,
            "version": reference_version,
        },
    )
    value = await session.scalar(
        text(
            "INSERT INTO notification_reminders "
            "(reminder_type,subject_type,subject_id,recipient_user_id,template_code,category,trigger_at,"
            "timezone,trigger_reference_version,status,deduplication_key) "
            "VALUES (:reminder_type,:subject_type,:subject_id,:user_id,:template_code,:category,"
            ":trigger_at,:timezone,:version,'scheduled',:dedup_key) "
            "ON CONFLICT (deduplication_key) DO UPDATE SET trigger_at=EXCLUDED.trigger_at,"
            "trigger_reference_version=EXCLUDED.trigger_reference_version,status='scheduled',updated_at=now() "
            "RETURNING id"
        ),
        {
            "reminder_type": reminder_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "user_id": recipient_user_id,
            "template_code": template_code,
            "category": category,
            "trigger_at": trigger_at,
            "timezone": timezone_name,
            "version": reference_version,
            "dedup_key": deduplication_key,
        },
    )
    reminder_id = UUID(str(value))
    await _audit(session, "notification.reminder.created", "notification_reminder", reminder_id)
    await session.commit()
    return reminder_id


async def receive_provider_webhook(
    session: AsyncSession,
    *,
    provider_name: str,
    headers: dict[str, str],
    raw_body: bytes,
) -> dict[str, Any]:
    provider = configured_email_provider()
    if provider_name != provider.name:
        raise VavError(
            "NOTIFICATION_PROVIDER_MISMATCH",
            "The webhook provider is not active for this environment.",
            status_code=404,
        )
    if not await provider.verify_webhook(headers, raw_body):
        raise VavError(
            "NOTIFICATION_WEBHOOK_SIGNATURE_INVALID",
            "Notification provider webhook signature is invalid.",
            status_code=401,
        )
    try:
        body = json.loads(raw_body)
        event_id = str(body["event_id"])
        event_type = str(body["event_type"])
    except (ValueError, KeyError, TypeError) as exc:
        raise VavError(
            "NOTIFICATION_WEBHOOK_INVALID",
            "Notification provider webhook body is invalid.",
            status_code=400,
        ) from exc
    if event_type not in {"delivered", "deferred", "hard_bounce", "soft_bounce", "complaint"}:
        raise VavError(
            "NOTIFICATION_WEBHOOK_EVENT_UNSUPPORTED",
            "Notification provider webhook event is unsupported.",
            status_code=422,
        )
    inserted = await session.scalar(
        text(
            "INSERT INTO notification_provider_events "
            "(provider,provider_event_id,event_type,provider_message_id,signature_verified,"
            "payload_encrypted,payload_hash,processing_status) VALUES (:provider,:event_id,:event_type,"
            ":message_id,true,CAST(:payload AS jsonb),:payload_hash,'received') "
            "ON CONFLICT (provider,provider_event_id) DO NOTHING RETURNING id"
        ),
        {
            "provider": provider_name,
            "event_id": event_id,
            "event_type": event_type,
            "message_id": body.get("provider_message_id"),
            "payload": _json(encrypt_notification_data(body)),
            "payload_hash": hashlib.sha256(raw_body).hexdigest(),
        },
    )
    if inserted is None:
        await session.commit()
        return {"status": "duplicate", "provider_event_id": event_id}
    provider_event_id = UUID(str(inserted))
    message_id = body.get("provider_message_id")
    delivery = None
    if message_id:
        delivery = (
            (
                await session.execute(
                    text(
                        "SELECT id,destination_hash,status FROM notification_deliveries "
                        "WHERE provider=:provider AND provider_message_id=:message_id FOR UPDATE"
                    ),
                    {"provider": provider_name, "message_id": message_id},
                )
            )
            .mappings()
            .first()
        )
    if delivery is not None:
        status_map = {
            "delivered": "delivered",
            "deferred": "deferred",
            "hard_bounce": "failed_final",
            "soft_bounce": "failed_retryable",
            "complaint": "failed_final",
        }
        target = status_map[event_type]
        await session.execute(
            text(
                "UPDATE notification_deliveries SET status=CAST(:status AS varchar),"
                "delivered_at=CASE WHEN CAST(:status AS varchar)='delivered' THEN now() ELSE delivered_at END,"
                "next_attempt_at=CASE WHEN CAST(:status AS varchar) IN ('deferred','failed_retryable') "
                "THEN now()+interval '5 minutes' ELSE next_attempt_at END,updated_at=now() WHERE id=:id"
            ),
            {"status": target, "id": delivery["id"]},
        )
        await session.execute(
            text(
                "UPDATE notification_delivery_attempts SET status=:attempt_status,completed_at=now() "
                "WHERE delivery_id=:id AND attempt_number=(SELECT max(attempt_number) "
                "FROM notification_delivery_attempts WHERE delivery_id=:id)"
            ),
            {
                "attempt_status": {
                    "delivered": "delivered",
                    "deferred": "deferred",
                    "hard_bounce": "bounced",
                    "soft_bounce": "bounced",
                    "complaint": "complained",
                }[event_type],
                "id": delivery["id"],
            },
        )
        if event_type in {"hard_bounce", "complaint"}:
            reason = "hard_bounce" if event_type == "hard_bounce" else "spam_complaint"
            await session.execute(
                text(
                    "INSERT INTO notification_suppressions "
                    "(destination_type,destination_hash,channel,suppression_reason,source,status) "
                    "VALUES ('email',:hash,'email',:reason,'provider_webhook','active') "
                    "ON CONFLICT DO NOTHING"
                ),
                {"hash": delivery["destination_hash"], "reason": reason},
            )
    await session.execute(
        text(
            "UPDATE notification_provider_events SET processing_status='processed',processed_at=now() WHERE id=:id"
        ),
        {"id": provider_event_id},
    )
    await _audit(
        session,
        "notification.provider_event.processed",
        "notification_provider_event",
        provider_event_id,
        context={"provider": provider_name, "event_type": event_type},
    )
    await session.commit()
    return {"status": "processed", "provider_event_id": event_id}


async def generate_campaign_audience(
    session: AsyncSession, campaign_id: UUID, *, actor_id: UUID
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
    if campaign is None:
        raise VavError(
            "NOTIFICATION_CAMPAIGN_NOT_FOUND", "Campaign was not found.", status_code=404
        )
    if campaign["status"] != "approved":
        raise VavError(
            "NOTIFICATION_CAMPAIGN_AUDIENCE_STATE_INVALID",
            "An approved campaign is required before freezing its audience.",
            status_code=409,
        )
    definition = dict(campaign["audience_definition"])
    validate_campaign_audience(definition)
    clauses = ["u.status='active'", "u.deleted_at IS NULL", "u.email_verified_at IS NOT NULL"]
    params: dict[str, Any] = {}
    if definition.get("locale"):
        clauses.append("u.preferred_locale=:locale")
        params["locale"] = definition["locale"]
    if campaign["category"] == "marketing" or definition.get("marketing_consent") is True:
        clauses.append(
            "EXISTS(SELECT 1 FROM notification_consents c WHERE c.user_id=u.id "
            "AND c.consent_type='marketing_email' AND c.status='granted' AND c.withdrawn_at IS NULL)"
        )
    candidates = list(
        (
            await session.execute(
                text(
                    "SELECT u.id,u.preferred_locale,u.email FROM users u WHERE "
                    + " AND ".join(clauses)
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    eligible: list[dict[str, Any]] = []
    suppressed_count = 0
    for candidate in candidates:
        destination_hash = stable_hash(str(candidate["email"]))
        suppressed = await session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM notification_suppressions WHERE destination_hash=:hash "
                "AND channel='email' AND status='active' AND (expires_at IS NULL OR expires_at>now()))"
            ),
            {"hash": destination_hash},
        )
        if suppressed:
            suppressed_count += 1
            continue
        eligible.append({**dict(candidate), "destination_hash": destination_hash})
    checksum = hashlib.sha256(
        _json(
            {"definition": definition, "users": sorted(str(row["id"]) for row in eligible)}
        ).encode()
    ).hexdigest()
    audience_id = await session.scalar(
        text(
            "INSERT INTO notification_campaign_audiences "
            "(campaign_id,audience_definition_snapshot,total_candidates,eligible_recipients,"
            "suppressed_recipients,locale_distribution,region_distribution,checksum_sha256) "
            "VALUES (:campaign_id,CAST(:definition AS jsonb),:total,:eligible,:suppressed,"
            "CAST(:locales AS jsonb),'{}'::jsonb,:checksum) "
            "ON CONFLICT (campaign_id,checksum_sha256) DO UPDATE SET checksum_sha256=EXCLUDED.checksum_sha256 "
            "RETURNING id"
        ),
        {
            "campaign_id": campaign_id,
            "definition": _json(definition),
            "total": len(candidates),
            "eligible": len(eligible),
            "suppressed": suppressed_count,
            "locales": _json(
                {
                    locale: sum(1 for row in eligible if row["preferred_locale"] == locale)
                    for locale in {str(row["preferred_locale"]) for row in eligible}
                }
            ),
            "checksum": checksum,
        },
    )
    for recipient in eligible:
        await session.execute(
            text(
                "INSERT INTO notification_campaign_recipients "
                "(audience_id,user_id,locale,destination_hash,eligibility_snapshot) "
                "VALUES (:audience_id,:user_id,:locale,:destination_hash,CAST(:snapshot AS jsonb)) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "audience_id": audience_id,
                "user_id": recipient["id"],
                "locale": recipient["preferred_locale"],
                "destination_hash": recipient["destination_hash"],
                "snapshot": _json({"consent_checked": True, "suppression_checked": True}),
            },
        )
    await session.execute(
        text(
            "UPDATE notification_campaigns SET audience_snapshot_id=:audience_id,status='ready' WHERE id=:id"
        ),
        {"audience_id": audience_id, "id": campaign_id},
    )
    await _audit(
        session,
        "notification.campaign.audience_generated",
        "notification_campaign",
        campaign_id,
        actor_id=actor_id,
        context={"eligible_recipients": len(eligible), "suppressed_recipients": suppressed_count},
    )
    await session.commit()
    return {
        "audience_id": str(audience_id),
        "total_candidates": len(candidates),
        "eligible_recipients": len(eligible),
        "suppressed_recipients": suppressed_count,
        "checksum": checksum,
    }


async def dispatch_campaign_batch(session: AsyncSession, campaign_id: UUID) -> dict[str, Any]:
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
    if campaign is None or campaign["status"] != "sending":
        raise VavError(
            "NOTIFICATION_CAMPAIGN_DISPATCH_INVALID",
            "Campaign is not in the sending state.",
            status_code=409,
        )
    audience_id = campaign["audience_snapshot_id"]
    if audience_id is None:
        raise VavError(
            "NOTIFICATION_CAMPAIGN_AUDIENCE_MISSING",
            "Campaign has no approved audience snapshot.",
            status_code=409,
        )
    recipients = list(
        (
            await session.execute(
                text(
                    "SELECT * FROM notification_campaign_recipients WHERE audience_id=:audience_id "
                    "AND status='pending' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT :limit"
                ),
                {"audience_id": audience_id, "limit": int(campaign["batch_size"] or 100)},
            )
        )
        .mappings()
        .all()
    )
    queued = 0
    suppressed = 0
    for recipient in recipients:
        user = await _active_user(session, UUID(str(recipient["user_id"])))
        eligible = user is not None
        if eligible and campaign["category"] == "marketing":
            eligible = await _has_marketing_consent(session, UUID(str(recipient["user_id"])))
        if eligible and user is not None:
            eligible = stable_hash(str(user["email"])) == recipient["destination_hash"]
        if not eligible or user is None:
            await session.execute(
                text(
                    "UPDATE notification_campaign_recipients SET status='suppressed' WHERE id=:id"
                ),
                {"id": recipient["id"]},
            )
            suppressed += 1
            continue
        dedup_key = f"campaign:{campaign_id}:{recipient['user_id']}"
        locale = str(user["preferred_locale"] or get_settings().notification_default_locale)
        variables = _safe_variables({}, str(campaign["template_code"]), locale, user)
        policy = (
            PreferencePolicy.MARKETING_OPT_IN.value
            if campaign["category"] == "marketing"
            else PreferencePolicy.SERVICE_OPTIONAL.value
        )
        intent_id = await session.scalar(
            text(
                "INSERT INTO notification_intents "
                "(notification_type,category,priority,recipient_type,recipient_reference_id,"
                "template_code,channel_policy,preference_policy,template_variables_encrypted,"
                "deduplication_key,status) VALUES ('campaign',:category,'normal','user',:user_id,"
                ":template_code,CAST(:channels AS jsonb),:policy,:variables,:dedup_key,'created') "
                "ON CONFLICT (deduplication_key) DO NOTHING RETURNING id"
            ),
            {
                "category": campaign["category"],
                "user_id": recipient["user_id"],
                "template_code": campaign["template_code"],
                "channels": _json(campaign["channel_policy"]),
                "policy": policy,
                "variables": encrypt_notification_data(variables),
                "dedup_key": dedup_key,
            },
        )
        if intent_id is not None:
            await _materialize_intent(
                session,
                intent_id=UUID(str(intent_id)),
                user=user,
                subscription={
                    "template_code": campaign["template_code"],
                    "category": campaign["category"],
                    "priority": "normal",
                    "preference_policy": policy,
                    "channel_policy": campaign["channel_policy"],
                },
                variables=variables,
                action_reference=None,
                expires_at=None,
                dedup_key=dedup_key,
            )
        await session.execute(
            text(
                "UPDATE notification_campaign_recipients SET status='queued',"
                "notification_intent_id=:intent_id WHERE id=:id"
            ),
            {"intent_id": intent_id, "id": recipient["id"]},
        )
        queued += 1
    pending = await session.scalar(
        text(
            "SELECT count(*) FROM notification_campaign_recipients "
            "WHERE audience_id=:audience_id AND status='pending'"
        ),
        {"audience_id": audience_id},
    )
    if not pending:
        await session.execute(
            text(
                "UPDATE notification_campaigns SET status='completed',completed_at=now() WHERE id=:id"
            ),
            {"id": campaign_id},
        )
        await _audit(
            session,
            "notification.campaign.completed",
            "notification_campaign",
            campaign_id,
            context={"queued": queued, "suppressed": suppressed},
        )
    await session.commit()
    return {
        "campaign_id": str(campaign_id),
        "queued": queued,
        "suppressed": suppressed,
        "pending": int(pending or 0),
        "status": "completed" if not pending else "sending",
    }


async def dispatch_digest_window(
    session: AsyncSession, *, frequency: str, window_key: str
) -> dict[str, Any]:
    if frequency not in {"daily_digest", "weekly_digest"}:
        raise VavError(
            "NOTIFICATION_DIGEST_FREQUENCY_INVALID",
            "Digest frequency is invalid.",
            status_code=422,
        )
    items = list(
        (
            await session.execute(
                text(
                    "SELECT id,user_id,category FROM notification_digest_items WHERE status='pending' "
                    "AND digest_frequency=:frequency AND digest_window_key=:window "
                    "ORDER BY created_at FOR UPDATE SKIP LOCKED"
                ),
                {"frequency": frequency, "window": window_key},
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[tuple[UUID, str], list[UUID]] = {}
    for item in items:
        key = (UUID(str(item["user_id"])), str(item["category"]))
        grouped.setdefault(key, []).append(UUID(str(item["id"])))
    dispatched = 0
    for (user_id, category), item_ids in grouped.items():
        user = await _active_user(session, user_id)
        if user is None:
            continue
        dedup_key = f"digest:{frequency}:{window_key}:{category}:{user_id}"
        locale = str(user["preferred_locale"] or get_settings().notification_default_locale)
        variables = _safe_variables({}, "marketing-newsletter", locale, user)
        variables["message"] = f"{len(item_ids)} grouped notifications are available."
        intent_id = await session.scalar(
            text(
                "INSERT INTO notification_intents "
                "(notification_type,category,priority,recipient_type,recipient_reference_id,template_code,"
                "channel_policy,preference_policy,template_variables_encrypted,deduplication_key,status) "
                "VALUES ('digest',:category,'low','user',:user_id,'marketing-newsletter',"
                '\'{"required":["in_app"],"optional":["email"]}\'::jsonb,'
                "'service_optional',:variables,:dedup_key,'created') "
                "ON CONFLICT (deduplication_key) DO NOTHING RETURNING id"
            ),
            {
                "category": category,
                "user_id": user_id,
                "variables": encrypt_notification_data(variables),
                "dedup_key": dedup_key,
            },
        )
        if intent_id is not None:
            await _materialize_intent(
                session,
                intent_id=UUID(str(intent_id)),
                user=user,
                subscription={
                    "template_code": "marketing-newsletter",
                    "category": category,
                    "priority": "low",
                    "preference_policy": "service_optional",
                    "channel_policy": {"required": ["in_app"], "optional": ["email"]},
                },
                variables=variables,
                action_reference={"route_name": "account-notifications", "params": {}},
                expires_at=None,
                dedup_key=dedup_key,
            )
        await session.execute(
            text("UPDATE notification_digest_items SET status='sent' WHERE id=ANY(:item_ids)"),
            {"item_ids": item_ids},
        )
        dispatched += 1
    await session.commit()
    return {"frequency": frequency, "window_key": window_key, "dispatched": dispatched}


async def consume_outbox_events(
    session: AsyncSession, *, limit: int | None = None
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT o.id,o.topic,o.aggregate_type,o.aggregate_id,o.payload,o.created_at "
                    "FROM outbox_events o "
                    "LEFT JOIN notification_events n ON n.source_event_id=o.id "
                    "AND n.source_module=split_part(o.topic,'.',1) WHERE n.id IS NULL "
                    "AND EXISTS(SELECT 1 FROM notification_event_subscriptions s "
                    "WHERE s.source_event_type=o.topic AND s.status='active') "
                    "ORDER BY o.created_at FOR UPDATE OF o SKIP LOCKED LIMIT :limit"
                ),
                {"limit": min(limit or get_settings().notification_worker_batch_size, 1000)},
            )
        )
        .mappings()
        .all()
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        aggregate_id: UUID | None
        try:
            aggregate_id = UUID(str(row["aggregate_id"]))
        except ValueError:
            aggregate_id = None
        result = await ingest_event(
            session,
            IngestNotificationEventRequest(
                source_event_id=UUID(str(row["id"])),
                source_module=str(row["topic"]).split(".", 1)[0],
                event_type=str(row["topic"]),
                event_version=1,
                subject_type=str(row["aggregate_type"]),
                subject_id=aggregate_id,
                payload=dict(row["payload"]),
                occurred_at=row["created_at"],
            ),
        )
        results.append(result)
    return results
