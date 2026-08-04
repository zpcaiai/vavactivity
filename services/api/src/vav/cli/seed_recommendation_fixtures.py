"""Seed a balanced synthetic cohort of approved, recommendable profiles.

Everything here is synthetic. No real member data is ever copied into a
development or evaluation fixture set.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.core.database import session_factory
from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.matchmaking_profiles import review as profile_review
from vav.modules.matchmaking_profiles import service as profile_service
from vav.modules.privacy.crypto import encrypt_private
from vav.modules.recommendations.service import json_value

PASSWORD = "VavRecommendation!2026_Secure#"

SELF_INTRODUCTION = (
    "这是一段用于推荐系统本地测试的合成自我介绍文本，用来验证候选生成、硬条件过滤、双向评分、"
    "排序多样化以及解释输出是否按预期工作。文本长度刻意超过平台设置的自我介绍最小字数要求，"
    "以便完整走通提交与审核流程。它不包含任何真实个人信息，也不代表任何真实用户的陈述内容。"
)

#: A balanced cohort so bidirectional eligibility can actually be satisfied.
COHORT: tuple[dict[str, Any], ...] = (
    {
        "key": "rec-f1",
        "gender": "female",
        "wants": ["male"],
        "city": "shanghai",
        "region": "east",
        "birth": 1993,
        "faith": "believer_baptized",
        "tradition": "reformed",
        "importance": 5,
        "intent": "marriage_oriented",
        "schedule": "standard",
        "interests": ["reading", "music"],
    },
    {
        "key": "rec-f2",
        "gender": "female",
        "wants": ["male"],
        "city": "shanghai",
        "region": "east",
        "birth": 1990,
        "faith": "believer_baptized",
        "tradition": "baptist",
        "importance": 4,
        "intent": "marriage_oriented",
        "schedule": "early_riser",
        "interests": ["outdoors", "music"],
    },
    {
        "key": "rec-f3",
        "gender": "female",
        "wants": ["male"],
        "city": "taipei",
        "region": "taiwan",
        "birth": 1996,
        "faith": "believer_not_baptized",
        "tradition": "non_denominational",
        "importance": 4,
        "intent": "serious_relationship",
        "schedule": "night_owl",
        "interests": ["arts", "travel"],
    },
    {
        "key": "rec-f4",
        "gender": "female",
        "wants": ["male"],
        "city": "beijing",
        "region": "north",
        "birth": 1988,
        "faith": "believer_baptized",
        "tradition": "house_church",
        "importance": 5,
        "intent": "marriage_oriented",
        "schedule": "standard",
        "interests": ["reading", "volunteering"],
    },
    {
        "key": "rec-m1",
        "gender": "male",
        "wants": ["female"],
        "city": "shanghai",
        "region": "east",
        "birth": 1991,
        "faith": "believer_baptized",
        "tradition": "reformed",
        "importance": 5,
        "intent": "marriage_oriented",
        "schedule": "standard",
        "interests": ["reading", "sports"],
    },
    {
        "key": "rec-m2",
        "gender": "male",
        "wants": ["female"],
        "city": "shanghai",
        "region": "east",
        "birth": 1989,
        "faith": "believer_baptized",
        "tradition": "baptist",
        "importance": 4,
        "intent": "marriage_oriented",
        "schedule": "early_riser",
        "interests": ["music", "outdoors"],
    },
    {
        "key": "rec-m3",
        "gender": "male",
        "wants": ["female"],
        "city": "taipei",
        "region": "taiwan",
        "birth": 1994,
        "faith": "believer_not_baptized",
        "tradition": "non_denominational",
        "importance": 3,
        "intent": "serious_relationship",
        "schedule": "night_owl",
        "interests": ["arts", "travel"],
    },
    {
        "key": "rec-m4",
        "gender": "male",
        "wants": ["female"],
        "city": "beijing",
        "region": "north",
        "birth": 1987,
        "faith": "believer_baptized",
        "tradition": "house_church",
        "importance": 5,
        "intent": "marriage_oriented",
        "schedule": "standard",
        "interests": ["volunteering", "study"],
    },
)


async def _ensure_reviewer(session: AsyncSession) -> User:
    email = "rec-fixture-reviewer@example.test"
    user_id = await session.scalar(
        text("SELECT id FROM users WHERE email=:email"), {"email": email}
    )
    if user_id is None:
        user_id = await session.scalar(
            text(
                "INSERT INTO users (email,display_email,password_hash,status,email_verified_at,preferred_locale,timezone) "
                "VALUES (:email,:display,:hash,'active',now(),'zh-CN','UTC') RETURNING id"
            ),
            {"email": email, "display": email, "hash": PasswordHasher().hash(PASSWORD)},
        )
    for role_code in ("profile_reviewer", "profile_review_lead"):
        role_id = await session.scalar(
            text("SELECT id FROM roles WHERE code=:code"), {"code": role_code}
        )
        if role_id is not None:
            await session.execute(
                text(
                    "INSERT INTO user_roles (user_id,role_id,granted_by,grant_reason) "
                    "VALUES (:user_id,:role_id,:user_id,'recommendation fixture seed') ON CONFLICT DO NOTHING"
                ),
                {"user_id": user_id, "role_id": role_id},
            )
    await session.commit()
    reviewer = await session.get(User, UUID(str(user_id)))
    assert reviewer is not None
    return reviewer


async def _ensure_member(session: AsyncSession, spec: dict[str, Any]) -> User:
    email = f"{spec['key']}@example.test"
    user_id = await session.scalar(
        text("SELECT id FROM users WHERE email=:email"), {"email": email}
    )
    if user_id is None:
        user_id = await session.scalar(
            text(
                "INSERT INTO users (email,display_email,password_hash,status,email_verified_at,preferred_locale,timezone) "
                "VALUES (:email,:display,:hash,'active',now(),'zh-CN','Asia/Shanghai') RETURNING id"
            ),
            {"email": email, "display": email, "hash": PasswordHasher().hash(PASSWORD)},
        )
    await session.execute(
        text(
            "INSERT INTO user_profiles (user_id,display_name,date_of_birth_encrypted,preferred_locale,timezone,profile_status) "
            "VALUES (:id,:name,:dob,'zh-CN','Asia/Shanghai','complete') "
            "ON CONFLICT (user_id) DO UPDATE SET date_of_birth_encrypted=EXCLUDED.date_of_birth_encrypted"
        ),
        {
            "id": user_id,
            "name": spec["key"].replace("-", " ").title(),
            "dob": encrypt_private(date(int(spec["birth"]), 5, 20).isoformat()),
        },
    )
    await session.execute(
        text(
            "INSERT INTO user_privacy_settings (user_id,visible_in_matchmaking,privacy_mode) "
            "VALUES (:id,true,'strict') ON CONFLICT (user_id) DO UPDATE SET visible_in_matchmaking=true"
        ),
        {"id": user_id},
    )
    await session.commit()
    member = await session.get(User, UUID(str(user_id)))
    assert member is not None
    return member


def _fields(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "basic.gender_code": spec["gender"],
        "basic.eligible_partner_gender_codes": list(spec["wants"]),
        "basic.age_display_mode": "exact_age",
        "basic.relationship_intent": spec["intent"],
        "basic.height_cm": 170,
        "location.country_code": "CN",
        "location.region_code": spec["region"],
        "location.city_code": spec["city"],
        "location.primary_language_codes": ["zh-CN"],
        "location.additional_language_codes": ["en"],
        "location.relocation_willingness": "same_country",
        "location.residence_status_code": "citizen",
        "location.citizenship_codes": ["CN"],
        "education_and_work.education_level_code": "bachelor",
        "education_and_work.occupation_category_code": "education",
        "faith.faith_status_code": spec["faith"],
        "faith.current_church_participation_code": "weekly",
        "faith.church_tradition_codes": [spec["tradition"]],
        "faith.marriage_faith_importance": int(spec["importance"]),
        "faith.devotional_life_code": "daily",
        "faith.faith_started_year": 2012,
        "faith.small_group_participation_code": "regular_member",
        "faith.ministry_participation_codes": ["teaching"],
        "faith.future_church_expectation_codes": ["worship_together"],
        "relationship_history.marital_status_code": "never_married",
        "relationship_history.has_children": False,
        "relationship_history.prior_marriage_count": 0,
        "relationship_history.children_living_arrangement_code": "no_children",
        "relationship_history.open_to_partner_with_children": "open_with_conversation",
        "relationship_history.relationship_history_disclosure_level": "after_mutual_match",
        "family.desire_children_code": "want_children",
        "family.family_closeness_code": "close",
        "family.current_living_arrangement_code": "living_alone",
        "family.family_culture_codes": ["christian_household"],
        "family.parental_care_expectation_codes": ["live_nearby"],
        "family.parenting_expectation_codes": ["faith_formation"],
        "family.preferred_future_household_codes": ["nuclear"],
        "lifestyle.daily_schedule_code": spec["schedule"],
        "lifestyle.smoking_status_code": "never",
        "lifestyle.alcohol_use_code": "never",
        "lifestyle.leisure_interest_codes": list(spec["interests"]),
        "lifestyle.communication_preference_codes": ["in_person", "video_call"],
        "lifestyle.diet_codes": ["no_restriction"],
        "lifestyle.exercise_frequency_code": "several_times_week",
        "lifestyle.social_style_codes": ["small_gatherings"],
        "lifestyle.pet_preference_codes": ["likes_pets"],
        "lifestyle.travel_frequency_code": "occasional",
        "lifestyle.financial_attitude_codes": ["saver"],
        "lifestyle.conflict_style_codes": ["talk_immediately"],
    }


async def seed_recommendation_fixtures() -> None:
    from vav.cli.seed_dating_taxonomies import seed_dating_taxonomies

    await seed_dating_taxonomies()

    async with session_factory() as session:
        reviewer = await _ensure_reviewer(session)

    created = 0
    for spec in COHORT:
        async with session_factory() as session:
            member = await _ensure_member(session, spec)
            existing = await profile_service.get_profile_row(session, member.id)
            if existing is not None and existing["status"] == "active":
                continue
            if existing is None:
                await profile_service.create_profile(session, member)
            await profile_service.update_fields(session, member, _fields(spec))
            await profile_service.update_narratives(
                session,
                member,
                "zh-CN",
                {
                    "self_introduction": SELF_INTRODUCTION,
                    "faith_journey": "一段用于测试的合成信仰旅程叙述。",
                    "relationship_values": "诚实、委身、彼此扶持。",
                    "marriage_vision": "希望共同建立以信仰为根基的家庭。",
                    "family_vision": "希望家庭成为彼此的避风港。",
                    "strengths_and_growth": "耐心是我的优势，表达情绪仍在学习。",
                    "interests_and_lifestyle": "喜欢阅读、音乐与户外活动。",
                    "hoped_for_relationship": "希望认识重视信仰与家庭的伴侣。",
                },
            )
            await profile_service.replace_preferences(
                session,
                member,
                [
                    {
                        "criterion_code": "age_range",
                        "operator": "range",
                        "desired_value": {"minimum": 25, "maximum": 45},
                        "importance": "required",
                        "hard_constraint": True,
                        "allow_unknown": False,
                    },
                    {
                        "criterion_code": "faith_status_code",
                        "operator": "in",
                        "desired_value": ["believer_baptized", "believer_not_baptized"],
                        "importance": "very_important",
                        "hard_constraint": False,
                    },
                    {
                        "criterion_code": "relationship_intent",
                        "operator": "in",
                        "desired_value": ["marriage_oriented", "serious_relationship"],
                        "importance": "important",
                        "hard_constraint": False,
                    },
                    {
                        "criterion_code": "leisure_interest_codes",
                        "operator": "contains_any",
                        "desired_value": [
                            "reading",
                            "music",
                            "outdoors",
                            "arts",
                            "travel",
                            "volunteering",
                            "study",
                            "sports",
                        ],
                        "importance": "nice_to_have",
                        "hard_constraint": False,
                    },
                ],
                allow_relaxation=False,
            )
            await _attach_photo(session, member)
            profile = await profile_service.require_profile(session, member.id)
            await profile_service.refresh_completeness(session, profile["id"])
            await session.commit()

            await profile_service.submit_profile(session, member, "Recommendation fixture seed")
            case_id = await session.scalar(
                text(
                    "SELECT id FROM dating_profile_review_cases WHERE dating_profile_id=:id "
                    "ORDER BY submitted_at DESC LIMIT 1"
                ),
                {"id": profile["id"]},
            )
            await profile_review.start_case(session, reviewer, UUID(str(case_id)), None)
            await profile_review.approve_case(
                session,
                reviewer,
                UUID(str(case_id)),
                user_message="Fixture profile approved.",
                internal_summary=None,
                expected_version=None,
            )
            await profile_service.rebuild_projection(session, profile["id"])
            created += 1

    print(
        f"Recommendation fixture cohort ready: {len(COHORT)} synthetic members "
        f"({created} newly approved) at {datetime.now(UTC).isoformat(timespec='seconds')}"
    )


async def _attach_photo(session: AsyncSession, member: User) -> None:
    """Attach a synthetic, already-approved primary photo."""
    from vav.modules.matchmaking_profiles import photos as photo_processing

    profile = await profile_service.require_profile(session, member.id)
    existing = await session.scalar(
        text(
            "SELECT count(*) FROM dating_profile_photos WHERE dating_profile_id=:id AND deleted_at IS NULL"
        ),
        {"id": profile["id"]},
    )
    if int(existing or 0):
        return

    import io

    from PIL import Image

    seed = abs(hash(str(member.id))) % 97 + 1
    image = Image.new("RGB", (900, 900))
    image.putdata(
        [
            (
                (x * 7 + y * 3 + seed) % 200 + 30,
                (x * 3 + y * 11 + seed) % 200 + 30,
                (x * 13 + y * 5 + seed) % 200 + 30,
            )
            for y in range(900)
            for x in range(900)
        ]
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    processed = photo_processing.process_image(buffer.getvalue(), "image/jpeg")

    media_id = await session.scalar(
        text(
            "INSERT INTO media_assets (storage_provider,bucket_name,object_key,original_filename,media_type,"
            "mime_type,byte_size,width,height,checksum_sha256,visibility,processing_status,uploaded_by) "
            "VALUES ('s3','vav-private',:key,'fixture.jpg','image','image/jpeg',:size,900,900,:checksum,"
            "'private','processed',:user_id) RETURNING id"
        ),
        {
            "key": f"private/dating-photos/{profile['id']}/{processed['checksum_sha256']}.jpg",
            "size": processed["byte_size"],
            "checksum": processed["checksum_sha256"],
            "user_id": member.id,
        },
    )
    await session.commit()
    result = await profile_service.register_photo(
        session,
        member,
        media_asset_id=UUID(str(media_id)),
        role="primary",
        checksum=processed["checksum_sha256"],
        report=processed["report"],
    )
    await session.execute(
        text("UPDATE dating_profile_photos SET status='approved',reviewed_at=now() WHERE id=:id"),
        {"id": UUID(result["photo_id"])},
    )
    await session.commit()
    _ = json_value


if __name__ == "__main__":
    asyncio.run(seed_recommendation_fixtures())
