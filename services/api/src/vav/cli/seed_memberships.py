"""Seed governed Batch 17 benefits and a safe free fallback plan."""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.config import get_settings
from vav.core.database import session_factory

BENEFITS = {
    "platform.basic_access": ("capability", "platform"),
    "ai.assistant.access": ("capability", "ai"),
    "ai.message_quota": ("quota", "ai"),
    "recommendation.daily_received_limit": ("limit_override", "recommendations"),
    "recommendation.advanced_filters": ("capability", "recommendations"),
    "recommendation.batch_frequency": ("limit_override", "recommendations"),
    "recommendation.feedback_personalization": ("capability", "recommendations"),
    "course.catalog_access": ("resource_scope", "courses"),
    "course.category_access": ("resource_scope", "courses"),
    "course.bundle_access": ("resource_scope", "courses"),
    "activity.priority_registration": ("priority_access", "activities"),
    "activity.member_ticket_access": ("resource_scope", "activities"),
    "counseling.booking_access": ("capability", "counseling"),
    "counseling.discount_eligibility": ("price_benefit", "counseling"),
    "privacy.data_export_priority": ("priority_access", "privacy"),
    "support.priority_queue": ("priority_access", "support"),
}


async def seed_memberships() -> None:
    settings = get_settings()
    if not settings.membership_require_active_entitlement:
        raise RuntimeError("paid membership must require an active entitlement")
    if settings.membership_allow_multiple_paid_plans:
        raise RuntimeError("stacked paid memberships are not approved")
    await ensure_system_user()
    async with session_factory() as session:
        actor = SYSTEM_USER_ID
        definition_ids: dict[str, object] = {}
        for code, (benefit_type, module) in BENEFITS.items():
            schema = (
                {"type": "object", "required": ["limit", "period"]}
                if benefit_type == "quota"
                else {"type": "object"}
            )
            await session.execute(
                text(
                    "INSERT INTO membership_benefit_definitions "
                    "(benefit_code,semantic_version,benefit_type,value_schema,owning_module,sensitivity,status) "
                    "VALUES (:code,'1.0.0',:type,CAST(:schema AS jsonb),:module,'internal','active') "
                    "ON CONFLICT (benefit_code,semantic_version) DO UPDATE SET status='active'"
                ),
                {
                    "code": code,
                    "type": benefit_type,
                    "schema": json.dumps(schema),
                    "module": module,
                },
            )
            definition_ids[code] = (
                await session.execute(
                    text(
                        "SELECT id FROM membership_benefit_definitions WHERE benefit_code=:code AND semantic_version='1.0.0'"
                    ),
                    {"code": code},
                )
            ).scalar_one()
        plan_code = settings.membership_default_free_plan
        plan_id = (
            await session.execute(
                text(
                    "INSERT INTO membership_plans "
                    "(plan_code,internal_name,plan_type,status,default_locale,display_order,created_by,updated_by) "
                    "VALUES (:code,'Free Membership','free','draft','en',0,:actor,:actor) "
                    "ON CONFLICT (plan_code) DO UPDATE SET updated_at=now() RETURNING id"
                ),
                {"code": plan_code, "actor": actor},
            )
        ).scalar_one()
        version = (
            await session.execute(
                text(
                    "INSERT INTO membership_plan_versions "
                    "(membership_plan_id,version_number,semantic_version,status,benefit_manifest,access_policy_snapshot,quota_policy_snapshot,valid_from,created_by,activated_at) "
                    "VALUES (:plan,1,'1.0.0','active',CAST(:manifest AS jsonb),CAST(:access AS jsonb),CAST(:quota AS jsonb),now(),:actor,now()) "
                    "ON CONFLICT (membership_plan_id,version_number) DO UPDATE SET status='active' RETURNING id"
                ),
                {
                    "plan": plan_id,
                    "actor": actor,
                    "manifest": json.dumps(
                        ["platform.basic_access", "ai.message_quota", "course.catalog_access"]
                    ),
                    "access": json.dumps({"safety_bypass": False, "privacy_bypass": False}),
                    "quota": json.dumps({"rollover": False}),
                },
            )
        ).scalar_one()
        for locale, name, description in (
            ("en", "Free", "Core platform access with a small monthly AI allowance."),
            ("zh-CN", "免费会员", "包含平台基础访问和少量周期 AI 配额。"),
        ):
            await session.execute(
                text(
                    "INSERT INTO membership_plan_localizations "
                    "(membership_plan_version_id,locale,name,short_description,benefit_summary,limitation_summary) "
                    "VALUES (:version,:locale,:name,:description,CAST(:benefits AS jsonb),CAST(:limitations AS jsonb)) "
                    "ON CONFLICT (membership_plan_version_id,locale) DO UPDATE SET name=EXCLUDED.name,short_description=EXCLUDED.short_description"
                ),
                {
                    "version": version,
                    "locale": locale,
                    "name": name,
                    "description": description,
                    "benefits": json.dumps(
                        ["platform.basic_access", "course.catalog_access", "ai.message_quota"]
                    ),
                    "limitations": json.dumps(
                        ["AI usage is quota limited", "Safety and privacy rules always apply"]
                    ),
                },
            )
        values = {
            "platform.basic_access": {"enabled": True},
            "course.catalog_access": {"scope_type": "all"},
            "ai.message_quota": {
                "limit": 10,
                "unit": "messages",
                "period": "calendar_month",
                "rollover": False,
            },
        }
        for order, (code, value) in enumerate(values.items()):
            await session.execute(
                text(
                    "INSERT INTO membership_plan_benefits "
                    "(membership_plan_version_id,benefit_definition_id,benefit_value,sort_order) "
                    "VALUES (:version,:definition,CAST(:value AS jsonb),:sort) "
                    "ON CONFLICT (membership_plan_version_id,benefit_definition_id) DO UPDATE SET benefit_value=EXCLUDED.benefit_value"
                ),
                {
                    "version": version,
                    "definition": definition_ids[code],
                    "value": json.dumps(value),
                    "sort": order,
                },
            )
        await session.execute(
            text(
                "UPDATE membership_plans SET status='active',current_version_id=:version,updated_at=now() WHERE id=:plan"
            ),
            {"version": version, "plan": plan_id},
        )
        await session.commit()
    print(f"Membership registry ready: {len(BENEFITS)} benefits; free plan={plan_code}")


if __name__ == "__main__":
    asyncio.run(seed_memberships())
