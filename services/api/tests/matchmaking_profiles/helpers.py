"""Shared fixtures for dating-profile tests."""

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
from vav.modules.matchmaking_profiles import service
from vav.modules.privacy.crypto import encrypt_private

TEST_PASSWORD = "VavDating!2026_Secure#"

#: Every required-for-submission field, so a test can reach a submittable profile.
COMPLETE_FIELDS: dict[str, Any] = {
    "basic.gender_code": "female",
    "basic.eligible_partner_gender_codes": ["male"],
    "basic.age_display_mode": "exact_age",
    "basic.relationship_intent": "marriage_oriented",
    "location.country_code": "CN",
    "location.region_code": "east",
    "location.city_code": "shanghai",
    "location.primary_language_codes": ["zh-CN"],
    "location.relocation_willingness": "same_country",
    "education_and_work.education_level_code": "bachelor",
    "education_and_work.occupation_category_code": "education",
    "faith.faith_status_code": "believer_baptized",
    "faith.current_church_participation_code": "weekly",
    "faith.church_tradition_codes": ["reformed"],
    "faith.marriage_faith_importance": 5,
    "faith.devotional_life_code": "daily",
    "relationship_history.marital_status_code": "never_married",
    "relationship_history.has_children": False,
    "family.desire_children_code": "want_children",
    "family.family_closeness_code": "close",
    "lifestyle.daily_schedule_code": "standard",
    "lifestyle.smoking_status_code": "never",
    "lifestyle.alcohol_use_code": "never",
    "lifestyle.leisure_interest_codes": ["reading", "music"],
    "lifestyle.communication_preference_codes": ["in_person"],
}

#: Optional detail that lifts a profile past the recommendation threshold.
OPTIONAL_FIELDS: dict[str, Any] = {
    "basic.height_cm": 168,
    "location.residence_status_code": "citizen",
    "location.citizenship_codes": ["CN"],
    "location.additional_language_codes": ["en"],
    "faith.faith_started_year": 2010,
    "faith.small_group_participation_code": "regular_member",
    "faith.ministry_participation_codes": ["teaching"],
    "faith.future_church_expectation_codes": ["worship_together"],
    "faith.faith_journey_summary": "一段用于测试的信仰经历摘要。",
    "relationship_history.prior_marriage_count": 0,
    "relationship_history.relationship_history_disclosure_level": "after_mutual_match",
    "relationship_history.children_count_range": "prefer_not_to_say",
    "relationship_history.children_living_arrangement_code": "no_children",
    "relationship_history.open_to_partner_with_children": "open_with_conversation",
    "relationship_history.history_summary": "一段用于测试的关系历史摘要。",
    "family.current_living_arrangement_code": "living_alone",
    "family.family_culture_codes": ["christian_household"],
    "family.parental_care_expectation_codes": ["live_nearby"],
    "family.parenting_expectation_codes": ["faith_formation"],
    "family.preferred_future_household_codes": ["nuclear"],
    "family.family_summary": "一段用于测试的家庭描述摘要。",
    "lifestyle.diet_codes": ["no_restriction"],
    "lifestyle.exercise_frequency_code": "several_times_week",
    "lifestyle.social_style_codes": ["small_gatherings"],
    "lifestyle.pet_preference_codes": ["likes_pets"],
    "lifestyle.travel_frequency_code": "occasional",
    "lifestyle.financial_attitude_codes": ["saver"],
    "lifestyle.conflict_style_codes": ["talk_immediately"],
}

SELF_INTRODUCTION = (
    "我是一名教育工作者，喜欢阅读和音乐，也重视在信仰中的成长与委身。"
    "希望认识一位同样看重家庭与信仰的伴侣，一起在生活里彼此扶持、共同成长。"
    "这段文字仅用于自动化测试，不代表任何真实用户的陈述内容。"
)


async def create_member(
    session: AsyncSession,
    *,
    birth_year: int = 1993,
    display_name: str = "Test Member",
    visible_in_matchmaking: bool = True,
) -> User:
    """Create an active member with a protected date of birth."""
    email = f"dating-{uuid4()}@example.com"
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
            "VALUES (:user_id,:name,:dob,'zh-CN','Asia/Shanghai','complete')"
        ),
        {
            "user_id": user.id,
            "name": display_name,
            "dob": encrypt_private(date(birth_year, 6, 15).isoformat()),
        },
    )
    await session.execute(
        text(
            "INSERT INTO user_privacy_settings (user_id,visible_in_matchmaking,privacy_mode) "
            "VALUES (:user_id,:visible,'strict')"
        ),
        {"user_id": user.id, "visible": visible_in_matchmaking},
    )
    await session.commit()
    return user


async def ensure_schema_release(session: AsyncSession) -> None:
    """Make sure the active schema release and taxonomies exist."""
    existing = await session.scalar(
        text(
            "SELECT count(*) FROM dating_profile_schema_releases WHERE schema_code='vav-dating-profile' AND status='active'"
        )
    )
    if not existing:
        from vav.cli.seed_dating_taxonomies import seed_dating_taxonomies

        await seed_dating_taxonomies()


async def create_complete_profile(
    session: AsyncSession, user: User, *, with_photo: bool = True
) -> dict[str, Any]:
    """Create a profile filled in far enough to be submittable."""
    await ensure_schema_release(session)
    profile = await service.create_profile(session, user)
    await service.update_fields(session, user, dict(COMPLETE_FIELDS) | dict(OPTIONAL_FIELDS))
    await service.update_narratives(
        session,
        user,
        "zh-CN",
        {
            "self_introduction": SELF_INTRODUCTION,
            "faith_journey": "一段用于测试的信仰旅程叙述。",
            "relationship_values": "诚实、委身、彼此扶持。",
            "marriage_vision": "希望共同建立以信仰为根基的家庭。",
            "family_vision": "希望家庭成为彼此的避风港。",
            "strengths_and_growth": "耐心是我的优势，表达情绪仍在学习。",
            "interests_and_lifestyle": "喜欢阅读、音乐与户外活动。",
            "hoped_for_relationship": "希望认识重视信仰与家庭的伴侣。",
        },
    )
    await service.replace_preferences(
        session,
        user,
        [
            {
                "criterion_code": "age_range",
                "operator": "range",
                "desired_value": {"minimum": 28, "maximum": 45},
                "importance": "required",
                "hard_constraint": True,
            }
        ],
        allow_relaxation=False,
    )
    if with_photo:
        await attach_photo(session, user, role="primary")
    await service.refresh_completeness(session, profile["id"])
    await session.commit()
    return await service.require_profile(session, user.id)


def sample_image_bytes(
    *,
    size: tuple[int, int] = (900, 900),
    fmt: str = "JPEG",
    with_exif: bool = False,
    seed: int = 0,
) -> bytes:
    """Build a deterministic non-uniform test image; ``seed`` varies the checksum."""
    image = Image.new("RGB", size)
    pixels = [
        (
            (x * 7 + y * 3 + seed) % 200 + 30,
            (x * 3 + y * 11 + seed * 3) % 200 + 30,
            (x * 13 + y * 5 + seed * 7) % 200 + 30,
        )
        for y in range(size[1])
        for x in range(size[0])
    ]
    image.putdata(pixels)
    buffer = io.BytesIO()
    if with_exif and fmt == "JPEG":
        exif = image.getexif()
        exif[271] = "TestCamera"
        exif[272] = "TestModel"
        exif[305] = "TestSoftware"
        exif[306] = "2026:01:01 12:00:00"
        image.save(buffer, format=fmt, exif=exif.tobytes())
    else:
        image.save(buffer, format=fmt)
    return buffer.getvalue()


_photo_seed = itertools.count(1)


async def attach_photo(
    session: AsyncSession, user: User, *, role: str = "gallery", approve: bool = True
) -> UUID:
    """Process and register a photo, optionally approving it directly."""
    from vav.modules.matchmaking_profiles import photos as photo_processing

    processed = photo_processing.process_image(
        sample_image_bytes(seed=next(_photo_seed)), "image/jpeg"
    )
    profile = await service.require_profile(session, user.id)
    media_id = await session.scalar(
        text(
            "INSERT INTO media_assets (storage_provider,bucket_name,object_key,original_filename,media_type,"
            "mime_type,byte_size,width,height,checksum_sha256,visibility,processing_status,uploaded_by) "
            "VALUES ('s3','vav-private',:key,'test.jpg','image','image/jpeg',:size,:w,:h,:checksum,'private','processed',:user_id) "
            "RETURNING id"
        ),
        {
            "key": f"private/dating-photos/{profile['id']}/{uuid4()}.jpg",
            "size": processed["byte_size"],
            "w": processed["width"],
            "h": processed["height"],
            "checksum": processed["checksum_sha256"],
            "user_id": user.id,
        },
    )
    await session.commit()
    result = await service.register_photo(
        session,
        user,
        media_asset_id=UUID(str(media_id)),
        role=role,
        checksum=processed["checksum_sha256"],
        report=processed["report"],
    )
    photo_id = UUID(result["photo_id"])
    if approve:
        await session.execute(
            text(
                "UPDATE dating_profile_photos SET status='approved',reviewed_at=now() WHERE id=:id"
            ),
            {"id": photo_id},
        )
        await session.commit()
    return photo_id


async def create_reviewer(session: AsyncSession, role_code: str = "profile_reviewer") -> User:
    """Create an admin user holding a matchmaking review role."""
    email = f"reviewer-{uuid4()}@example.com"
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
    role_id = await session.scalar(
        text("SELECT id FROM roles WHERE code=:code"), {"code": role_code}
    )
    if role_id is not None:
        await session.execute(
            text(
                "INSERT INTO user_roles (user_id,role_id,granted_by,grant_reason) "
                "VALUES (:user_id,:role_id,:user_id,'automated test fixture') ON CONFLICT DO NOTHING"
            ),
            {"user_id": user.id, "role_id": role_id},
        )
        await session.commit()
    return user


async def submit_and_approve(session: AsyncSession, user: User, reviewer: User) -> dict[str, Any]:
    """Run a profile through submission, review start and approval."""
    from vav.modules.matchmaking_profiles import review as review_service

    await service.submit_profile(session, user, "Initial submission")
    profile = await service.require_profile(session, user.id)
    case_id = await session.scalar(
        text(
            "SELECT id FROM dating_profile_review_cases WHERE dating_profile_id=:id "
            "ORDER BY submitted_at DESC LIMIT 1"
        ),
        {"id": profile["id"]},
    )
    await review_service.start_case(session, reviewer, UUID(str(case_id)), None)
    await review_service.approve_case(
        session,
        reviewer,
        UUID(str(case_id)),
        user_message="Welcome to VAV.",
        internal_summary="Baseline check passed.",
        expected_version=None,
    )
    return await service.require_profile(session, user.id)
