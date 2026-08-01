# ruff: noqa: E501
from __future__ import annotations

import asyncio
import hashlib
import json

from sqlalchemy import text

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.database import session_factory

CONSENTS: tuple[tuple[str, str, bool, bool], ...] = (
    ("platform_terms", "service", True, False),
    ("privacy_policy", "service", True, False),
    ("ai_assistant_use", "ai", False, True),
    ("ai_long_term_memory", "ai", False, True),
    ("ai_profile_context_access", "ai", False, True),
    ("ai_service_history_access", "ai", False, True),
    ("marketing_email", "marketing", False, True),
    ("activity_directory_visibility", "visibility", False, True),
    ("activity_post_event_choice", "visibility", False, True),
    ("counseling_data_processing", "counseling", False, True),
    ("counseling_recording", "counseling", False, True),
    ("counseling_transcription", "counseling", False, True),
    ("testimonial_publication", "publication", False, True),
    ("external_model_training", "ai_training", False, True),
)
LOCALES = ("zh-CN", "zh-TW", "en")


async def seed_privacy() -> None:
    await ensure_system_user()
    async with session_factory() as session:
        for code, category, required, withdrawable in CONSENTS:
            definition_id = await session.scalar(
                text(
                    "INSERT INTO consent_definitions "
                    "(consent_code,category,required_for_service,withdrawable,scope_definition,evidence_requirements) "
                    "VALUES (:code,:category,:required,:withdrawable,CAST(:scope AS jsonb),CAST(:evidence AS jsonb)) "
                    "ON CONFLICT (consent_code) DO UPDATE SET category=EXCLUDED.category,"
                    "required_for_service=EXCLUDED.required_for_service,withdrawable=EXCLUDED.withdrawable,"
                    "updated_at=now() RETURNING id"
                ),
                {
                    "code": code,
                    "category": category,
                    "required": required,
                    "withdrawable": withdrawable,
                    "scope": json.dumps({"consent_code": code, "purposes": [category]}),
                    "evidence": json.dumps({"required": ["release_id", "timestamp", "source"]}),
                },
            )
            for locale in LOCALES:
                title = f"{code} ({locale})"
                summary = (
                    "This is an operational baseline consent release. Legal wording and jurisdictional "
                    "approval remain an external production gate."
                )
                checksum = hashlib.sha256(f"{title}\n{summary}".encode()).hexdigest()
                await session.execute(
                    text(
                        "INSERT INTO consent_releases "
                        "(consent_definition_id,semantic_version,locale,title,summary,status,valid_from,"
                        "checksum_sha256,approved_by,approved_at) "
                        "VALUES (:definition,'1.0.0',:locale,:title,:summary,'active',now(),:checksum,:actor,now()) "
                        "ON CONFLICT (consent_definition_id,semantic_version,locale) DO NOTHING"
                    ),
                    {
                        "definition": definition_id,
                        "locale": locale,
                        "title": title,
                        "summary": summary,
                        "checksum": checksum,
                        "actor": SYSTEM_USER_ID,
                    },
                )

        await session.execute(
            text(
                "INSERT INTO user_profiles (user_id,display_name,preferred_locale,timezone,profile_status) "
                "SELECT id,display_email,preferred_locale,timezone,'incomplete' FROM users "
                "ON CONFLICT (user_id) DO NOTHING"
            )
        )
        await session.execute(
            text(
                "INSERT INTO user_privacy_settings (user_id,privacy_mode) "
                "SELECT id,'strict' FROM users ON CONFLICT (user_id) DO NOTHING"
            )
        )
        await session.execute(
            text(
                "INSERT INTO ai_memory_preferences (user_id,long_term_memory_enabled) "
                "SELECT id,false FROM users ON CONFLICT (user_id) DO NOTHING"
            )
        )
        await session.commit()

    print(
        f"Privacy seed complete: {len(CONSENTS)} consent definitions, "
        f"{len(CONSENTS) * len(LOCALES)} localized baseline releases; external training remains opt-in."
    )


if __name__ == "__main__":
    asyncio.run(seed_privacy())
