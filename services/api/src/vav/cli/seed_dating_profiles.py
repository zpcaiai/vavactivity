"""Seed a deterministic dating-profile fixture set for tests and demos.

Fixture members carry synthetic values only. No real personal data, no real
photographs and no third-party information are ever seeded.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from vav.cli.seed_dating_taxonomies import seed_dating_taxonomies
from vav.core.database import session_factory
from vav.modules.identity.security import PasswordHasher
from vav.modules.privacy.crypto import encrypt_private

FIXTURES: tuple[dict[str, Any], ...] = (
    {
        "email": "dating-fixture-anna@example.test",
        "display_name": "Anna F.",
        "date_of_birth": "1993-04-12",
        "gender": "female",
        "partner_genders": ["male"],
        "city": "shanghai",
    },
    {
        "email": "dating-fixture-ben@example.test",
        "display_name": "Ben L.",
        "date_of_birth": "1990-09-30",
        "gender": "male",
        "partner_genders": ["female"],
        "city": "shanghai",
    },
    {
        "email": "dating-fixture-clara@example.test",
        "display_name": "Clara W.",
        "date_of_birth": "1996-01-08",
        "gender": "female",
        "partner_genders": ["male"],
        "city": "taipei",
    },
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


async def seed_dating_profiles() -> None:
    await seed_dating_taxonomies()
    async with session_factory() as session:
        release_id = await session.scalar(
            text(
                "SELECT id FROM dating_profile_schema_releases WHERE schema_code='vav-dating-profile' AND status='active'"
            )
        )
        if release_id is None:
            print("No active dating schema release; nothing to seed.")
            return

        hasher = PasswordHasher()
        password_hash = hasher.hash("DatingFixture!2026")
        created = 0
        for index, fixture in enumerate(FIXTURES):
            user_id = await session.scalar(
                text("SELECT id FROM users WHERE email=:email"), {"email": fixture["email"]}
            )
            if user_id is None:
                user_id = await session.scalar(
                    text(
                        "INSERT INTO users (email,display_email,password_hash,status,email_verified_at,preferred_locale,timezone) "
                        "VALUES (:email,:display_email,:hash,'active',now(),'zh-CN','UTC') RETURNING id"
                    ),
                    {
                        "email": fixture["email"],
                        "display_email": fixture["email"],
                        "hash": password_hash,
                    },
                )
            await session.execute(
                text(
                    "INSERT INTO user_profiles (user_id,display_name,date_of_birth_encrypted,gender_code,preferred_locale,timezone,profile_status) "
                    "VALUES (:user_id,:name,:dob,:gender,'zh-CN','UTC','complete') "
                    "ON CONFLICT (user_id) DO UPDATE SET display_name=EXCLUDED.display_name,"
                    "date_of_birth_encrypted=EXCLUDED.date_of_birth_encrypted,gender_code=EXCLUDED.gender_code"
                ),
                {
                    "user_id": user_id,
                    "name": fixture["display_name"],
                    "dob": encrypt_private(fixture["date_of_birth"]),
                    "gender": fixture["gender"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO user_privacy_settings (user_id,visible_in_matchmaking,privacy_mode) "
                    "VALUES (:user_id,true,'strict') ON CONFLICT (user_id) DO UPDATE SET visible_in_matchmaking=true"
                ),
                {"user_id": user_id},
            )

            profile_id = await session.scalar(
                text("SELECT id FROM dating_profiles WHERE user_id=:user_id"), {"user_id": user_id}
            )
            if profile_id is None:
                profile_id = await session.scalar(
                    text(
                        "INSERT INTO dating_profiles (user_id,profile_number,status,review_status,schema_release_id,default_locale,relationship_intent,current_city_code) "
                        "VALUES (:user_id,:number,'draft','not_required',:release,'zh-CN','marriage_oriented',:city) RETURNING id"
                    ),
                    {
                        "user_id": user_id,
                        "number": f"VAV-SEED-{index + 1:04d}",
                        "release": release_id,
                        "city": fixture["city"],
                    },
                )
                created += 1
            for table in (
                "dating_profile_core_details",
                "dating_profile_faith_details",
                "dating_profile_relationship_history",
                "dating_profile_family_details",
                "dating_profile_lifestyle_details",
            ):
                await session.execute(
                    text(
                        f"INSERT INTO {table} (dating_profile_id) VALUES (:id) ON CONFLICT DO NOTHING"
                    ),
                    {"id": profile_id},
                )
            await session.execute(
                text(
                    "UPDATE dating_profile_core_details SET gender_code=:gender,"
                    "eligible_partner_gender_codes=CAST(:partners AS jsonb),age_display_mode='exact_age',"
                    "country_code='CN',region_code='east',city_code=:city,"
                    "primary_language_codes='[\"zh-CN\"]'::jsonb,relocation_willingness='same_country',"
                    "education_level_code='bachelor',occupation_category_code='education',updated_at=now() "
                    "WHERE dating_profile_id=:id"
                ),
                {
                    "gender": fixture["gender"],
                    "partners": _json(fixture["partner_genders"]),
                    "city": fixture["city"],
                    "id": profile_id,
                },
            )
            await session.execute(
                text(
                    "UPDATE dating_profile_faith_details SET faith_status_code='believer_baptized',"
                    "current_church_participation_code='weekly',church_tradition_codes='[\"reformed\"]'::jsonb,"
                    "marriage_faith_importance=5,devotional_life_code='daily',updated_at=now() WHERE dating_profile_id=:id"
                ),
                {"id": profile_id},
            )
            await session.execute(
                text(
                    "UPDATE dating_profile_relationship_history SET marital_status_code='never_married',"
                    "has_children=false,updated_at=now() WHERE dating_profile_id=:id"
                ),
                {"id": profile_id},
            )
            await session.execute(
                text(
                    "UPDATE dating_profile_family_details SET desire_children_code='want_children',updated_at=now() "
                    "WHERE dating_profile_id=:id"
                ),
                {"id": profile_id},
            )
            await session.execute(
                text(
                    "UPDATE dating_profile_lifestyle_details SET daily_schedule_code='standard',"
                    "smoking_status_code='never',alcohol_use_code='never',"
                    'leisure_interest_codes=\'["reading","music"]\'::jsonb,updated_at=now() WHERE dating_profile_id=:id'
                ),
                {"id": profile_id},
            )
            await session.execute(
                text(
                    "INSERT INTO dating_profile_narratives (dating_profile_id,locale,self_introduction,marriage_vision,moderation_status) "
                    "VALUES (:id,'zh-CN',:intro,:vision,'review_required') "
                    "ON CONFLICT (dating_profile_id,locale) DO UPDATE SET self_introduction=EXCLUDED.self_introduction"
                ),
                {
                    "id": profile_id,
                    "intro": (
                        "这是一段用于本地测试的合成自我介绍文本，用来验证长度校验、内容筛查与展示投影是否正常工作。"
                        "它不包含任何真实个人信息，也不代表任何真实用户的陈述内容。"
                    ),
                    "vision": "希望在信仰里彼此扶持，一同建立家庭。",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO partner_preference_profiles (user_id,dating_profile_id,schema_release_id,status) "
                    "VALUES (:user_id,:profile_id,:release,'confirmed') "
                    "ON CONFLICT (dating_profile_id) DO UPDATE SET status='confirmed'"
                ),
                {"user_id": user_id, "profile_id": profile_id, "release": release_id},
            )
            preference_id = await session.scalar(
                text("SELECT id FROM partner_preference_profiles WHERE dating_profile_id=:id"),
                {"id": profile_id},
            )
            for criterion in (
                {
                    "code": "age_range",
                    "operator": "range",
                    "value": {"minimum": 25, "maximum": 40},
                    "importance": "required",
                    "hard": True,
                },
                {
                    "code": "faith_status_code",
                    "operator": "in",
                    "value": ["believer_baptized", "believer_not_baptized"],
                    "importance": "very_important",
                    "hard": False,
                },
            ):
                await session.execute(
                    text(
                        "INSERT INTO partner_preference_criteria "
                        "(partner_preference_profile_id,criterion_code,operator,desired_value,importance,hard_constraint) "
                        "VALUES (:profile_id,:code,:operator,CAST(:value AS jsonb),:importance,:hard) "
                        "ON CONFLICT (partner_preference_profile_id,criterion_code) DO NOTHING"
                    ),
                    {
                        "profile_id": preference_id,
                        "code": criterion["code"],
                        "operator": criterion["operator"],
                        "value": _json(criterion["value"]),
                        "importance": criterion["importance"],
                        "hard": criterion["hard"],
                    },
                )
        await session.commit()
    print(
        f"Dating profile seed complete: {len(FIXTURES)} fixtures ({created} new) at "
        f"{datetime.now(UTC).isoformat(timespec='seconds')}"
    )


if __name__ == "__main__":
    asyncio.run(seed_dating_profiles())
