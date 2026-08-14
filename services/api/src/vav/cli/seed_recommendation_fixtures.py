"""Seed synthetic, recommendation-eligible dating profiles.

Every value here is invented for local runs, evaluation and tests. No real
member profile is ever copied into a fixture, which is exactly what the
evaluation dataset policy requires.

The fixtures are driven into the same state the Batch 13 review flow produces —
an approved immutable version, a completeness snapshot, an approved primary
photo and confirmed preferences — and then handed to the real projection
builder, so Batch 14 consumes the production contract rather than a shortcut.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.cli.seed_dating_taxonomies import seed_dating_taxonomies
from vav.core.database import session_factory
from vav.modules.identity.security import PasswordHasher
from vav.modules.matchmaking_profiles.service import rebuild_projection
from vav.modules.privacy.crypto import encrypt_private

FIXTURE_PREFIX = "recommendation-fixture"

#: Synthetic members designed to exercise matching, exclusion and diversity.
FIXTURES: tuple[dict[str, Any], ...] = (
    {
        "key": "mei",
        "display_name": "Mei R.",
        "birth_year": 1993,
        "gender": "female",
        "partner_genders": ["male"],
        "city": "shanghai",
        "region": "east",
        "faith": "believer_baptized",
        "tradition": "reformed",
        "faith_importance": 5,
        "languages": ["zh-CN", "en"],
        "interests": ["reading", "music", "hiking"],
        "smoking": "never",
        "children": "want_children",
        "age_range": {"minimum": 28, "maximum": 42},
    },
    {
        "key": "jonathan",
        "display_name": "Jonathan T.",
        "birth_year": 1990,
        "gender": "male",
        "partner_genders": ["female"],
        "city": "shanghai",
        "region": "east",
        "faith": "believer_baptized",
        "tradition": "reformed",
        "faith_importance": 5,
        "languages": ["zh-CN", "en"],
        "interests": ["reading", "music", "cooking"],
        "smoking": "never",
        "children": "want_children",
        "age_range": {"minimum": 26, "maximum": 38},
    },
    {
        "key": "daniel",
        "display_name": "Daniel K.",
        "birth_year": 1988,
        "gender": "male",
        "partner_genders": ["female"],
        "city": "hangzhou",
        "region": "east",
        "faith": "believer_not_baptized",
        "tradition": "baptist",
        "faith_importance": 3,
        "languages": ["zh-CN"],
        "interests": ["sports", "travel"],
        "smoking": "occasionally",
        "children": "open_to_children",
        "age_range": {"minimum": 25, "maximum": 40},
    },
    {
        "key": "grace",
        "display_name": "Grace H.",
        "birth_year": 1995,
        "gender": "female",
        "partner_genders": ["male"],
        "city": "hangzhou",
        "region": "east",
        "faith": "believer_baptized",
        "tradition": "baptist",
        "faith_importance": 4,
        "languages": ["zh-CN"],
        "interests": ["cooking", "travel"],
        "smoking": "never",
        "children": "want_children",
        "age_range": {"minimum": 28, "maximum": 44},
    },
    {
        "key": "peter",
        "display_name": "Peter S.",
        "birth_year": 1986,
        "gender": "male",
        "partner_genders": ["female"],
        "city": "taipei",
        "region": "taiwan",
        "faith": "believer_baptized",
        "tradition": "reformed",
        "faith_importance": 5,
        "languages": ["zh-TW", "en"],
        "interests": ["reading", "hiking"],
        "smoking": "never",
        "children": "want_children",
        "age_range": {"minimum": 26, "maximum": 40},
    },
    {
        "key": "hannah",
        "display_name": "Hannah C.",
        "birth_year": 1992,
        "gender": "female",
        "partner_genders": ["male"],
        "city": "taipei",
        "region": "taiwan",
        "faith": "believer_baptized",
        "tradition": "reformed",
        "faith_importance": 5,
        "languages": ["zh-TW", "en"],
        "interests": ["music", "hiking"],
        "smoking": "never",
        "children": "want_children",
        "age_range": {"minimum": 30, "maximum": 45},
    },
    {
        "key": "michael",
        "display_name": "Michael L.",
        "birth_year": 1991,
        "gender": "male",
        "partner_genders": ["female"],
        "city": "shanghai",
        "region": "east",
        "faith": "believer_baptized",
        "tradition": "reformed",
        "faith_importance": 5,
        "languages": ["zh-CN", "en"],
        "interests": ["reading", "hiking", "cooking"],
        "smoking": "never",
        "children": "want_children",
        "age_range": {"minimum": 27, "maximum": 39},
    },
    {
        "key": "samuel",
        "display_name": "Samuel W.",
        "birth_year": 1989,
        "gender": "male",
        "partner_genders": ["female"],
        "city": "hangzhou",
        "region": "east",
        "faith": "believer_not_baptized",
        "tradition": "baptist",
        "faith_importance": 4,
        "languages": ["zh-CN"],
        "interests": ["music", "travel", "reading"],
        "smoking": "never",
        "children": "open_to_children",
        "age_range": {"minimum": 27, "maximum": 40},
    },
    {
        "key": "isaac",
        "display_name": "Isaac C.",
        "birth_year": 1992,
        "gender": "male",
        "partner_genders": ["female"],
        "city": "taipei",
        "region": "taiwan",
        "faith": "believer_baptized",
        "tradition": "reformed",
        "faith_importance": 5,
        "languages": ["zh-TW", "en"],
        "interests": ["reading", "music", "hiking"],
        "smoking": "never",
        "children": "want_children",
        "age_range": {"minimum": 28, "maximum": 39},
    },
)

PASSWORD = "RecommendationFixture!2026"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _email(key: str) -> str:
    # `EmailStr` correctly rejects the reserved `.test` suffix at login time.
    # `example.com` is accepted by the same validator and remains non-deliverable
    # test data by convention.
    return f"{FIXTURE_PREFIX}-{key}@example.com"


async def _ensure_user(session: AsyncSession, fixture: dict[str, Any], password_hash: str) -> Any:
    email = _email(str(fixture["key"]))
    user_id = await session.scalar(
        text("SELECT id FROM users WHERE email=:email"), {"email": email}
    )
    if user_id is None:
        # Older fixture releases used `.test`, which current `EmailStr`
        # validation correctly refuses at login. Migrate that synthetic row in
        # place so its stable profile number and generated history remain
        # idempotent instead of creating a second fixture identity.
        legacy_email = f"{FIXTURE_PREFIX}-{fixture['key']}@example.test"
        user_id = await session.scalar(
            text("SELECT id FROM users WHERE email=:email"), {"email": legacy_email}
        )
        if user_id is not None:
            await session.execute(
                text(
                    "UPDATE users SET email=:email,display_email=:display_email,password_hash=:hash,"
                    "status='active',email_verified_at=COALESCE(email_verified_at,now()),"
                    "updated_at=now() WHERE id=:id"
                ),
                {
                    "id": user_id,
                    "email": email,
                    "display_email": email,
                    "hash": password_hash,
                },
            )
    if user_id is None:
        user_id = await session.scalar(
            text(
                "INSERT INTO users (email,display_email,password_hash,status,email_verified_at,preferred_locale,timezone) "
                "VALUES (:email,:display_email,:hash,'active',now(),'zh-CN','UTC') RETURNING id"
            ),
            {"email": email, "display_email": email, "hash": password_hash},
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
            "dob": encrypt_private(date(int(fixture["birth_year"]), 6, 15).isoformat()),
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
    return user_id


async def _ensure_photo(session: AsyncSession, *, profile_id: Any, user_id: Any, key: str) -> None:
    """Attach a synthetic approved primary photo.

    The fixture stores no image bytes; it only records the approved photo state
    the eligibility rule checks for.
    """
    existing = await session.scalar(
        text(
            "SELECT id FROM dating_profile_photos WHERE dating_profile_id=:id AND photo_role='primary' "
            "AND deleted_at IS NULL"
        ),
        {"id": profile_id},
    )
    if existing is not None:
        return
    checksum = hashlib.sha256(f"{FIXTURE_PREFIX}:{key}".encode()).hexdigest()
    asset_id = await session.scalar(
        text(
            "INSERT INTO media_assets (storage_provider,bucket_name,object_key,original_filename,"
            "media_type,mime_type,byte_size,width,height,checksum_sha256,visibility,processing_status,uploaded_by) "
            "VALUES ('minio','vav-private',:object_key,'fixture.jpg','image','image/jpeg',1024,600,600,"
            ":checksum,'private','ready',:user_id) "
            "ON CONFLICT (object_key) DO UPDATE SET updated_at=now() RETURNING id"
        ),
        {
            "object_key": f"fixtures/recommendations/{key}.jpg",
            "checksum": checksum,
            "user_id": user_id,
        },
    )
    await session.execute(
        text(
            "INSERT INTO dating_profile_photos (dating_profile_id,media_asset_id,photo_role,status,"
            "visibility,sort_order,content_checksum_sha256,reviewed_at) "
            "VALUES (:profile_id,:asset_id,'primary','approved','verified_members',0,:checksum,now())"
        ),
        {"profile_id": profile_id, "asset_id": asset_id, "checksum": checksum},
    )


def _snapshot_payload(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "basic.gender_code": fixture["gender"],
        "basic.eligible_partner_gender_codes": fixture["partner_genders"],
        "basic.relationship_intent": "marriage_oriented",
        "location.country_code": "CN",
        "location.region_code": fixture["region"],
        "location.city_code": fixture["city"],
        "location.relocation_willingness": "same_country",
        "location.primary_language_codes": fixture["languages"],
        "education_and_work.education_level_code": "bachelor",
        "education_and_work.occupation_category_code": "education",
        "faith.faith_status_code": fixture["faith"],
        "faith.church_tradition_codes": [fixture["tradition"]],
        "faith.current_church_participation_code": "weekly",
        "faith.marriage_faith_importance": fixture["faith_importance"],
        "relationship_history.marital_status_code": "never_married",
        "relationship_history.has_children": False,
        "family.desire_children_code": fixture["children"],
        "lifestyle.daily_schedule_code": "standard",
        "lifestyle.smoking_status_code": fixture["smoking"],
        "lifestyle.alcohol_use_code": "never",
        "lifestyle.leisure_interest_codes": fixture["interests"],
        "lifestyle.communication_preference_codes": ["messaging", "voice_call"],
    }


async def seed_fixtures() -> int:
    await seed_dating_taxonomies()
    hasher = PasswordHasher()
    password_hash = hasher.hash(PASSWORD)
    profile_ids: list[Any] = []

    async with session_factory() as session:
        release_id = await session.scalar(
            text(
                "SELECT id FROM dating_profile_schema_releases WHERE schema_code='vav-dating-profile' AND status='active'"
            )
        )
        if release_id is None:
            print("No active dating schema release; nothing to seed.")
            return 0

        for index, fixture in enumerate(FIXTURES):
            user_id = await _ensure_user(session, fixture, password_hash)
            profile_id = await session.scalar(
                text("SELECT id FROM dating_profiles WHERE user_id=:user_id"), {"user_id": user_id}
            )
            if profile_id is None:
                profile_id = await session.scalar(
                    text(
                        "INSERT INTO dating_profiles (user_id,profile_number,status,review_status,"
                        "schema_release_id,default_locale,relationship_intent,current_city_code) "
                        "VALUES (:user_id,:number,'draft','not_required',:release,'zh-CN','marriage_oriented',:city) RETURNING id"
                    ),
                    {
                        "user_id": user_id,
                        "number": f"VAV-REC-{index + 1:04d}",
                        "release": release_id,
                        "city": fixture["city"],
                    },
                )
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
                    "country_code='CN',region_code=:region,city_code=:city,"
                    "primary_language_codes=CAST(:languages AS jsonb),relocation_willingness='same_country',"
                    "education_level_code='bachelor',occupation_category_code='education',updated_at=now() "
                    "WHERE dating_profile_id=:id"
                ),
                {
                    "gender": fixture["gender"],
                    "partners": _json(fixture["partner_genders"]),
                    "region": fixture["region"],
                    "city": fixture["city"],
                    "languages": _json(fixture["languages"]),
                    "id": profile_id,
                },
            )
            await session.execute(
                text(
                    "UPDATE dating_profile_faith_details SET faith_status_code=:faith,"
                    "current_church_participation_code='weekly',church_tradition_codes=CAST(:tradition AS jsonb),"
                    "marriage_faith_importance=:importance,devotional_life_code='daily',updated_at=now() "
                    "WHERE dating_profile_id=:id"
                ),
                {
                    "faith": fixture["faith"],
                    "tradition": _json([fixture["tradition"]]),
                    "importance": fixture["faith_importance"],
                    "id": profile_id,
                },
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
                    "UPDATE dating_profile_family_details SET desire_children_code=:children,updated_at=now() "
                    "WHERE dating_profile_id=:id"
                ),
                {"children": fixture["children"], "id": profile_id},
            )
            await session.execute(
                text(
                    "UPDATE dating_profile_lifestyle_details SET daily_schedule_code='standard',"
                    "smoking_status_code=:smoking,alcohol_use_code='never',"
                    "leisure_interest_codes=CAST(:interests AS jsonb),"
                    'communication_preference_codes=\'["messaging","voice_call"]\'::jsonb,updated_at=now() '
                    "WHERE dating_profile_id=:id"
                ),
                {
                    "smoking": fixture["smoking"],
                    "interests": _json(fixture["interests"]),
                    "id": profile_id,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO dating_profile_narratives (dating_profile_id,locale,self_introduction,marriage_vision,moderation_status) "
                    "VALUES (:id,'zh-CN',:intro,:vision,'approved') "
                    "ON CONFLICT (dating_profile_id,locale) DO UPDATE SET moderation_status='approved'"
                ),
                {
                    "id": profile_id,
                    "intro": (
                        "这是一段用于推荐引擎本地验证的合成自我介绍，用来检查投影、解释与展示边界是否正确。"
                        "内容为虚构，不代表任何真实用户。"
                    ),
                    "vision": "希望在信仰里彼此扶持，一同建立家庭。",
                },
            )

            await _ensure_photo(
                session, profile_id=profile_id, user_id=user_id, key=str(fixture["key"])
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
                    "value": fixture["age_range"],
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
                {
                    "code": "relationship_intent",
                    "operator": "equals",
                    "value": "marriage_oriented",
                    "importance": "very_important",
                    "hard": False,
                },
                {
                    "code": "leisure_interest_codes",
                    "operator": "contains_any",
                    "value": fixture["interests"],
                    "importance": "nice_to_have",
                    "hard": False,
                },
            ):
                await session.execute(
                    text(
                        "INSERT INTO partner_preference_criteria "
                        "(partner_preference_profile_id,criterion_code,operator,desired_value,importance,hard_constraint) "
                        "VALUES (:profile_id,:code,:operator,CAST(:value AS jsonb),:importance,:hard) "
                        "ON CONFLICT (partner_preference_profile_id,criterion_code) DO UPDATE SET "
                        "operator=EXCLUDED.operator, desired_value=EXCLUDED.desired_value, "
                        "importance=EXCLUDED.importance, hard_constraint=EXCLUDED.hard_constraint"
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

            await _approve_version(session, profile_id=profile_id, user_id=user_id, fixture=fixture)
            profile_ids.append(profile_id)

        await session.commit()

    async with session_factory() as session:
        for profile_id in profile_ids:
            await rebuild_projection(session, profile_id)
    return len(profile_ids)


async def _approve_version(
    session: AsyncSession, *, profile_id: Any, user_id: Any, fixture: dict[str, Any]
) -> None:
    """Record the approved immutable version and completeness snapshot."""
    payload = {"fields": _snapshot_payload(fixture), "preference_criteria": []}
    serialised = _json(payload)
    checksum = hashlib.sha256(serialised.encode()).hexdigest()
    existing = await session.scalar(
        text(
            "SELECT version_number FROM dating_profile_versions WHERE dating_profile_id=:id "
            "AND approved_at IS NOT NULL ORDER BY version_number DESC LIMIT 1"
        ),
        {"id": profile_id},
    )
    if existing is None:
        release_id = await session.scalar(
            text("SELECT schema_release_id FROM dating_profiles WHERE id=:id"), {"id": profile_id}
        )
        await session.execute(
            text(
                "INSERT INTO dating_profile_versions (dating_profile_id,version_number,schema_release_id,"
                "snapshot_encrypted,snapshot_checksum_sha256,change_summary,created_by,review_status,"
                "submitted_at,approved_at) "
                "VALUES (:id,1,:release,:snapshot,:checksum,'fixture seed',:user_id,'approved',now(),now())"
            ),
            {
                "id": profile_id,
                "release": release_id,
                "snapshot": encrypt_private(payload),
                "checksum": checksum,
                "user_id": user_id,
            },
        )
    await session.execute(
        text(
            "INSERT INTO dating_profile_completeness_snapshots (dating_profile_id,profile_version_number,"
            "policy_version,total_basis_points,section_scores,submission_eligible,recommendation_eligible) "
            "VALUES (:id,1,'1.0.0',9500,'{}'::jsonb,true,true) "
            "ON CONFLICT (dating_profile_id,profile_version_number) DO UPDATE SET "
            "recommendation_eligible=true, submission_eligible=true, evaluated_at=now()"
        ),
        {"id": profile_id},
    )
    await session.execute(
        text(
            "UPDATE dating_profiles SET status='active', review_status='approved', "
            "approved_version_number=1, current_version_number=1, approved_at=COALESCE(approved_at, now()), "
            "activated_at=COALESCE(activated_at, now()), updated_at=now() WHERE id=:id"
        ),
        {"id": profile_id},
    )


async def main() -> None:
    count = await seed_fixtures()
    print(
        f"seeded {count} recommendation-eligible fixtures at "
        f"{datetime.now(UTC).isoformat(timespec='seconds')}"
    )


if __name__ == "__main__":
    asyncio.run(main())
