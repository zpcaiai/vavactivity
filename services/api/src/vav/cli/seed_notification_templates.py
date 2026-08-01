# ruff: noqa: E501
from __future__ import annotations

import asyncio
import hashlib
import json

from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.database import session_factory

TEMPLATE_CODES = (
    ("verify-email", "account", "transactional"),
    ("account-activated", "account", "transactional"),
    ("password-changed", "security", "security"),
    ("password-reset-completed", "security", "security"),
    ("suspicious-session", "security", "security"),
    ("order-created", "order", "transactional"),
    ("payment-succeeded", "payment", "transactional"),
    ("payment-failed", "payment", "transactional"),
    ("refund-succeeded", "payment", "transactional"),
    ("subscription-activated", "subscription", "transactional"),
    ("subscription-renewal-failed", "subscription", "transactional"),
    ("subscription-cancelled", "subscription", "transactional"),
    ("registration-approved", "activity", "service"),
    ("registration-confirmed", "activity", "service"),
    ("waitlist-promotion", "activity", "service"),
    ("waitlist-offer-expiring", "activity", "service"),
    ("activity-reminder", "activity", "service"),
    ("checkin-available", "activity", "service"),
    ("activity-cancelled", "activity", "service"),
    ("mutual-choice-created", "matchmaking", "service"),
    ("enrollment-activated", "course", "service"),
    ("content-released", "course", "service"),
    ("assignment-graded", "course", "service"),
    ("assignment-revision-required", "course", "service"),
    ("course-access-expiring", "course", "service"),
    ("course-completed", "course", "service"),
    ("certificate-issued", "course", "service"),
    ("appointment-requested", "counseling", "service"),
    ("appointment-time-proposed", "counseling", "service"),
    ("appointment-payment-required", "counseling", "transactional"),
    ("appointment-confirmed", "counseling", "service"),
    ("appointment-reminder", "counseling", "service"),
    ("appointment-rescheduled", "counseling", "service"),
    ("appointment-cancelled", "counseling", "service"),
    ("session-summary-published", "counseling", "service"),
    ("action-item-due", "counseling", "service"),
    ("follow-up-due", "counseling", "service"),
    ("referral-created", "ai_assistant", "service"),
    ("referral-assigned", "ai_assistant", "service"),
    ("human-message-created", "ai_assistant", "service"),
    ("marketing-newsletter", "marketing", "marketing"),
)
LOCALES = {
    "zh-CN": {
        "title": "VAV 服务通知",
        "body": "{{ user_display_name }}，{{ message }}",
        "action": "查看详情",
    },
    "zh-TW": {
        "title": "VAV 服務通知",
        "body": "{{ user_display_name }}，{{ message }}",
        "action": "查看詳情",
    },
    "en": {
        "title": "VAV service notification",
        "body": "{{ user_display_name }}, {{ message }}",
        "action": "View details",
    },
}
VARIABLE_SCHEMA = {
    "type": "object",
    "required": ["user_display_name", "message"],
    "properties": {
        "user_display_name": {"type": "string", "maxLength": 200},
        "message": {"type": "string", "maxLength": 2000},
        "reference_id": {"type": "string", "maxLength": 128},
    },
    "additionalProperties": False,
}


async def seed_notification_templates() -> None:
    await ensure_system_user()
    async with session_factory() as session:
        for code, category, purpose in TEMPLATE_CODES:
            definition_id = await session.scalar(
                text(
                    "INSERT INTO notification_template_definitions "
                    "(template_code,internal_name,category,purpose,variable_schema,required_channels,"
                    "supported_channels,status) VALUES (:code,:name,:category,:purpose,CAST(:schema AS jsonb),"
                    "'[\"in_app\"]'::jsonb,'[\"in_app\",\"email\"]'::jsonb,'active') "
                    "ON CONFLICT (template_code) DO UPDATE SET internal_name=EXCLUDED.internal_name,"
                    "status='active',updated_at=now() RETURNING id"
                ),
                {
                    "code": code,
                    "name": code.replace("-", " ").title(),
                    "category": category,
                    "purpose": purpose,
                    "schema": json.dumps(VARIABLE_SCHEMA),
                },
            )
            for locale, copy in LOCALES.items():
                for channel in ("in_app", "email"):
                    subject = copy["title"] if channel == "email" else None
                    title = copy["title"] if channel == "in_app" else None
                    body_html = f"<p>{copy['body']}</p>" if channel == "email" else None
                    checksum_source = json.dumps(
                        {
                            "code": code,
                            "locale": locale,
                            "channel": channel,
                            "subject": subject,
                            "title": title,
                            "html": body_html,
                            "text": copy["body"],
                        },
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    await session.execute(
                        text(
                            "INSERT INTO notification_template_releases "
                            "(template_definition_id,semantic_version,locale,channel,subject_template,"
                            "title_template,body_html_template,body_text_template,action_label_template,"
                            "checksum_sha256,status,created_by,approved_by,approved_at,activated_at) "
                            "VALUES (:definition_id,'1.0.0',:locale,:channel,:subject,:title,:html,:text,"
                            ":action,:checksum,'active',:system_user,:system_user,now(),now()) "
                            "ON CONFLICT (template_definition_id,semantic_version,locale,channel) DO NOTHING"
                        ),
                        {
                            "definition_id": definition_id,
                            "locale": locale,
                            "channel": channel,
                            "subject": subject,
                            "title": title,
                            "html": body_html,
                            "text": copy["body"],
                            "action": copy["action"],
                            "checksum": hashlib.sha256(checksum_source.encode()).hexdigest(),
                            "system_user": SYSTEM_USER_ID,
                        },
                    )
        await session.commit()
    print(
        f"Notification template seed complete: {len(TEMPLATE_CODES)} definitions, "
        f"{len(TEMPLATE_CODES) * len(LOCALES) * 2} active releases"
    )


if __name__ == "__main__":
    asyncio.run(seed_notification_templates())
