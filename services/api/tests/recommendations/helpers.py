"""Shared fixtures for recommendation tests."""

# ruff: noqa: E501
from __future__ import annotations

import io
import itertools
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.models.identity import User
from vav.modules.identity.security import PasswordHasher
from vav.modules.matchmaking_profiles import photos as photo_processing
from vav.modules.matchmaking_profiles import review as profile_review
from vav.modules.matchmaking_profiles import service as profile_service
from vav.modules.privacy.crypto import encrypt_private
from vav.modules.recommendations import service

TEST_PASSWORD = "VavRecommendation!2026_Secure#"

SELF_INTRODUCTION = (
    "这是一段用于推荐系统自动化测试的合成自我介绍文本，用来验证候选生成、硬条件过滤、双向评分、"
    "排序多样化以及解释输出是否按预期工作。文本长度刻意超过平台设置的自我介绍最小字数要求，"
    "以便完整走通提交与审核流程。它不包含任何真实个人信息，也不代表任何真实用户的陈述内容。"
)

_photo_seed = itertools.count(1)

#: A minimal projection shaped exactly like the Batch 13 output.
BASE_PROJECTION: dict[str, Any] = {
    "age_bucket": "30_34",
    "age_years": 32,
    "country_code": "CN",
    "region_code": "east",
    "city_code": "shanghai",
    "gender_code": "female",
    "eligible_partner_gender_codes": ["male"],
    "faith_codes": ["believer_baptized", "weekly", "reformed", "marriage_faith_importance:5"],
    "relationship_intent": "marriage_oriented",
    "marital_status_code": "never_married",
    "children_status_code": "no_children",
    "relocation_willingness": "same_country",
    "language_codes": ["zh-CN"],
    "lifestyle_codes": [
        "daily_schedule_code:standard",
        "smoking_status_code:never",
        "alcohol_use_code:never",
        "leisure_interest_codes:reading",
        "leisure_interest_codes:music",
        "communication_preference_codes:in_person",
        "education_level_code:bachelor",
        "desire_children_code:want_children",
    ],
    "indexed_preference_criteria": [],
    "approved_profile_version": 1,
    "preference_version": 1,
    "privacy_settings_version": 1,
    "projection_version": 1,
    "projection_checksum": "0" * 64,
}


def projection(**overrides: Any) -> dict[str, Any]:
    """Build a projection dict for pure-function tests."""
    return {**BASE_PROJECTION, **overrides}


def criterion(
    code: str,
    operator: str,
    value: Any,
    *,
    importance: str = "very_important",
    hard: bool = False,
    allow_unknown: bool = True,
    allow_relaxation: bool = False,
) -> dict[str, Any]:
    return {
        "criterion_code": code,
        "operator": operator,
        "desired_value": value,
        "importance": importance,
        "hard_constraint": hard,
        "allow_unknown": allow_unknown,
        "allow_system_relaxation": allow_relaxation,
    }


async def ensure_strategy(session: AsyncSession) -> None:
    existing = await session.scalar(
        text("SELECT count(*) FROM recommendation_strategies WHERE status='active'")
    )
    if not existing:
        from vav.cli.seed_recommendations import seed_recommendations

        await seed_recommendations()


async def create_member(
    session: AsyncSession,
    *,
    gender: str = "female",
    wants: list[str] | None = None,
    city: str = "shanghai",
    region: str = "east",
    birth_year: int = 1993,
    faith: str = "believer_baptized",
    tradition: str = "reformed",
    importance: int = 5,
    intent: str = "marriage_oriented",
    schedule: str = "standard",
    interests: list[str] | None = None,
    visible_in_matchmaking: bool = True,
) -> User:
    """Create an active member with a protected date of birth."""
    email = f"rec-{uuid4()}@example.com"
    user = User(
        email=email,
        display_email=email,
        password_hash=PasswordHasher().hash(TEST_PASSWORD),
        status="active",
        email_verified_at=datetime.now(UTC),
        preferred_locale="zh-CN",
        timezone="Asia/Shanghai",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await session.execute(
        text(
            "INSERT INTO user_profiles (user_id,display_name,date_of_birth_encrypted,preferred_locale,timezone,profile_status) "
            "VALUES (:id,:name,:dob,'zh-CN','Asia/Shanghai','complete')"
        ),
        {
            "id": user.id,
            "name": f"Rec {gender.title()}",
            "dob": encrypt_private(date(birth_year, 5, 20).isoformat()),
        },
    )
    await session.execute(
        text(
            "INSERT INTO user_privacy_settings (user_id,visible_in_matchmaking,privacy_mode) "
            "VALUES (:id,:visible,'strict')"
        ),
        {"id": user.id, "visible": visible_in_matchmaking},
    )
    await session.commit()
    user.__dict__["_spec"] = {
        "gender": gender,
        "wants": wants or (["male"] if gender == "female" else ["female"]),
        "city": city,
        "region": region,
        "faith": faith,
        "tradition": tradition,
        "importance": importance,
        "intent": intent,
        "schedule": schedule,
        "interests": interests or ["reading", "music"],
    }
    return user


def _fields(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "basic.gender_code": spec["gender"],
        "basic.eligible_partner_gender_codes": list(spec["wants"]),
        "basic.age_display_mode": "exact_age",
        "basic.relationship_intent": spec["intent"],
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


DEFAULT_CRITERIA: list[dict[str, Any]] = [
    criterion(
        "age_range",
        "range",
        {"minimum": 25, "maximum": 45},
        importance="required",
        hard=True,
        allow_unknown=False,
    ),
    criterion(
        "faith_status_code",
        "in",
        ["believer_baptized", "believer_not_baptized"],
        importance="very_important",
    ),
    criterion(
        "relationship_intent",
        "in",
        ["marriage_oriented", "serious_relationship"],
        importance="important",
    ),
]


async def create_reviewer(session: AsyncSession) -> User:
    email = f"rec-reviewer-{uuid4()}@example.com"
    user = User(
        email=email,
        display_email=email,
        password_hash=PasswordHasher().hash(TEST_PASSWORD),
        status="active",
        email_verified_at=datetime.now(UTC),
        preferred_locale="zh-CN",
        timezone="UTC",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    for role_code in ("profile_reviewer", "profile_review_lead"):
        role_id = await session.scalar(
            text("SELECT id FROM roles WHERE code=:code"), {"code": role_code}
        )
        if role_id is not None:
            await session.execute(
                text(
                    "INSERT INTO user_roles (user_id,role_id,granted_by,grant_reason) "
                    "VALUES (:user_id,:role_id,:user_id,'recommendation test fixture') ON CONFLICT DO NOTHING"
                ),
                {"user_id": user.id, "role_id": role_id},
            )
    await session.commit()
    return user


async def _attach_photo(session: AsyncSession, member: User) -> None:
    seed = next(_photo_seed)
    image = Image.new("RGB", (900, 900))
    image.putdata(
        [
            (
                (x * 7 + y * 3 + seed) % 200 + 30,
                (x * 3 + y * 11 + seed * 3) % 200 + 30,
                (x * 13 + y * 5 + seed * 7) % 200 + 30,
            )
            for y in range(900)
            for x in range(900)
        ]
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    processed = photo_processing.process_image(buffer.getvalue(), "image/jpeg")
    profile = await profile_service.require_profile(session, member.id)
    media_id = await session.scalar(
        text(
            "INSERT INTO media_assets (storage_provider,bucket_name,object_key,original_filename,media_type,"
            "mime_type,byte_size,width,height,checksum_sha256,visibility,processing_status,uploaded_by) "
            "VALUES ('s3','vav-private',:key,'t.jpg','image','image/jpeg',:size,900,900,:checksum,'private','processed',:user_id) RETURNING id"
        ),
        {
            "key": f"private/dating-photos/{profile['id']}/{uuid4()}.jpg",
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


async def make_recommendable(
    session: AsyncSession,
    member: User,
    reviewer: User,
    *,
    criteria: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Drive a member all the way to an ACTIVE profile with a projection."""
    spec = member.__dict__["_spec"]
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
        [dict(item) for item in (criteria if criteria is not None else DEFAULT_CRITERIA)],
        allow_relaxation=False,
    )
    await _attach_photo(session, member)
    profile = await profile_service.require_profile(session, member.id)
    await profile_service.refresh_completeness(session, profile["id"])
    await session.commit()

    await profile_service.submit_profile(session, member, "Recommendation test fixture")
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
        user_message="Approved for tests.",
        internal_summary=None,
        expected_version=None,
    )
    await profile_service.rebuild_projection(session, profile["id"])
    await service.sync_pool_entry(session, member.id)
    await session.commit()
    return await profile_service.require_profile(session, member.id)


async def make_pair(
    session: AsyncSession,
    *,
    female_overrides: dict[str, Any] | None = None,
    male_overrides: dict[str, Any] | None = None,
    female_criteria: list[dict[str, Any]] | None = None,
    male_criteria: list[dict[str, Any]] | None = None,
) -> tuple[User, User]:
    """Create one recommendable female / male pair."""
    await ensure_strategy(session)
    reviewer = await create_reviewer(session)
    female = await create_member(session, gender="female", **(female_overrides or {}))
    male = await create_member(session, gender="male", **(male_overrides or {}))
    await make_recommendable(session, female, reviewer, criteria=female_criteria)
    await make_recommendable(session, male, reviewer, criteria=male_criteria)
    return female, male
