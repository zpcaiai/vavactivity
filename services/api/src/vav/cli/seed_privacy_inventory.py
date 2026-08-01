# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.database import session_factory

ASSETS: tuple[tuple[str, str, str, str, str, str, bool, bool, str, int], ...] = (
    (
        "identity.profile",
        "identity",
        "user_profiles",
        "profile",
        "confidential",
        "delete",
        True,
        True,
        "privacy.identity.profile",
        730,
    ),
    (
        "identity.contacts",
        "identity",
        "user_contact_points",
        "contact",
        "highly_restricted",
        "delete",
        True,
        True,
        "privacy.identity.contacts",
        365,
    ),
    (
        "identity.security",
        "identity",
        "auth_sessions",
        "security",
        "restricted",
        "retain_restricted",
        False,
        False,
        "privacy.identity.security",
        730,
    ),
    (
        "commerce.orders",
        "commerce",
        "orders",
        "financial",
        "restricted",
        "retain_restricted",
        True,
        False,
        "privacy.commerce.orders",
        2555,
    ),
    (
        "commerce.payments",
        "commerce",
        "payment_attempts",
        "financial",
        "highly_restricted",
        "retain_restricted",
        True,
        False,
        "privacy.commerce.payments",
        2555,
    ),
    (
        "activities.registrations",
        "activities",
        "activity_registrations",
        "service_history",
        "confidential",
        "anonymize",
        True,
        True,
        "privacy.activities.registrations",
        1095,
    ),
    (
        "courses.enrollments",
        "courses",
        "course_enrollments",
        "service_history",
        "confidential",
        "anonymize",
        True,
        True,
        "privacy.courses.enrollments",
        1095,
    ),
    (
        "courses.certificates",
        "courses",
        "course_certificates",
        "credential",
        "restricted",
        "retain_restricted",
        True,
        False,
        "privacy.courses.certificates",
        2555,
    ),
    (
        "counseling.appointments",
        "counseling",
        "counseling_appointments",
        "service_history",
        "restricted",
        "retain_restricted",
        True,
        True,
        "privacy.counseling.appointments",
        2555,
    ),
    (
        "counseling.private_records",
        "counseling",
        "counseling_records",
        "counseling",
        "highly_restricted",
        "manual_review",
        False,
        False,
        "privacy.counseling.records",
        2555,
    ),
    (
        "knowledge.queries",
        "knowledge",
        "knowledge_retrieval_queries",
        "usage",
        "confidential",
        "delete",
        False,
        False,
        "privacy.knowledge.queries",
        90,
    ),
    (
        "ai.conversations",
        "ai",
        "ai_conversations",
        "conversation",
        "restricted",
        "delete",
        True,
        False,
        "privacy.ai.conversations",
        365,
    ),
    (
        "ai.memories",
        "ai",
        "ai_memory_items",
        "inferred_profile",
        "highly_restricted",
        "delete",
        True,
        True,
        "privacy.ai.memories",
        365,
    ),
    (
        "notifications.in_app",
        "notifications",
        "user_notifications",
        "communications",
        "confidential",
        "delete",
        True,
        False,
        "privacy.notifications.in_app",
        365,
    ),
    (
        "notifications.deliveries",
        "notifications",
        "notification_deliveries",
        "delivery_audit",
        "restricted",
        "retain_restricted",
        True,
        False,
        "privacy.notifications.deliveries",
        365,
    ),
    (
        "notifications.preferences",
        "notifications",
        "notification_preferences",
        "preference",
        "confidential",
        "delete",
        True,
        True,
        "privacy.notifications.preferences",
        365,
    ),
)


async def seed_privacy_inventory() -> None:
    await ensure_system_user()
    async with session_factory() as session:
        for (
            asset_code,
            module,
            entity,
            category,
            sensitivity,
            erasure,
            export,
            correction,
            policy,
            days,
        ) in ASSETS:
            await session.execute(
                text(
                    "INSERT INTO privacy_retention_policies "
                    "(policy_code,semantic_version,data_category,module_code,trigger_event,retention_days,"
                    "expiration_action,policy_basis,status,approved_by,approved_at,valid_from) "
                    "VALUES (:policy,'1.0.0',:category,:module,'record_created',:days,:action,"
                    ":basis,'active',:actor,now(),now()) ON CONFLICT (policy_code,semantic_version) DO NOTHING"
                ),
                {
                    "policy": policy,
                    "category": category,
                    "module": module,
                    "days": days,
                    "action": "manual_review"
                    if erasure in {"manual_review", "retain_restricted"}
                    else erasure,
                    "basis": "Operational baseline pending jurisdiction-specific legal approval.",
                    "actor": SYSTEM_USER_ID,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO privacy_data_assets "
                    "(asset_code,module_code,storage_type,entity_name,field_path,data_category,sensitivity,"
                    "processing_purposes,lawful_or_policy_basis,export_supported,correction_supported,"
                    "erasure_mode,retention_policy_code,owner_team) "
                    "VALUES (:asset,:module,'postgresql',:entity,'*',:category,:sensitivity,"
                    "CAST(:purposes AS jsonb),CAST(:basis AS jsonb),:export,:correction,:erasure,:policy,:owner) "
                    "ON CONFLICT (asset_code) DO UPDATE SET sensitivity=EXCLUDED.sensitivity,"
                    "erasure_mode=EXCLUDED.erasure_mode,retention_policy_code=EXCLUDED.retention_policy_code,updated_at=now()"
                ),
                {
                    "asset": asset_code,
                    "module": module,
                    "entity": entity,
                    "category": category,
                    "sensitivity": sensitivity,
                    "purposes": json.dumps(["service_delivery", "security", "user_rights"]),
                    "basis": json.dumps(["service_contract", "user_consent_or_approved_policy"]),
                    "export": export,
                    "correction": correction,
                    "erasure": erasure,
                    "policy": policy,
                    "owner": f"{module}-team",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO privacy_field_classifications "
                    "(asset_code,field_path,sensitivity,data_category,encryption_required,masking_policy_code,"
                    "access_policy_code,log_policy,export_policy,erasure_mode,approved_by) "
                    "VALUES (:asset,'*',:sensitivity,:category,:encrypted,:masking,:access,'no_values',"
                    ":export_policy,:erasure,:actor) ON CONFLICT (asset_code,field_path) DO UPDATE SET "
                    "sensitivity=EXCLUDED.sensitivity,encryption_required=EXCLUDED.encryption_required,updated_at=now()"
                ),
                {
                    "asset": asset_code,
                    "sensitivity": sensitivity,
                    "category": category,
                    "encrypted": sensitivity in {"restricted", "highly_restricted"},
                    "masking": "masked_by_default" if sensitivity != "public" else None,
                    "access": "purpose_and_permission_required",
                    "export_policy": "include_minimized" if export else "exclude",
                    "erasure": erasure,
                    "actor": SYSTEM_USER_ID,
                },
            )

        for module in sorted({item[1] for item in ASSETS}):
            await session.execute(
                text(
                    "INSERT INTO privacy_processing_activities "
                    "(activity_code,name,purpose,data_categories,data_subject_types,recipient_categories,"
                    "external_processors,retention_policy_codes,automated_decisioning,ai_involved,owner_team,status) "
                    "VALUES (:code,:name,'Provide the explicitly requested VAV service',CAST(:categories AS jsonb),"
                    "'[\"account_user\"]'::jsonb,'[\"authorized_platform_operators\"]'::jsonb,'[]'::jsonb,"
                    "CAST(:policies AS jsonb),false,:ai,:owner,'active') ON CONFLICT (activity_code) DO UPDATE SET updated_at=now()"
                ),
                {
                    "code": f"{module}.service_delivery",
                    "name": f"{module.title()} service delivery",
                    "categories": json.dumps(
                        sorted({item[3] for item in ASSETS if item[1] == module})
                    ),
                    "policies": json.dumps([item[8] for item in ASSETS if item[1] == module]),
                    "ai": module == "ai",
                    "owner": f"{module}-team",
                },
            )
        await session.commit()

    print(f"Privacy inventory seed complete: {len(ASSETS)} assets across 8 provider modules.")


if __name__ == "__main__":
    asyncio.run(seed_privacy_inventory())
