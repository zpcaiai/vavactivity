"""Populate the intentionally insecure test account with synthetic showcase data.

The seed is repeatable and owns identifiers in the ``test-showcase`` namespace. It may
also fill the untouched draft page slots created by ``seed_cms``. It is allowed in
development, test and staging, and always refuses production/DR.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.cli.seed_activities import seed_activities
from vav.cli.seed_ai_assistant import seed_ai_assistant
from vav.cli.seed_catalog import seed_catalog
from vav.cli.seed_cms import SYSTEM_USER_ID, seed_cms
from vav.cli.seed_counseling import seed_counseling
from vav.cli.seed_courses import seed_courses
from vav.cli.seed_dating_profiles import seed_dating_profiles
from vav.cli.seed_experience import seed_experience
from vav.cli.seed_memberships import seed_memberships
from vav.cli.seed_notification_templates import seed_notification_templates
from vav.cli.seed_notifications import seed_notifications
from vav.cli.seed_permissions import seed_permissions
from vav.cli.seed_privacy import seed_privacy
from vav.cli.seed_recommendation_fixtures import (
    _approve_version,
    _ensure_photo,
    seed_fixtures,
)
from vav.cli.seed_recommendations import main as seed_recommendations
from vav.cli.seed_relationships import seed_relationships
from vav.cli.seed_test_user import TEST_USER_EMAIL, seed_test_user
from vav.cli.seed_trust_safety import seed_trust_safety
from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.modules.ai_assistant.crypto import content_hash, encrypt_ai_data
from vav.modules.courses.crypto import encrypt_sensitive as encrypt_service
from vav.modules.matchmaking_profiles.service import rebuild_projection
from vav.modules.memberships import projection as membership_projection
from vav.modules.privacy.crypto import encrypt_private, searchable_hmac
from vav.modules.recommendations import batches as recommendation_batches
from vav.modules.recommendations import service as recommendation_service
from vav.modules.trust_safety.crypto import encrypt_sensitive as encrypt_safety

PROTECTED_ENVIRONMENTS = frozenset({"production", "dr"})
SHOWCASE_PREFIX = "test-showcase"


def _id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"vav:{SHOWCASE_PREFIX}:{key}")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


async def _test_user_id(session: AsyncSession) -> UUID:
    user_id = await session.scalar(
        text("SELECT id FROM users WHERE email=:email"), {"email": TEST_USER_EMAIL}
    )
    if user_id is None:
        raise RuntimeError("The test account is missing; run seed_test_user first.")
    return cast(UUID, user_id)


async def _seed_public_content(session: AsyncSession) -> None:
    page_specs = (
        ("home", "欢迎来到 VAV", "从真实内容开始探索活动、课程与关系成长服务。"),
        ("about", "关于 VAV", "以安全、尊重和真实连接为核心的成长平台。"),
        ("services", "服务总览", "浏览活动、课程、咨询与会员支持。"),
        ("contact", "联系与合作", "欢迎提交合作、支持或一般咨询。"),
        ("privacy", "隐私中心", "了解数据使用、选择、导出与删除权利。"),
        ("terms", "服务条款", "使用测试站点前请阅读适用规则。"),
        ("refund-policy", "退款政策", "不同服务的取消与退款条件可能不同。"),
        ("ai-disclaimer", "AI 助手说明", "AI 内容用于辅助思考，不能替代专业判断。"),
    )
    for slug, title, excerpt in page_specs:
        blocks = [
            {
                "id": f"{SHOWCASE_PREFIX}-{slug}-hero",
                "type": "hero",
                "version": 1,
                "data": {"heading": title, "subheading": excerpt},
            },
            {
                "id": f"{SHOWCASE_PREFIX}-{slug}-body",
                "type": "rich_text",
                "version": 1,
                "data": {
                    "document": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": excerpt}],
                            }
                        ],
                    }
                },
            },
            {
                "id": f"{SHOWCASE_PREFIX}-{slug}-cta",
                "type": "call_to_action",
                "version": 1,
                "data": {
                    "title": "继续探索",
                    "description": "这些内容为 staging/test 展示数据。",
                    "button": {"label": "查看全部服务", "href": "/zh-CN/services"},
                },
            },
        ]
        entry_id = await session.scalar(
            text(
                "INSERT INTO content_entries "
                "(id,entry_type,internal_name,canonical_slug,status,default_locale,visibility,author_id,published_by,published_at,published_revision_number) "
                "VALUES (:id,'page',:name,:slug,'published','zh-CN','public',:actor,:actor,now(),1) "
                "ON CONFLICT (entry_type,canonical_slug) DO UPDATE SET status='published',visibility='public',"
                "published_revision_number=COALESCE(content_entries.published_revision_number,GREATEST(content_entries.current_version,1)),"
                "published_by=EXCLUDED.published_by,published_at=COALESCE(content_entries.published_at,now()),updated_at=now() "
                "WHERE content_entries.internal_name LIKE 'System page:%' "
                "OR content_entries.internal_name LIKE 'Test showcase page:%' "
                "RETURNING id"
            ),
            {
                "id": _id(f"content-page:{slug}"),
                "name": f"Test showcase page: {slug}",
                "slug": slug,
                "actor": SYSTEM_USER_ID,
            },
        )
        if entry_id is None:
            continue
        await session.execute(
            text(
                "INSERT INTO content_localizations "
                "(id,entry_id,locale,localized_slug,title,excerpt,content_blocks,plain_text,translation_status) "
                "VALUES (:id,:entry,'zh-CN',:slug,:title,:excerpt,CAST(:blocks AS jsonb),:excerpt,'ready') "
                "ON CONFLICT (entry_id,locale) DO UPDATE SET localized_slug=EXCLUDED.localized_slug,title=EXCLUDED.title,"
                "excerpt=EXCLUDED.excerpt,content_blocks=EXCLUDED.content_blocks,plain_text=EXCLUDED.plain_text,"
                "translation_status='ready',updated_at=now()"
            ),
            {
                "id": _id(f"content-page-localization:{slug}"),
                "entry": entry_id,
                "slug": slug,
                "title": title,
                "excerpt": excerpt,
                "blocks": _json(blocks),
            },
        )

    article_specs = (
        (
            "learn-to-listen",
            "练习倾听：从三分钟开始",
            "沟通练习",
            "先复述对方的重点，再表达自己的理解。",
        ),
        (
            "healthy-boundaries",
            "健康边界不是疏远",
            "关系成长",
            "清晰边界让双方更安心，也让承诺更可靠。",
        ),
        (
            "weekly-reflection",
            "十分钟的每周关系复盘",
            "实践工具",
            "固定时间回顾感谢、困难与下一步行动。",
        ),
    )
    for index, (slug, title, category, excerpt) in enumerate(article_specs, start=1):
        entry_id = await session.scalar(
            text(
                "INSERT INTO content_entries "
                "(id,entry_type,internal_name,canonical_slug,status,default_locale,visibility,author_id,published_by,published_at,published_revision_number) "
                "VALUES (:id,'article',:title,:slug,'published','zh-CN','public',:actor,:actor,now(),1) "
                "ON CONFLICT (entry_type,canonical_slug) DO UPDATE SET status='published',visibility='public',"
                "published_revision_number=COALESCE(content_entries.published_revision_number,GREATEST(content_entries.current_version,1)),"
                "published_by=EXCLUDED.published_by,published_at=COALESCE(content_entries.published_at,now()),updated_at=now() "
                "RETURNING id"
            ),
            {
                "id": _id(f"content-article:{index}"),
                "title": title,
                "slug": f"test-showcase-{slug}",
                "actor": SYSTEM_USER_ID,
            },
        )
        blocks = [
            {
                "id": f"{SHOWCASE_PREFIX}-article-{index}-body",
                "type": "rich_text",
                "version": 1,
                "data": {
                    "document": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": excerpt}],
                            }
                        ],
                    }
                },
            },
            {
                "id": f"{SHOWCASE_PREFIX}-article-{index}-quote",
                "type": "quote",
                "version": 1,
                "data": {
                    "quote": "关系成长来自持续、具体、可选择的行动。",
                    "attribution": "VAV 展示内容",
                },
            },
        ]
        await session.execute(
            text(
                "INSERT INTO content_localizations "
                "(id,entry_id,locale,localized_slug,title,excerpt,content_blocks,plain_text,translation_status) "
                "VALUES (:id,:entry,'zh-CN',:slug,:title,:excerpt,CAST(:blocks AS jsonb),:excerpt,'ready') "
                "ON CONFLICT (entry_id,locale) DO UPDATE SET title=EXCLUDED.title,excerpt=EXCLUDED.excerpt,"
                "content_blocks=EXCLUDED.content_blocks,plain_text=EXCLUDED.plain_text,translation_status='ready',updated_at=now()"
            ),
            {
                "id": _id(f"content-article-localization:{index}"),
                "entry": entry_id,
                "slug": f"test-showcase-{slug}",
                "title": title,
                "excerpt": excerpt,
                "blocks": _json(blocks),
            },
        )
        await session.execute(
            text(
                "INSERT INTO article_metadata (entry_id,category,author_display_name,reading_time_minutes,featured) "
                "VALUES (:entry,:category,'VAV 内容团队',:minutes,:featured) ON CONFLICT (entry_id) DO UPDATE SET "
                "category=EXCLUDED.category,reading_time_minutes=EXCLUDED.reading_time_minutes,featured=EXCLUDED.featured"
            ),
            {
                "entry": entry_id,
                "category": category,
                "minutes": index + 2,
                "featured": index == 1,
            },
        )

    story_specs = (
        ("steady-conversation", "从不敢表达，到能稳定沟通", "建立连接"),
        ("first-group-event", "第一次参加小组活动之后", "相互了解"),
        ("shared-weekly-plan", "一起完成每周成长计划", "关系成长"),
    )
    for index, (slug, title, stage) in enumerate(story_specs, start=1):
        excerpt = "这是匿名合成案例，仅用于展示页面结构，不代表真实用户经历。"
        entry_id = await session.scalar(
            text(
                "INSERT INTO content_entries "
                "(id,entry_type,internal_name,canonical_slug,status,default_locale,visibility,author_id,published_by,published_at,published_revision_number) "
                "VALUES (:id,'testimonial',:title,:slug,'published','zh-CN','public',:actor,:actor,now(),1) "
                "ON CONFLICT (entry_type,canonical_slug) DO UPDATE SET status='published',visibility='public',"
                "published_revision_number=COALESCE(content_entries.published_revision_number,GREATEST(content_entries.current_version,1)),"
                "published_by=EXCLUDED.published_by,published_at=COALESCE(content_entries.published_at,now()),updated_at=now() "
                "RETURNING id"
            ),
            {
                "id": _id(f"content-story:{index}"),
                "title": title,
                "slug": f"test-showcase-{slug}",
                "actor": SYSTEM_USER_ID,
            },
        )
        blocks = [
            {
                "id": f"{SHOWCASE_PREFIX}-story-{index}-quote",
                "type": "quote",
                "version": 1,
                "data": {"quote": excerpt, "attribution": "匿名合成案例"},
            },
            {
                "id": f"{SHOWCASE_PREFIX}-story-{index}-cta",
                "type": "call_to_action",
                "version": 1,
                "data": {
                    "title": "开始自己的成长练习",
                    "button": {"label": "浏览服务", "href": "/zh-CN/services"},
                },
            },
        ]
        await session.execute(
            text(
                "INSERT INTO content_localizations "
                "(id,entry_id,locale,localized_slug,title,excerpt,content_blocks,plain_text,translation_status) "
                "VALUES (:id,:entry,'zh-CN',:slug,:title,:excerpt,CAST(:blocks AS jsonb),:excerpt,'ready') "
                "ON CONFLICT (entry_id,locale) DO UPDATE SET title=EXCLUDED.title,excerpt=EXCLUDED.excerpt,"
                "content_blocks=EXCLUDED.content_blocks,plain_text=EXCLUDED.plain_text,translation_status='ready',updated_at=now()"
            ),
            {
                "id": _id(f"content-story-localization:{index}"),
                "entry": entry_id,
                "slug": f"test-showcase-{slug}",
                "title": title,
                "excerpt": excerpt,
                "blocks": _json(blocks),
            },
        )
        await session.execute(
            text(
                "INSERT INTO testimonial_metadata "
                "(entry_id,subject_display_name,relationship_stage,consent_status,consent_record_id,anonymity_level,featured) "
                "VALUES (:entry,'匿名合成用户',:stage,'approved',:consent,'fully_anonymous',:featured) "
                "ON CONFLICT (entry_id) DO UPDATE SET consent_status='approved',consent_record_id=EXCLUDED.consent_record_id,"
                "relationship_stage=EXCLUDED.relationship_stage,featured=EXCLUDED.featured"
            ),
            {
                "entry": entry_id,
                "stage": stage,
                "consent": _id(f"content-story-consent:{index}"),
                "featured": index == 1,
            },
        )


async def _seed_profile_and_privacy(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO user_profiles "
            "(user_id,display_name,date_of_birth_encrypted,gender_code,country_code,region,city,"
            "preferred_locale,timezone,public_bio,profile_status,completeness_basis_points) "
            "VALUES (:user,'Test 用户',:dob,'female','CN','上海','上海','zh-CN','Asia/Shanghai',"
            ":bio,'complete',9200) ON CONFLICT (user_id) DO UPDATE SET "
            "display_name=EXCLUDED.display_name,date_of_birth_encrypted=COALESCE(user_profiles.date_of_birth_encrypted,EXCLUDED.date_of_birth_encrypted),"
            "gender_code=COALESCE(user_profiles.gender_code,EXCLUDED.gender_code),country_code=COALESCE(user_profiles.country_code,EXCLUDED.country_code),"
            "region=COALESCE(user_profiles.region,EXCLUDED.region),city=COALESCE(user_profiles.city,EXCLUDED.city),"
            "public_bio=COALESCE(user_profiles.public_bio,EXCLUDED.public_bio),profile_status='complete',"
            "completeness_basis_points=GREATEST(user_profiles.completeness_basis_points,9200),updated_at=now()"
        ),
        {
            "user": user_id,
            "dob": encrypt_private("1993-05-18"),
            "bio": "喜欢阅读、散步和有深度的交流，正在练习更清晰地表达与倾听。",
        },
    )
    await session.execute(
        text(
            "INSERT INTO user_privacy_settings "
            "(user_id,searchable_by_platform_users,visible_in_activity_directory,visible_in_matchmaking,"
            "allow_contact_exchange_after_mutual_confirmation,allow_profile_use_by_ai,"
            "allow_service_history_use_by_ai,privacy_mode) "
            "VALUES (:user,true,true,true,true,true,true,'balanced') ON CONFLICT (user_id) DO UPDATE SET "
            "searchable_by_platform_users=true,visible_in_activity_directory=true,visible_in_matchmaking=true,"
            "allow_contact_exchange_after_mutual_confirmation=true,allow_profile_use_by_ai=true,"
            "allow_service_history_use_by_ai=true,privacy_mode='balanced',settings_version=user_privacy_settings.settings_version+1,updated_at=now()"
        ),
        {"user": user_id},
    )
    contacts = (
        ("email", TEST_USER_EMAIL, True, "private"),
        ("phone", "+86 138 0000 2026", True, "mutual_matches"),
        ("wechat", "vav_test_showcase", False, "mutual_matches"),
    )
    for contact_type, value, verified, visibility in contacts:
        await session.execute(
            text(
                "INSERT INTO user_contact_points "
                "(id,user_id,contact_type,value_encrypted,value_hmac,status,verified_at,is_primary,visibility) "
                "VALUES (:id,:user,:type,:value,:hmac,:status,:verified,false,:visibility) "
                "ON CONFLICT (id) DO UPDATE SET value_encrypted=EXCLUDED.value_encrypted,value_hmac=EXCLUDED.value_hmac,"
                "status=EXCLUDED.status,verified_at=EXCLUDED.verified_at,visibility=EXCLUDED.visibility,updated_at=now()"
            ),
            {
                "id": _id(f"contact:{contact_type}"),
                "user": user_id,
                "type": contact_type,
                "value": encrypt_private(value),
                "hmac": searchable_hmac(value),
                "status": "verified" if verified else "pending_verification",
                "verified": datetime.now(UTC) if verified else None,
                "visibility": visibility,
            },
        )
    for index, (domain, field_code, visibility) in enumerate(
        (
            ("profile", "display_name", "verified_members"),
            ("profile", "city", "verified_members"),
            ("contact", "verified_contact", "mutual_matches"),
        ),
        start=1,
    ):
        await session.execute(
            text(
                "INSERT INTO user_field_visibility_rules "
                "(id,user_id,data_domain,field_code,visibility,allowed_purposes,allowed_recipient_types) "
                "VALUES (:id,:user,:domain,:field,:visibility,'[\"service_delivery\"]'::jsonb,'[]'::jsonb) "
                "ON CONFLICT (user_id,data_domain,field_code) DO UPDATE SET visibility=EXCLUDED.visibility,updated_at=now()"
            ),
            {
                "id": _id(f"visibility:{index}"),
                "user": user_id,
                "domain": domain,
                "field": field_code,
                "visibility": visibility,
            },
        )
    for consent_code in ("platform_terms", "privacy_policy", "ai_assistant_use"):
        await session.execute(
            text(
                "INSERT INTO user_consents "
                "(id,user_id,consent_definition_id,consent_release_id,status,scope_snapshot,source,evidence,granted_at) "
                "SELECT :id,:user,d.id,r.id,'granted',d.scope_definition,'test_showcase',"
                "'{\"fixture\"\\:true}'::jsonb,now() FROM consent_definitions d JOIN consent_releases r "
                "ON r.consent_definition_id=d.id AND r.locale='zh-CN' AND r.status='active' "
                "WHERE d.consent_code=:code AND NOT EXISTS (SELECT 1 FROM user_consents c WHERE c.user_id=:user "
                "AND c.consent_definition_id=d.id AND c.status='granted')"
            ),
            {"id": _id(f"consent:{consent_code}"), "user": user_id, "code": consent_code},
        )
    requests = (
        ("inventory", "completed", "json", "个人数据清单已生成。"),
        ("export", "completed", "json", "数据导出已完成，可在有效期内下载。"),
        ("correction", "partially_completed", None, "个人简介修正已完成，其余字段无需变更。"),
    )
    for index, (request_type, status, requested_format, message) in enumerate(requests, start=1):
        await session.execute(
            text(
                "INSERT INTO data_subject_requests "
                "(id,request_number,user_id,request_type,status,requested_scope,requested_format,identity_verification_level,"
                "identity_verified_at,reauthenticated_at,submitted_at,due_at,decision_code,decision_reason_safe,completed_at) "
                'VALUES (:id,:number,:user,:type,:status,\'{"modules":["profile","commerce","services"]}\'::jsonb,'
                ":format,'password',now(),now(),now()-CAST(:days AS integer)*interval '1 day',now()+interval '20 days',"
                "'test_showcase_completed',:message,CASE WHEN CAST(:status AS varchar) IN ('completed','partially_completed') "
                "THEN now() ELSE NULL END) "
                "ON CONFLICT (request_number) DO UPDATE SET status=EXCLUDED.status,decision_reason_safe=EXCLUDED.decision_reason_safe,"
                "completed_at=EXCLUDED.completed_at,updated_at=now()"
            ),
            {
                "id": _id(f"privacy-request:{index}"),
                "number": f"PRQ-TEST-{index:03d}",
                "user": user_id,
                "type": request_type,
                "status": status,
                "format": requested_format,
                "days": index * 6,
                "message": message,
            },
        )
    await session.execute(
        text(
            "INSERT INTO ai_memory_preferences "
            "(user_id,long_term_memory_enabled,allow_profile_facts,allow_service_history,allow_relationship_context,allow_cross_conversation_use) "
            "VALUES (:user,true,true,true,true,true) ON CONFLICT (user_id) DO UPDATE SET "
            "long_term_memory_enabled=true,allow_profile_facts=true,allow_service_history=true,"
            "allow_relationship_context=true,allow_cross_conversation_use=true,settings_version=ai_memory_preferences.settings_version+1,updated_at=now()"
        ),
        {"user": user_id},
    )
    memories = (
        ("communication_preference", "我更喜欢先倾听，再用简短清晰的话表达自己的需要。"),
        ("stated_goal", "希望建立稳定的每周关系沟通与复盘习惯。"),
        ("service_preference", "偏好周末参加线上课程与小组活动。"),
    )
    for index, (memory_type, content) in enumerate(memories, start=1):
        await session.execute(
            text(
                "INSERT INTO ai_memory_items "
                "(id,user_id,memory_type,status,content_encrypted,content_hmac,source_type,provenance_snapshot,certainty,"
                "user_confirmed,allowed_purposes,allowed_agent_profiles) "
                "VALUES (:id,:user,:type,'active',:content,:hmac,'test_showcase','{\"synthetic\"\\:true}'::jsonb,"
                "'user_confirmed',true,'[\"personalization\"]'::jsonb,'[\"hanna_v1\"]'::jsonb) "
                "ON CONFLICT (id) DO UPDATE SET content_encrypted=EXCLUDED.content_encrypted,content_hmac=EXCLUDED.content_hmac,"
                "status='active',updated_at=now(),deleted_at=NULL"
            ),
            {
                "id": _id(f"memory:{index}"),
                "user": user_id,
                "type": memory_type,
                "content": encrypt_private(content),
                "hmac": searchable_hmac(content),
            },
        )


async def _seed_notifications(session: AsyncSession, user_id: UUID) -> None:
    fixtures = (
        ("activity", "活动报名已确认", "你已成功报名“健康边界练习工作坊”。", "/account/activities"),
        ("course", "课程学习提醒", "“关系沟通练习课”有新的练习等待完成。", "/account/learning"),
        (
            "platform",
            "欢迎回来",
            "你的 test 展示账户已准备好，可以浏览全部示例功能。",
            "/account/home",
        ),
    )
    for index, (category, title, body, action_url) in enumerate(fixtures, start=1):
        intent_id = _id(f"notification-intent:{index}")
        await session.execute(
            text(
                "INSERT INTO notification_intents "
                "(id,notification_type,category,priority,recipient_type,recipient_reference_id,template_code,channel_policy,"
                "preference_policy,template_variables_encrypted,action_reference,deduplication_key,status,created_at) "
                "VALUES (:id,'test-showcase',:category,'normal','user',:user,'platform-announcement',"
                "'{\"required\"\\:[\"in_app\"]}'::jsonb,'service_optional','test-showcase',"
                "CAST(:action AS jsonb),:dedupe,'created',now()-CAST(:days AS integer)*interval '1 day') "
                "ON CONFLICT (deduplication_key) DO UPDATE SET status='created'"
            ),
            {
                "id": intent_id,
                "category": category,
                "user": user_id,
                "action": _json({"route": action_url}),
                "dedupe": f"{SHOWCASE_PREFIX}:notification:{index}",
                "days": index - 1,
            },
        )
        await session.execute(
            text(
                "INSERT INTO user_notifications "
                "(id,user_id,notification_intent_id,category,priority,title,body,action_type,action_reference,action_url,status,"
                "read_at,rendering_snapshot,created_at) VALUES (:id,:user,:intent,:category,'normal',:title,:body,'route',"
                "CAST(:action AS jsonb),:url,'active',CASE WHEN :read THEN now() ELSE NULL END,"
                '\'{"locale"\\:"zh-CN","channel"\\:"in_app","fixture"\\:true}\'::jsonb,'
                "now()-CAST(:days AS integer)*interval '1 day') ON CONFLICT (user_id,notification_intent_id) DO UPDATE SET "
                "title=EXCLUDED.title,body=EXCLUDED.body,action_url=EXCLUDED.action_url,status='active',withdrawn_at=NULL"
            ),
            {
                "id": _id(f"notification:{index}"),
                "user": user_id,
                "intent": intent_id,
                "category": category,
                "title": title,
                "body": body,
                "action": _json({"route_name": action_url}),
                "url": action_url,
                "read": index == 3,
                "days": index - 1,
            },
        )
        await session.execute(
            text(
                "INSERT INTO notification_preferences "
                "(id,user_id,category,channel,enabled,frequency,quiet_hours_enabled,source) "
                "VALUES (:id,:user,:category,'in_app',true,'immediate',false,'test_showcase') "
                "ON CONFLICT (user_id,category,channel) DO UPDATE SET enabled=true,frequency='immediate',source='test_showcase',updated_at=now()"
            ),
            {"id": _id(f"notification-preference:{index}"), "user": user_id, "category": category},
        )


async def _seed_ai_conversations(session: AsyncSession, user_id: UUID) -> None:
    conversations = (
        (
            "沟通前如何整理自己的需要？",
            "先区分事实、感受和需要，再准备一句不指责的表达。",
            "communication",
        ),
        (
            "第一次参加活动有点紧张",
            "可以先设一个很小的目标，例如主动向一位参与者问好。",
            "social_connection",
        ),
        (
            "怎样坚持每周复盘？",
            "把复盘缩短到十分钟，并固定一个容易记住的时间。",
            "relationship_growth",
        ),
    )
    for index, (question, answer, topic) in enumerate(conversations, start=1):
        conversation_id = _id(f"ai-conversation:{index}")
        last_message_at = datetime.now(UTC) - timedelta(days=index - 1)
        await session.execute(
            text(
                "INSERT INTO ai_conversations "
                "(id,conversation_number,user_id,status,assistant_profile,locale,user_timezone,consent_version,consented_at,"
                "memory_consent_status,relationship_stage,primary_topic,latest_risk_level,active_graph_version,last_message_at) "
                "VALUES (:id,:number,:user,'active','hanna_v1','zh-CN','Asia/Shanghai','1.0.0',now(),"
                "'granted','getting_to_know',:topic,'none','hanna-graph-v1',:last_message) "
                "ON CONFLICT (conversation_number) DO UPDATE SET status='active',last_message_at=EXCLUDED.last_message_at,updated_at=now(),deleted_at=NULL"
            ),
            {
                "id": conversation_id,
                "number": f"AI-TEST-{index:03d}",
                "user": user_id,
                "topic": topic,
                "last_message": last_message_at,
            },
        )
        for role, content in (("user", question), ("assistant", answer)):
            message_id = _id(f"ai-message:{index}:{role}")
            await session.execute(
                text(
                    "INSERT INTO ai_messages "
                    "(id,conversation_id,turn_number,role,message_type,client_message_id,content_encrypted,content_hash,locale,"
                    "model_provider,model_name,status,created_at) VALUES (:id,:conversation,1,:role,'text',:client_id,:content,:hash,"
                    "'zh-CN',CASE WHEN CAST(:role AS varchar)='assistant' THEN 'fixture' ELSE NULL END,"
                    "CASE WHEN CAST(:role AS varchar)='assistant' THEN 'test-showcase' ELSE NULL END,'completed',:created) "
                    "ON CONFLICT (id) DO UPDATE SET content_encrypted=EXCLUDED.content_encrypted,content_hash=EXCLUDED.content_hash,status='completed'"
                ),
                {
                    "id": message_id,
                    "conversation": conversation_id,
                    "role": role,
                    "client_id": f"{SHOWCASE_PREFIX}-{index}-{role}",
                    "content": encrypt_ai_data({"content": content}),
                    "hash": content_hash(content),
                    "created": last_message_at,
                },
            )


async def _seed_sessions_and_experience(session: AsyncSession, user_id: UUID) -> None:
    now = datetime.now(UTC)
    sessions = (
        ("Safari · macOS", "active", 0),
        ("Chrome · Windows", "active", 12),
        ("Mobile Safari · iPhone", "active", 30),
    )
    for index, (device, status, age_days) in enumerate(sessions, start=1):
        session_id = _id(f"auth-session:{index}")
        issued_at = now - timedelta(days=age_days)
        await session.execute(
            text(
                "INSERT INTO auth_sessions "
                "(id,user_id,session_family_id,refresh_token_hash,audience,status,issued_at,expires_at,last_used_at,"
                "revoked_at,revoke_reason,device_name,user_agent_hash,ip_address_hash) "
                "VALUES (:id,:user,:family,:hash,'user',:status,:issued,:expires,:last_used,"
                "CASE WHEN CAST(:status AS varchar)='revoked' THEN CAST(:last_used AS timestamptz) ELSE NULL END,"
                "CASE WHEN CAST(:status AS varchar)='revoked' THEN 'test_showcase_history' ELSE NULL END,:device,:agent,:ip) "
                "ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,expires_at=EXCLUDED.expires_at,"
                "revoked_at=NULL,revoke_reason=NULL,device_name=EXCLUDED.device_name,updated_at=now()"
            ),
            {
                "id": session_id,
                "user": user_id,
                "family": _id(f"auth-family:{index}"),
                "hash": hashlib.sha256(f"{SHOWCASE_PREFIX}:refresh:{index}".encode()).hexdigest(),
                "status": status,
                "issued": issued_at,
                "expires": now + timedelta(days=20)
                if status == "active"
                else issued_at + timedelta(days=7),
                "last_used": issued_at + timedelta(hours=2),
                "device": device,
                "agent": hashlib.sha256(device.encode()).hexdigest(),
                "ip": hashlib.sha256(f"fixture-ip-{index}".encode()).hexdigest(),
            },
        )
    task_rows = (
        ("matchmaking.profile", "in_progress", 820, 2),
        ("activities.registration", "available", 700, 5),
        ("courses.continue", "waiting_user", 650, 7),
    )
    for index, (task_code, state, priority, due_days) in enumerate(task_rows, start=1):
        await session.execute(
            text(
                "INSERT INTO experience_user_tasks "
                "(id,user_id,task_definition_id,source_module,source_entity_type,source_entity_id,deduplication_key,state,priority,due_at,authoritative_state_version) "
                "SELECT :id,:user,d.id,d.source_module,'test_showcase',:entity,:dedupe,:state,:priority,"
                "now()+CAST(:days AS integer)*interval '1 day','test-showcase-v1' FROM experience_task_definitions d "
                "WHERE d.task_code=:code AND d.active ORDER BY d.version DESC LIMIT 1 "
                "ON CONFLICT (user_id,deduplication_key) DO UPDATE SET state=EXCLUDED.state,priority=EXCLUDED.priority,due_at=EXCLUDED.due_at,updated_at=now()"
            ),
            {
                "id": _id(f"experience-task:{index}"),
                "user": user_id,
                "entity": _id(f"experience-task-entity:{index}"),
                "dedupe": f"{SHOWCASE_PREFIX}:task:{index}",
                "state": state,
                "priority": priority,
                "days": due_days,
                "code": task_code,
            },
        )
    for index, journey_code in enumerate(("activity", "course", "relationship"), start=1):
        await session.execute(
            text(
                "INSERT INTO experience_journey_instances "
                "(id,definition_id,user_id,source_module,source_entity_type,source_entity_id,current_step_code,context_snapshot,"
                "authoritative_state_version,state,started_at) SELECT :id,d.id,:user,'test_showcase','fixture',:entity,"
                "COALESCE(d.step_manifest->0->>'code','started'),'{\"synthetic\"\\:true}'::jsonb,'test-showcase-v1',"
                "CASE WHEN :index=3 THEN 'waiting' ELSE 'active' END,now()-CAST(:index AS integer)*interval '1 day' "
                "FROM experience_journey_definitions d WHERE d.journey_code=:code AND d.status='active' "
                "ORDER BY d.version DESC LIMIT 1 ON CONFLICT (id) DO UPDATE SET updated_at=now()"
            ),
            {
                "id": _id(f"experience-journey:{index}"),
                "user": user_id,
                "entity": _id(f"experience-journey-entity:{index}"),
                "index": index,
                "code": journey_code,
            },
        )


async def _seed_activity_registrations(session: AsyncSession, user_id: UUID) -> None:
    codes = (
        "activity-e2e-social",
        "activity-showcase-boundaries",
        "activity-showcase-walk",
    )
    statuses = (
        ("confirmed", "not_checked_in"),
        ("confirmed", "not_checked_in"),
        ("confirmed", "checked_in"),
    )
    for index, (code, (status, attendance)) in enumerate(
        zip(codes, statuses, strict=True), start=1
    ):
        row = (
            (
                await session.execute(
                    text(
                        "SELECT a.id AS activity_id,t.id AS ticket_id FROM activities a "
                        "JOIN activity_ticket_types t ON t.activity_id=a.id AND t.ticket_code='general' "
                        "WHERE a.activity_code=:code"
                    ),
                    {"code": code},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise RuntimeError(f"Activity showcase fixture is missing: {code}")
        await session.execute(
            text(
                "INSERT INTO activity_registrations "
                "(id,registration_number,activity_id,ticket_type_id,user_id,status,attendance_status,form_schema_version,"
                "form_response_encrypted,review_status,confirmed_at,cancelled_at) "
                "VALUES (:id,:number,:activity,:ticket,:user,:status,:attendance,1,:response,'approved',"
                "CASE WHEN CAST(:status AS varchar)='confirmed' THEN now() ELSE NULL END,"
                "CASE WHEN CAST(:status AS varchar)='cancelled' THEN now() ELSE NULL END) "
                "ON CONFLICT (activity_id,user_id) DO UPDATE SET status=EXCLUDED.status,attendance_status=EXCLUDED.attendance_status,"
                "registration_number=EXCLUDED.registration_number,form_response_encrypted=EXCLUDED.form_response_encrypted,confirmed_at=EXCLUDED.confirmed_at,"
                "cancelled_at=EXCLUDED.cancelled_at,updated_at=now()"
            ),
            {
                "id": _id(f"activity-registration:{index}"),
                "number": f"REG-TEST-{index:03d}",
                "activity": row["activity_id"],
                "ticket": row["ticket_id"],
                "user": user_id,
                "status": status,
                "attendance": attendance,
                "response": encrypt_service(
                    {"expectations": "认识新朋友，并练习更清晰的沟通。", "synthetic": True}
                ),
            },
        )
        registration_id = await session.scalar(
            text(
                "SELECT id FROM activity_registrations WHERE activity_id=:activity AND user_id=:user"
            ),
            {"activity": row["activity_id"], "user": user_id},
        )
        await session.execute(
            text(
                "INSERT INTO activity_waitlist_entries "
                "(id,activity_id,ticket_type_id,user_id,registration_id,status,sequence_number,priority_score,joined_at,"
                "promotion_offered_at,promotion_offer_expires_at,promoted_at) "
                "VALUES (:id,:activity,:ticket,:user,:registration,:status,:sequence,0,"
                "now()-CAST(:days AS integer)*interval '1 day',"
                "CASE WHEN CAST(:status AS varchar)='offer_expired' THEN now()-interval '3 days' ELSE NULL END,"
                "CASE WHEN CAST(:status AS varchar)='offer_expired' THEN now()-interval '2 days' ELSE NULL END,"
                "CASE WHEN CAST(:status AS varchar)='promoted' THEN now()-interval '1 day' ELSE NULL END) "
                "ON CONFLICT (activity_id,ticket_type_id,user_id) DO UPDATE SET status=EXCLUDED.status,"
                "sequence_number=EXCLUDED.sequence_number,promotion_offered_at=EXCLUDED.promotion_offered_at,"
                "promotion_offer_expires_at=EXCLUDED.promotion_offer_expires_at,promoted_at=EXCLUDED.promoted_at,updated_at=now()"
            ),
            {
                "id": _id(f"activity-waitlist:{index}"),
                "activity": row["activity_id"],
                "ticket": row["ticket_id"],
                "user": user_id,
                "registration": registration_id,
                "status": ("promoted", "declined", "offer_expired")[index - 1],
                "sequence": index,
                "days": index * 4,
            },
        )


async def _seed_activity_experience(session: AsyncSession, user_id: UUID) -> None:
    activity = (
        (
            await session.execute(
                text(
                    "SELECT a.id AS activity_id,t.id AS ticket_id FROM activities a "
                    "JOIN activity_ticket_types t ON t.activity_id=a.id AND t.ticket_code='general' "
                    "WHERE a.activity_code='activity-showcase-walk'"
                )
            )
        )
        .mappings()
        .one()
    )
    activity_id = activity["activity_id"]
    await session.execute(
        text(
            "UPDATE activities SET status='completed',registration_opens_at=now()-interval '40 days',"
            "registration_closes_at=now()-interval '10 days',starts_at=now()-interval '8 days',"
            "ends_at=now()-interval '8 days'+interval '2 hours',post_event_choice_enabled=true,"
            "post_event_choice_opens_at=now()-interval '7 days',post_event_choice_closes_at=now()+interval '21 days',"
            "updated_at=now() WHERE id=:activity"
        ),
        {"activity": activity_id},
    )
    targets = list(
        (
            await session.execute(
                text(
                    "SELECT id,email FROM users WHERE email=ANY(CAST(:emails AS citext[])) "
                    "ORDER BY array_position(CAST(:emails AS citext[]),email)"
                ),
                {
                    "emails": [
                        "recommendation-fixture-jonathan@example.com",
                        "recommendation-fixture-daniel@example.com",
                        "recommendation-fixture-peter@example.com",
                    ]
                },
            )
        ).mappings()
    )
    if len(targets) != 3:
        raise RuntimeError("Three activity-experience fixture members are required.")
    test_registration_id = await session.scalar(
        text("SELECT id FROM activity_registrations WHERE activity_id=:activity AND user_id=:user"),
        {"activity": activity_id, "user": user_id},
    )
    participant_rows: list[tuple[UUID, UUID, str]] = [
        (user_id, cast(UUID, test_registration_id), "Test 用户")
    ]
    for index, target in enumerate(targets, start=1):
        target_id = cast(UUID, target["id"])
        registration_id = _id(f"activity-experience-registration:{index}")
        await session.execute(
            text(
                "INSERT INTO activity_registrations "
                "(id,registration_number,activity_id,ticket_type_id,user_id,status,attendance_status,form_schema_version,"
                "form_response_encrypted,review_status,confirmed_at) "
                "VALUES (:id,:number,:activity,:ticket,:user,'confirmed','checked_in',1,:response,'approved',now()-interval '20 days') "
                "ON CONFLICT (activity_id,user_id) DO UPDATE SET status='confirmed',attendance_status='checked_in',"
                "form_response_encrypted=EXCLUDED.form_response_encrypted,cancelled_at=NULL,updated_at=now()"
            ),
            {
                "id": registration_id,
                "number": f"REG-TEST-EXPERIENCE-{index:03d}",
                "activity": activity_id,
                "ticket": activity["ticket_id"],
                "user": target_id,
                "response": encrypt_service({"synthetic": True, "role": "showcase participant"}),
            },
        )
        actual_registration_id = await session.scalar(
            text(
                "SELECT id FROM activity_registrations WHERE activity_id=:activity AND user_id=:user"
            ),
            {"activity": activity_id, "user": target_id},
        )
        participant_rows.append(
            (target_id, cast(UUID, actual_registration_id), str(target["email"]).split("@")[0])
        )
    for index, (participant_id, registration_id, display_name) in enumerate(
        participant_rows, start=0
    ):
        await session.execute(
            text(
                "INSERT INTO activity_participant_profiles "
                "(id,activity_id,registration_id,user_id,display_name,brief_introduction,visibility_status) "
                "VALUES (:id,:activity,:registration,:user,:name,:intro,'visible') "
                "ON CONFLICT (activity_id,user_id) DO UPDATE SET registration_id=EXCLUDED.registration_id,"
                "display_name=EXCLUDED.display_name,brief_introduction=EXCLUDED.brief_introduction,visibility_status='visible',updated_at=now()"
            ),
            {
                "id": _id(f"activity-participant-profile:{index}"),
                "activity": activity_id,
                "registration": registration_id,
                "user": participant_id,
                "name": display_name,
                "intro": "喜欢真诚交流、城市漫步与共同成长的测试参与者。",
            },
        )
    plan_id = _id("activity-grouping-plan")
    group_id = _id("activity-group")
    await session.execute(
        text(
            "INSERT INTO activity_grouping_plans "
            "(id,activity_id,plan_name,grouping_method,target_group_size,target_group_count,grouping_rules,random_seed,status,created_by) "
            "VALUES (:id,:activity,'Test 展示分组','manual',4,1,'{\"fixture\"\\:true}'::jsonb,'test-showcase','published',:user) "
            "ON CONFLICT (id) DO UPDATE SET status='published',target_group_size=4,updated_at=now()"
        ),
        {"id": plan_id, "activity": activity_id, "user": user_id},
    )
    await session.execute(
        text(
            "INSERT INTO activity_groups (id,grouping_plan_id,group_code,display_name,capacity) "
            "VALUES (:id,:plan,'TEST-A','同行成长 A 组',4) "
            "ON CONFLICT (grouping_plan_id,group_code) DO UPDATE SET display_name=EXCLUDED.display_name,capacity=4"
        ),
        {"id": group_id, "plan": plan_id},
    )
    actual_group_id = await session.scalar(
        text("SELECT id FROM activity_groups WHERE grouping_plan_id=:plan AND group_code='TEST-A'"),
        {"plan": plan_id},
    )
    for index, (_, registration_id, _) in enumerate(participant_rows, start=0):
        await session.execute(
            text(
                "INSERT INTO activity_group_members "
                "(id,grouping_plan_id,group_id,registration_id,assignment_source,assignment_reason,assigned_by,assigned_at) "
                "VALUES (:id,:plan,:group,:registration,'manual','test_showcase',:user,now()-interval '9 days') "
                "ON CONFLICT (id) DO UPDATE SET group_id=EXCLUDED.group_id,registration_id=EXCLUDED.registration_id,removed_at=NULL"
            ),
            {
                "id": _id(f"activity-group-member:{index}"),
                "plan": plan_id,
                "group": actual_group_id,
                "registration": registration_id,
                "user": user_id,
            },
        )
    for index, target in enumerate(targets, start=1):
        target_id = cast(UUID, target["id"])
        user_choice_id = _id(f"activity-choice:user:{index}")
        target_choice_id = _id(f"activity-choice:target:{index}")
        for choice_id, chooser, chosen in (
            (user_choice_id, user_id, target_id),
            (target_choice_id, target_id, user_id),
        ):
            await session.execute(
                text(
                    "INSERT INTO activity_post_event_choices "
                    "(id,activity_id,chooser_user_id,chosen_user_id,choice,status,submitted_at) "
                    "VALUES (:id,:activity,:chooser,:chosen,'interested','active',now()-CAST(:days AS integer)*interval '1 day') "
                    "ON CONFLICT (activity_id,chooser_user_id,chosen_user_id) DO UPDATE SET choice='interested',status='active',"
                    "submitted_at=EXCLUDED.submitted_at,withdrawn_at=NULL,version=activity_post_event_choices.version+1"
                ),
                {
                    "id": choice_id,
                    "activity": activity_id,
                    "chooser": chooser,
                    "chosen": chosen,
                    "days": index,
                },
            )
        actual_user_choice = await session.scalar(
            text(
                "SELECT id FROM activity_post_event_choices WHERE activity_id=:activity "
                "AND chooser_user_id=:user AND chosen_user_id=:target"
            ),
            {"activity": activity_id, "user": user_id, "target": target_id},
        )
        actual_target_choice = await session.scalar(
            text(
                "SELECT id FROM activity_post_event_choices WHERE activity_id=:activity "
                "AND chooser_user_id=:target AND chosen_user_id=:user"
            ),
            {"activity": activity_id, "user": user_id, "target": target_id},
        )
        low, high = _canonical_pair(user_id, target_id)
        first_choice = actual_user_choice if low == user_id else actual_target_choice
        second_choice = actual_target_choice if low == user_id else actual_user_choice
        await session.execute(
            text(
                "INSERT INTO activity_mutual_choices "
                "(id,activity_id,user_a_id,user_b_id,first_choice_id,second_choice_id,status,matched_at) "
                "VALUES (:id,:activity,:low,:high,:first,:second,'matched_private',now()-CAST(:days AS integer)*interval '1 day') "
                "ON CONFLICT (activity_id,user_a_id,user_b_id) DO UPDATE SET first_choice_id=EXCLUDED.first_choice_id,"
                "second_choice_id=EXCLUDED.second_choice_id,status='matched_private',matched_at=EXCLUDED.matched_at"
            ),
            {
                "id": _id(f"activity-mutual-choice:{index}"),
                "activity": activity_id,
                "low": low,
                "high": high,
                "first": first_choice,
                "second": second_choice,
                "days": index,
            },
        )


async def _seed_course_learning(session: AsyncSession, user_id: UUID) -> None:
    codes = (
        "course-e2e-foundations",
        "course-showcase-communication",
        "course-showcase-growth-plan",
    )
    progress_values = (10000, 10000, 10000)
    for index, (code, progress) in enumerate(zip(codes, progress_values, strict=True), start=1):
        course = (
            (
                await session.execute(
                    text(
                        "SELECT c.id AS course_id,v.id AS version_id,l.title FROM courses c "
                        "JOIN course_versions v ON v.course_id=c.id "
                        "JOIN course_localizations l ON l.course_id=c.id AND l.locale='zh-CN' "
                        "WHERE c.course_code=:code ORDER BY v.version_number DESC LIMIT 1"
                    ),
                    {"code": code},
                )
            )
            .mappings()
            .first()
        )
        if course is None:
            raise RuntimeError(f"Course showcase fixture is missing: {code}")
        enrollment_id = _id(f"course-enrollment:{index}")
        completed = progress == 10000
        await session.execute(
            text(
                "INSERT INTO course_enrollments "
                "(id,user_id,course_id,course_version_id,source_type,status,access_starts_at,access_expires_at,enrolled_at,"
                "first_accessed_at,completed_at) VALUES (:id,:user,:course,:version,'free_enrollment',:status,"
                "now()-CAST(:days AS integer)*interval '1 day',now()+interval '365 days',"
                "now()-CAST(:days AS integer)*interval '1 day',now()-CAST(:access_days AS integer)*interval '1 day',"
                "CASE WHEN :completed THEN now()-interval '2 days' ELSE NULL END) "
                "ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,completed_at=EXCLUDED.completed_at,updated_at=now()"
            ),
            {
                "id": enrollment_id,
                "user": user_id,
                "course": course["course_id"],
                "version": course["version_id"],
                "status": "completed" if completed else "active",
                "days": 20 - index * 3,
                "access_days": max(1, 10 - index),
                "completed": completed,
            },
        )
        lessons = (
            (
                await session.execute(
                    text(
                        "SELECT l.id FROM course_lessons l JOIN course_modules m ON m.id=l.module_id "
                        "WHERE m.course_id=:course ORDER BY m.sort_order,l.sort_order LIMIT 3"
                    ),
                    {"course": course["course_id"]},
                )
            )
            .scalars()
            .all()
        )
        for lesson_index, lesson_id in enumerate(lessons, start=1):
            lesson_progress = progress if lesson_index == 1 else (10000 if completed else 0)
            await session.execute(
                text(
                    "INSERT INTO lesson_progress "
                    "(id,enrollment_id,lesson_id,status,progress_basis_points,started_at,last_accessed_at,completed_at,completion_source,completion_evidence) "
                    "VALUES (:id,:enrollment,:lesson,:status,:progress,now()-interval '4 days',now()-interval '1 day',"
                    "CASE WHEN :progress=10000 THEN now()-interval '1 day' ELSE NULL END,"
                    "CASE WHEN :progress=10000 THEN 'manual' ELSE NULL END,'{\"synthetic\"\\:true}'::jsonb) "
                    "ON CONFLICT (enrollment_id,lesson_id) DO UPDATE SET status=EXCLUDED.status,"
                    "progress_basis_points=EXCLUDED.progress_basis_points,last_accessed_at=EXCLUDED.last_accessed_at,updated_at=now()"
                ),
                {
                    "id": _id(f"lesson-progress:{index}:{lesson_index}"),
                    "enrollment": enrollment_id,
                    "lesson": lesson_id,
                    "status": "completed" if lesson_progress == 10000 else "in_progress",
                    "progress": lesson_progress,
                },
            )
        if completed:
            completion_id = _id(f"course-completion:{index}")
            await session.execute(
                text(
                    "INSERT INTO course_completion_records "
                    "(id,enrollment_id,course_id,course_version_id,completion_policy_snapshot,completion_evidence,completed_at,evaluated_by,evaluation_version) "
                    "VALUES (:id,:enrollment,:course,:version,'{\"required_lessons\"\\:true}'::jsonb,"
                    "'{\"synthetic\"\\:true}'::jsonb,now()-interval '2 days','test_showcase','1.0.0') "
                    "ON CONFLICT (enrollment_id) DO NOTHING"
                ),
                {
                    "id": completion_id,
                    "enrollment": enrollment_id,
                    "course": course["course_id"],
                    "version": course["version_id"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO course_certificates "
                    "(id,certificate_number,completion_record_id,user_id,course_id,recipient_name_snapshot,course_title_snapshot,"
                    "issued_at,status,verification_token_hash) VALUES (:id,:number,:completion,:user,:course,'Test 用户',:title,"
                    "now()-interval '2 days','active',:token) ON CONFLICT (certificate_number) DO UPDATE SET status='active',updated_at=now()"
                ),
                {
                    "id": _id(f"course-certificate:{index}"),
                    "number": f"CERT-TEST-{index:03d}",
                    "completion": completion_id,
                    "user": user_id,
                    "course": course["course_id"],
                    "title": course["title"],
                    "token": hashlib.sha256(
                        f"{SHOWCASE_PREFIX}:certificate:{index}".encode()
                    ).hexdigest(),
                },
            )


async def _seed_counseling_appointments(session: AsyncSession, user_id: UUID) -> None:
    services = (
        ("counseling-e2e-growth-session", "completed", -14),
        ("counseling-showcase-communication", "confirmed", 7),
        ("counseling-showcase-decisions", "cancelled", 18),
    )
    mentor_id = await session.scalar(
        text("SELECT id FROM counseling_mentors WHERE mentor_code='counseling-e2e-mentor'")
    )
    if mentor_id is None:
        raise RuntimeError("Counseling showcase mentor is missing.")
    for index, (service_code, status, day_offset) in enumerate(services, start=1):
        service_id = await session.scalar(
            text("SELECT id FROM counseling_services WHERE service_code=:code"),
            {"code": service_code},
        )
        if service_id is None:
            raise RuntimeError(f"Counseling showcase service is missing: {service_code}")
        starts_at = datetime.now(UTC).replace(
            hour=2 + index * 2, minute=0, second=0, microsecond=0
        ) + timedelta(days=day_offset)
        appointment_id = _id(f"counseling-appointment:{index}")
        await session.execute(
            text(
                "INSERT INTO counseling_appointments "
                "(id,appointment_number,user_id,mentor_id,service_id,status,scheduled_starts_at,scheduled_ends_at,user_timezone,"
                "intake_schema_version,intake_response_encrypted,payment_status,cancellation_policy_snapshot,no_show_policy_snapshot,idempotency_key) "
                "VALUES (:id,:number,:user,:mentor,:service,:status,:starts,:ends,'Asia/Shanghai',1,:intake,'not_required',"
                '\'{"mode"\\:"manual_review"}\'::jsonb,\'{"consume_credit"\\:false}\'::jsonb,:key) '
                "ON CONFLICT (user_id,idempotency_key) DO UPDATE SET status=EXCLUDED.status,scheduled_starts_at=EXCLUDED.scheduled_starts_at,"
                "scheduled_ends_at=EXCLUDED.scheduled_ends_at,updated_at=now()"
            ),
            {
                "id": appointment_id,
                "number": f"APT-TEST-{index:03d}",
                "user": user_id,
                "mentor": mentor_id,
                "service": service_id,
                "status": status,
                "starts": starts_at,
                "ends": starts_at + timedelta(minutes=60),
                "intake": encrypt_service(
                    {"focus": "沟通与关系成长", "notes": f"test showcase appointment {index}"}
                ),
                "key": f"{SHOWCASE_PREFIX}:appointment:{index}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO counseling_appointment_history "
                "(id,appointment_id,from_status,to_status,actor_id,reason) VALUES (:id,:appointment,'requested',:status,:user,'test showcase') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": _id(f"counseling-history:{index}"),
                "appointment": appointment_id,
                "status": status,
                "user": user_id,
            },
        )
        if status == "completed":
            await session.execute(
                text(
                    "INSERT INTO counseling_sessions "
                    "(id,appointment_id,status,meeting_reference_encrypted,recording_enabled,transcription_enabled,started_at,completed_at,completion_key) "
                    "VALUES (:id,:appointment,'completed',:meeting,false,false,:starts,:ends,:key) "
                    "ON CONFLICT (appointment_id) DO UPDATE SET status='completed',completed_at=EXCLUDED.completed_at"
                ),
                {
                    "id": _id(f"counseling-session:{index}"),
                    "appointment": appointment_id,
                    "meeting": encrypt_service({"provider": "fixture", "reference": "completed"}),
                    "starts": starts_at,
                    "ends": starts_at + timedelta(minutes=60),
                    "key": f"{SHOWCASE_PREFIX}:counseling-completion:{index}",
                },
            )
        await session.execute(
            text(
                "INSERT INTO counseling_follow_ups "
                "(id,appointment_id,user_id,assigned_to,follow_up_type,status,due_at,content_encrypted) "
                "VALUES (:id,:appointment,:user,:mentor,'practice',:status,:due,:content) "
                "ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,due_at=EXCLUDED.due_at"
            ),
            {
                "id": _id(f"counseling-followup:{index}"),
                "appointment": appointment_id,
                "user": user_id,
                "mentor": user_id,
                "status": "completed" if status == "completed" else "open",
                "due": starts_at + timedelta(days=3),
                "content": encrypt_service(
                    {"content": "记录一次表达需要与倾听回应的练习。", "synthetic": True}
                ),
            },
        )


async def _seed_commerce(session: AsyncSession, user_id: UUID) -> None:
    catalog_codes = (
        "COURSE_E2E_FOUNDATIONS_ACCESS",
        "ACTIVITY_SHOWCASE_BOUNDARIES_FREE",
        "COUNSELING_E2E_SINGLE",
    )
    catalog_rows = list(
        (
            await session.execute(
                text(
                    "SELECT s.id AS sku_id,s.sku_code,s.internal_name AS sku_name,s.billing_type,"
                    "p.id AS product_id,p.product_code,p.product_type,p.fulfillment_type,"
                    "COALESCE(l.name,p.internal_name) AS product_name,pr.id AS price_id,pr.price_book_id,"
                    "pr.currency_code,pr.unit_amount_minor FROM product_skus s JOIN products p ON p.id=s.product_id "
                    "LEFT JOIN product_localizations l ON l.product_id=p.id AND l.locale='zh-CN' "
                    "JOIN LATERAL (SELECT prices.* FROM prices WHERE prices.sku_id=s.id AND prices.status='active' "
                    "ORDER BY prices.valid_from DESC LIMIT 1) pr ON true WHERE s.sku_code=ANY(CAST(:codes AS varchar[])) "
                    "ORDER BY array_position(CAST(:codes AS varchar[]),s.sku_code)"
                ),
                {"codes": list(catalog_codes)},
            )
        ).mappings()
    )
    if len(catalog_rows) != 3:
        raise RuntimeError("The three Catalog showcase SKUs are not available.")
    existing_cart_id = await session.scalar(
        text(
            "SELECT id FROM carts WHERE user_id=:user AND currency_code='USD' "
            "AND status IN ('active','checkout_started') ORDER BY created_at LIMIT 1"
        ),
        {"user": user_id},
    )
    cart_id = cast(UUID, existing_cart_id or _id("cart"))
    await session.execute(
        text(
            "INSERT INTO carts (id,user_id,status,currency_code,expires_at) "
            "VALUES (:id,:user,'active','USD',now()+interval '30 days') "
            "ON CONFLICT (id) DO UPDATE SET status='active',expires_at=EXCLUDED.expires_at,updated_at=now()"
        ),
        {"id": cart_id, "user": user_id},
    )
    for index, row in enumerate(catalog_rows, start=1):
        await session.execute(
            text(
                "INSERT INTO cart_items (id,cart_id,sku_id,quantity) VALUES (:id,:cart,:sku,1) "
                "ON CONFLICT (cart_id,sku_id) DO UPDATE SET quantity=1,updated_at=now()"
            ),
            {
                "id": _id(f"cart-item:{cart_id}:{index}"),
                "cart": cart_id,
                "sku": row["sku_id"],
            },
        )
        quote_id = _id(f"pricing-quote:{index}")
        amount = int(row["unit_amount_minor"])
        await session.execute(
            text(
                "INSERT INTO pricing_quotes "
                "(id,user_id,sku_id,price_id,price_book_id,quantity,currency_code,unit_amount_minor,subtotal_minor,"
                "discount_total_minor,tax_estimate_minor,total_minor,calculation_snapshot,expires_at,consumed_at) "
                "VALUES (:id,:user,:sku,:price,:book,1,:currency,:amount,:amount,0,0,:amount,"
                "'{\"fixture\"\\:true}'::jsonb,now()+interval '365 days',now()) ON CONFLICT (id) DO UPDATE SET consumed_at=now()"
            ),
            {
                "id": quote_id,
                "user": user_id,
                "sku": row["sku_id"],
                "price": row["price_id"],
                "book": row["price_book_id"],
                "currency": row["currency_code"],
                "amount": amount,
            },
        )
        order_id = _id(f"order:{index}")
        status = ("fulfilled", "paid", "cancelled")[index - 1]
        placed_at = datetime.now(UTC) - timedelta(days=index * 5)
        await session.execute(
            text(
                "INSERT INTO orders "
                "(id,order_number,user_id,status,currency_code,subtotal_minor,discount_total_minor,tax_total_minor,total_minor,"
                "refunded_total_minor,pricing_quote_id,billing_email,billing_name,locale,region_code,placed_at,paid_at,fulfilled_at,cancelled_at) "
                "VALUES (:id,:number,:user,:status,:currency,:amount,0,0,:amount,0,:quote,:email,'Test 用户','zh-CN','CN',"
                ":placed,CASE WHEN CAST(:status AS varchar) IN ('paid','fulfilled') THEN CAST(:placed AS timestamptz) ELSE NULL END,"
                "CASE WHEN CAST(:status AS varchar)='fulfilled' THEN CAST(:placed AS timestamptz) ELSE NULL END,"
                "CASE WHEN CAST(:status AS varchar)='cancelled' THEN CAST(:placed AS timestamptz) ELSE NULL END) "
                "ON CONFLICT (order_number) DO UPDATE SET status=EXCLUDED.status,paid_at=EXCLUDED.paid_at,"
                "fulfilled_at=EXCLUDED.fulfilled_at,cancelled_at=EXCLUDED.cancelled_at,updated_at=now()"
            ),
            {
                "id": order_id,
                "number": f"ORD-TEST-{index:03d}",
                "user": user_id,
                "status": status,
                "currency": row["currency_code"],
                "amount": amount,
                "quote": quote_id,
                "email": TEST_USER_EMAIL,
                "placed": placed_at,
            },
        )
        order_item_id = _id(f"order-item:{index}")
        await session.execute(
            text(
                "INSERT INTO order_items "
                "(id,order_id,product_id,sku_id,price_id,pricing_quote_id,product_code,sku_code,product_name_snapshot,"
                "sku_name_snapshot,product_type,fulfillment_type,quantity,unit_amount_minor,subtotal_minor,discount_total_minor,"
                "total_minor,fulfillment_snapshot,promotion_snapshot) VALUES (:id,:order,:product,:sku,:price,:quote,:product_code,"
                ":sku_code,:product_name,:sku_name,:product_type,:fulfillment,1,:amount,:amount,0,:amount,"
                "'{\"fixture\"\\:true}'::jsonb,'[]'::jsonb) ON CONFLICT (pricing_quote_id) DO UPDATE SET "
                "product_name_snapshot=EXCLUDED.product_name_snapshot,sku_name_snapshot=EXCLUDED.sku_name_snapshot"
            ),
            {
                "id": order_item_id,
                "order": order_id,
                "product": row["product_id"],
                "sku": row["sku_id"],
                "price": row["price_id"],
                "quote": quote_id,
                "product_code": row["product_code"],
                "sku_code": row["sku_code"],
                "product_name": row["product_name"],
                "sku_name": row["sku_name"],
                "product_type": row["product_type"],
                "fulfillment": row["fulfillment_type"],
                "amount": amount,
            },
        )
        await session.execute(
            text(
                "INSERT INTO order_status_history "
                "(id,order_id,from_status,to_status,reason_code,reason,actor_type,actor_user_id,metadata,created_at) "
                "VALUES (:id,:order,'draft',:status,'test_showcase','Synthetic display history','system',:user,"
                "'{\"fixture\"\\:true}'::jsonb,:created) ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": _id(f"order-history:{index}"),
                "order": order_id,
                "status": status,
                "user": user_id,
                "created": placed_at,
            },
        )
        entitlement_type = (
            "course_access"
            if row["product_type"] == "course"
            else "activity_admission"
            if row["product_type"] == "activity_ticket"
            else "counseling_credits"
        )
        entitlement_status = "active" if status in {"paid", "fulfilled"} else "revoked"
        await session.execute(
            text(
                "INSERT INTO entitlements "
                "(id,user_id,order_id,order_item_id,entitlement_type,status,resource_type,resource_id,quantity_granted,"
                "quantity_consumed,starts_at,expires_at,configuration_snapshot,activated_at,revoked_at,revoke_reason) "
                "VALUES (:id,:user,:order,:item,:type,:status,:resource_type,:resource,1,0,"
                "CAST(:starts AS timestamptz),CAST(:starts AS timestamptz)+interval '365 days',"
                "'{\"fixture\"\\:true}'::jsonb,CAST(:starts AS timestamptz),"
                "CASE WHEN CAST(:status AS varchar)='revoked' THEN CAST(:starts AS timestamptz) ELSE NULL END,"
                "CASE WHEN CAST(:status AS varchar)='revoked' THEN 'order_cancelled' ELSE NULL END) "
                "ON CONFLICT (order_item_id,entitlement_type) DO UPDATE SET status=EXCLUDED.status,"
                "revoked_at=EXCLUDED.revoked_at,revoke_reason=EXCLUDED.revoke_reason,updated_at=now()"
            ),
            {
                "id": _id(f"entitlement:{index}"),
                "user": user_id,
                "order": order_id,
                "item": order_item_id,
                "type": entitlement_type,
                "status": entitlement_status,
                "resource_type": row["product_type"],
                "resource": row["product_id"],
                "starts": placed_at,
            },
        )
    for index, status in enumerate(("active", "cancelled", "expired"), start=1):
        row = catalog_rows[index - 1]
        await session.execute(
            text(
                "INSERT INTO subscriptions "
                "(id,user_id,sku_id,provider,provider_environment,provider_subscription_id,status,currency_code,"
                "recurring_amount_minor,billing_interval,billing_interval_count,current_period_start,current_period_end,"
                "cancel_at_period_end,cancelled_at,ended_at,latest_order_id) "
                "VALUES (:id,:user,:sku,'fixture','test',:provider_id,:status,:currency,:amount,'month',1,"
                "now()-interval '10 days',now()+interval '20 days',:cancel_at,"
                "CASE WHEN CAST(:status AS varchar)='cancelled' THEN now()-interval '5 days' ELSE NULL END,"
                "CASE WHEN CAST(:status AS varchar) IN ('cancelled','expired') THEN now()-interval '5 days' ELSE NULL END,:order) "
                "ON CONFLICT (provider,provider_environment,provider_subscription_id) DO UPDATE SET status=EXCLUDED.status,"
                "cancel_at_period_end=EXCLUDED.cancel_at_period_end,updated_at=now()"
            ),
            {
                "id": _id(f"subscription:{index}"),
                "user": user_id,
                "sku": row["sku_id"],
                "provider_id": f"{SHOWCASE_PREFIX}-subscription-{index}",
                "status": status,
                "currency": row["currency_code"],
                "amount": int(row["unit_amount_minor"]),
                "cancel_at": status == "cancelled",
                "order": _id(f"order:{index}"),
            },
        )


async def _seed_membership(session: AsyncSession, user_id: UUID) -> None:
    await membership_projection.ensure_free_membership(session, user_id, commit=False)
    current = (
        (
            await session.execute(
                text(
                    "SELECT a.id,a.membership_plan_id,a.membership_plan_version_id FROM membership_accounts a "
                    "WHERE a.user_id=:user AND a.source_type='free_default' AND a.status='active'"
                ),
                {"user": user_id},
            )
        )
        .mappings()
        .one()
    )
    for index, (benefit_code, allocated, consumed) in enumerate(
        (
            ("ai.message_quota", 10, 3),
            ("recommendation.daily_received_limit", 12, 4),
            ("counseling.booking_access", 3, 1),
        ),
        start=1,
    ):
        await session.execute(
            text(
                "INSERT INTO membership_quota_buckets "
                "(id,membership_account_id,membership_cycle_id,benefit_code,period_type,period_starts_at,period_ends_at,"
                "allocated_quantity,consumed_quantity,reserved_quantity,rollover_quantity,status) "
                "VALUES (:id,:account,NULL,:benefit,'calendar_month',date_trunc('month',now()),"
                "date_trunc('month',now())+interval '1 month',:allocated,:consumed,0,0,'active') "
                "ON CONFLICT (membership_account_id,benefit_code,period_starts_at) DO UPDATE SET "
                "allocated_quantity=EXCLUDED.allocated_quantity,consumed_quantity=EXCLUDED.consumed_quantity,status='active',updated_at=now()"
            ),
            {
                "id": _id(f"membership-quota:{index}"),
                "account": current["id"],
                "benefit": benefit_code,
                "allocated": allocated,
                "consumed": consumed,
            },
        )
    for index in range(1, 4):
        starts = datetime.now(UTC) - timedelta(days=365 * index)
        expires = starts + timedelta(days=120)
        await session.execute(
            text(
                "INSERT INTO membership_accounts "
                "(id,user_id,membership_plan_id,membership_plan_version_id,status,source_type,starts_at,expires_at,cancel_at_period_end) "
                "VALUES (:id,:user,:plan,:version,'expired','admin_grant',:starts,:expires,false) "
                "ON CONFLICT (id) DO UPDATE SET status='expired',expires_at=EXCLUDED.expires_at,updated_at=now()"
            ),
            {
                "id": _id(f"membership-history:{index}"),
                "user": user_id,
                "plan": current["membership_plan_id"],
                "version": current["membership_plan_version_id"],
                "starts": starts,
                "expires": expires,
            },
        )


async def _seed_dating_profile(session: AsyncSession, user_id: UUID) -> UUID:
    release_id = await session.scalar(
        text(
            "SELECT id FROM dating_profile_schema_releases "
            "WHERE schema_code='vav-dating-profile' AND status='active'"
        )
    )
    if release_id is None:
        raise RuntimeError("The active dating-profile schema is missing.")
    profile_id = await session.scalar(
        text("SELECT id FROM dating_profiles WHERE user_id=:user"), {"user": user_id}
    )
    if profile_id is None:
        profile_id = _id("dating-profile")
        await session.execute(
            text(
                "INSERT INTO dating_profiles "
                "(id,user_id,profile_number,status,review_status,schema_release_id,default_locale,relationship_intent,current_city_code) "
                "VALUES (:id,:user,'VAV-TEST-0001','draft','not_required',:release,'zh-CN','marriage_oriented','shanghai')"
            ),
            {"id": profile_id, "user": user_id, "release": release_id},
        )
    for table in (
        "dating_profile_core_details",
        "dating_profile_faith_details",
        "dating_profile_relationship_history",
        "dating_profile_family_details",
        "dating_profile_lifestyle_details",
    ):
        await session.execute(
            text(f"INSERT INTO {table} (dating_profile_id) VALUES (:id) ON CONFLICT DO NOTHING"),
            {"id": profile_id},
        )
    await session.execute(
        text(
            "UPDATE dating_profile_core_details SET gender_code='female',eligible_partner_gender_codes='[\"male\"]'::jsonb,"
            "age_display_mode='exact_age',country_code='CN',region_code='east',city_code='shanghai',"
            "primary_language_codes='[\"zh-CN\",\"en\"]'::jsonb,relocation_willingness='same_country',"
            "education_level_code='bachelor',occupation_category_code='technology',updated_at=now() WHERE dating_profile_id=:id"
        ),
        {"id": profile_id},
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
            "UPDATE dating_profile_relationship_history SET marital_status_code='never_married',has_children=false,updated_at=now() "
            "WHERE dating_profile_id=:id"
        ),
        {"id": profile_id},
    )
    await session.execute(
        text(
            "UPDATE dating_profile_family_details SET desire_children_code='want_children',updated_at=now() WHERE dating_profile_id=:id"
        ),
        {"id": profile_id},
    )
    await session.execute(
        text(
            "UPDATE dating_profile_lifestyle_details SET daily_schedule_code='standard',smoking_status_code='never',"
            'alcohol_use_code=\'never\',leisure_interest_codes=\'["reading","music","hiking"]\'::jsonb,'
            'communication_preference_codes=\'["messaging","voice_call"]\'::jsonb,updated_at=now() WHERE dating_profile_id=:id'
        ),
        {"id": profile_id},
    )
    await session.execute(
        text(
            "INSERT INTO dating_profile_narratives "
            "(dating_profile_id,locale,self_introduction,marriage_vision,moderation_status) "
            "VALUES (:id,'zh-CN',:intro,:vision,'approved') ON CONFLICT (dating_profile_id,locale) DO UPDATE SET "
            "self_introduction=EXCLUDED.self_introduction,marriage_vision=EXCLUDED.marriage_vision,moderation_status='approved',updated_at=now()"
        ),
        {
            "id": profile_id,
            "intro": "喜欢阅读、音乐和城市漫步，也重视诚实、尊重与持续成长。希望通过真实交流慢慢认识彼此。",
            "vision": "期待在共同信仰、清晰沟通与彼此支持中建立稳定的长期关系。",
        },
    )
    fixture = {
        "key": "test-showcase",
        "display_name": "Test 用户",
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
        "age_range": {"minimum": 27, "maximum": 42},
    }
    await _ensure_photo(session, profile_id=profile_id, user_id=user_id, key="test-showcase")
    for index in (2, 3):
        checksum = hashlib.sha256(f"{SHOWCASE_PREFIX}:dating-photo:{index}".encode()).hexdigest()
        media_id = _id(f"dating-photo-media:{index}")
        await session.execute(
            text(
                "INSERT INTO media_assets "
                "(id,storage_provider,bucket_name,object_key,original_filename,media_type,mime_type,byte_size,width,height,"
                "checksum_sha256,visibility,processing_status,uploaded_by) VALUES (:id,'minio','vav-private',:key,:filename,"
                "'image','image/jpeg',2048,800,800,:checksum,'private','ready',:user) "
                "ON CONFLICT (object_key) DO UPDATE SET updated_at=now()"
            ),
            {
                "id": media_id,
                "key": f"fixtures/test-showcase/profile-{index}.jpg",
                "filename": f"test-showcase-{index}.jpg",
                "checksum": checksum,
                "user": user_id,
            },
        )
        await session.execute(
            text(
                "INSERT INTO dating_profile_photos "
                "(id,dating_profile_id,media_asset_id,photo_role,status,visibility,sort_order,content_checksum_sha256,reviewed_at) "
                "VALUES (:id,:profile,:media,'gallery','approved','verified_members',:sort,:checksum,now()) "
                "ON CONFLICT (id) DO UPDATE SET status='approved',deleted_at=NULL,updated_at=now()"
            ),
            {
                "id": _id(f"dating-photo:{index}"),
                "profile": profile_id,
                "media": media_id,
                "sort": index - 1,
                "checksum": checksum,
            },
        )
    await session.execute(
        text(
            "INSERT INTO partner_preference_profiles (user_id,dating_profile_id,schema_release_id,status) "
            "VALUES (:user,:profile,:release,'confirmed') ON CONFLICT (dating_profile_id) DO UPDATE SET status='confirmed',updated_at=now()"
        ),
        {"user": user_id, "profile": profile_id, "release": release_id},
    )
    preference_id = await session.scalar(
        text("SELECT id FROM partner_preference_profiles WHERE dating_profile_id=:profile"),
        {"profile": profile_id},
    )
    criteria = (
        ("age_range", "range", {"minimum": 27, "maximum": 42}, "required", True),
        (
            "faith_status_code",
            "in",
            ["believer_baptized", "believer_not_baptized"],
            "very_important",
            False,
        ),
        (
            "leisure_interest_codes",
            "contains_any",
            ["reading", "music", "hiking"],
            "nice_to_have",
            False,
        ),
    )
    for criterion_code, operator, desired_value, importance, hard_constraint in criteria:
        await session.execute(
            text(
                "INSERT INTO partner_preference_criteria "
                "(partner_preference_profile_id,criterion_code,operator,desired_value,importance,hard_constraint) "
                "VALUES (:profile,:code,:operator,CAST(:value AS jsonb),:importance,:hard) "
                "ON CONFLICT (partner_preference_profile_id,criterion_code) DO UPDATE SET operator=EXCLUDED.operator,"
                "desired_value=EXCLUDED.desired_value,importance=EXCLUDED.importance,hard_constraint=EXCLUDED.hard_constraint"
            ),
            {
                "profile": preference_id,
                "code": criterion_code,
                "operator": operator,
                "value": _json(desired_value),
                "importance": importance,
                "hard": hard_constraint,
            },
        )
    await _approve_version(session, profile_id=profile_id, user_id=user_id, fixture=fixture)
    await session.execute(
        text(
            "UPDATE dating_profiles SET completeness_basis_points=9500,status='active',review_status='approved',"
            "approved_version_number=1,current_version_number=1,updated_at=now() WHERE id=:id"
        ),
        {"id": profile_id},
    )
    return cast(UUID, profile_id)


async def _seed_recommendations(session: AsyncSession, user_id: UUID, profile_id: UUID) -> None:
    await rebuild_projection(session, profile_id)
    await recommendation_service.rebuild_pool_entry(session, user_id)
    await session.execute(
        text(
            "INSERT INTO recommendation_user_settings "
            "(user_id,recommendations_paused,daily_received_limit,delivery_frequency,extended_recommendations_enabled,"
            "relaxable_criteria,preferred_locale) VALUES (:user,false,6,'daily',true,"
            "'[\"city_code\",\"age_range\"]'::jsonb,'zh-CN') ON CONFLICT (user_id) DO UPDATE SET "
            "recommendations_paused=false,daily_received_limit=6,extended_recommendations_enabled=true,updated_at=now()"
        ),
        {"user": user_id},
    )
    await session.execute(
        text(
            "INSERT INTO recommendation_user_tuning_profiles "
            "(user_id,feature_weight_adjustments,exploration_level,feedback_personalization_enabled) "
            "VALUES (:user,'{\"shared_interests\"\\:15,\"location\"\\:10}'::jsonb,'balanced',true) "
            "ON CONFLICT (user_id) DO UPDATE SET feature_weight_adjustments=EXCLUDED.feature_weight_adjustments,"
            "exploration_level='balanced',feedback_personalization_enabled=true,updated_at=now()"
        ),
        {"user": user_id},
    )
    try:
        await recommendation_batches.generate_batch(session, user_id, requested_size=3)
    except VavError as error:
        if error.code not in {"RECOMMENDATION_DAILY_LIMIT_REACHED"}:
            raise
    batch = (
        (
            await session.execute(
                text(
                    "SELECT * FROM recommendation_batches WHERE user_id=:user AND status='active' "
                    "ORDER BY batch_number DESC LIMIT 1"
                ),
                {"user": user_id},
            )
        )
        .mappings()
        .first()
    )
    if batch is None:
        raise RuntimeError("The test account recommendation batch was not created.")
    target_emails = (
        "recommendation-fixture-jonathan@example.com",
        "recommendation-fixture-daniel@example.com",
        "recommendation-fixture-peter@example.com",
    )
    candidates = list(
        (
            await session.execute(
                text(
                    "SELECT u.id AS user_id,p.id AS pair_id,p.viewer_score,p.candidate_score,p.combined_score,p.confidence FROM users u "
                    "JOIN recommendation_pool_entries pool ON pool.user_id=u.id AND pool.eligible=true "
                    "JOIN LATERAL (SELECT cp.id,"
                    "CASE WHEN cp.user_low_id=:viewer THEN (cp.score_snapshot->>'user_a_to_b_score_bps')::integer "
                    "ELSE (cp.score_snapshot->>'user_b_to_a_score_bps')::integer END AS viewer_score,"
                    "CASE WHEN cp.user_low_id=:viewer THEN (cp.score_snapshot->>'user_b_to_a_score_bps')::integer "
                    "ELSE (cp.score_snapshot->>'user_a_to_b_score_bps')::integer END AS candidate_score,"
                    "(cp.score_snapshot->>'combined_score_bps')::integer AS combined_score,"
                    "(cp.score_snapshot->>'confidence_bps')::integer AS confidence "
                    "FROM recommendation_candidate_pairs cp "
                    "WHERE ((cp.user_low_id=:viewer AND cp.user_high_id=u.id) OR "
                    "(cp.user_high_id=:viewer AND cp.user_low_id=u.id)) AND cp.status='eligible' "
                    "AND cp.score_snapshot IS NOT NULL "
                    "ORDER BY cp.generated_at DESC LIMIT 1) p ON true "
                    "WHERE u.email=ANY(CAST(:emails AS citext[])) "
                    "ORDER BY array_position(CAST(:emails AS citext[]),u.email)"
                ),
                {"viewer": user_id, "emails": list(target_emails)},
            )
        ).mappings()
    )
    for candidate in candidates:
        existing = await session.scalar(
            text(
                "SELECT id FROM recommendation_items WHERE recommendation_batch_id=:batch "
                "AND recommended_user_id=:candidate"
            ),
            {"batch": batch["id"], "candidate": candidate["user_id"]},
        )
        if existing is not None:
            await session.execute(
                text(
                    "UPDATE recommendation_items SET status='ready',available_from=now(),expires_at=:expires,"
                    "exposed_at=NULL,viewed_at=NULL,invalidated_at=NULL,invalidation_reason=NULL "
                    "WHERE id=:id"
                ),
                {"id": existing, "expires": batch["expires_at"]},
            )
            continue
        current_size = int(
            await session.scalar(
                text(
                    "SELECT count(*) FROM recommendation_items WHERE recommendation_batch_id=:batch "
                    "AND status IN ('ready','exposed','viewed')"
                ),
                {"batch": batch["id"]},
            )
            or 0
        )
        if current_size >= 3:
            break
        candidate_entry = await recommendation_service.pool_entry(
            session, cast(UUID, candidate["user_id"])
        )
        if candidate_entry is None:
            continue
        visible = await recommendation_batches._visible_snapshot(
            session,
            viewer_id=user_id,
            candidate_user_id=cast(UUID, candidate["user_id"]),
        )
        await session.execute(
            text(
                "INSERT INTO recommendation_items "
                "(id,recommendation_batch_id,viewer_user_id,recommended_user_id,candidate_pair_id,"
                "candidate_projection_version,candidate_privacy_version,rank_position,viewer_to_candidate_score_bps,"
                "candidate_to_viewer_score_bps,bidirectional_score_bps,confidence_bps,explanation_snapshot,"
                "visible_profile_snapshot,status,available_from,expires_at) "
                "VALUES (:id,:batch,:viewer,:candidate,:pair,:projection,:privacy,:rank,:viewer_score,:candidate_score,"
                ":combined_score,:confidence,"
                "CAST(:explanation AS jsonb),CAST(:visible AS jsonb),'ready',now(),:expires) "
                "ON CONFLICT (recommendation_batch_id,recommended_user_id) DO NOTHING"
            ),
            {
                "id": _id(f"recommendation-item:{candidate['user_id']}"),
                "batch": batch["id"],
                "viewer": user_id,
                "candidate": candidate["user_id"],
                "pair": candidate["pair_id"],
                "projection": candidate_entry["profile_projection_version"],
                "privacy": candidate_entry["privacy_settings_version"],
                "rank": current_size + 1,
                "viewer_score": candidate["viewer_score"],
                "candidate_score": candidate["candidate_score"],
                "combined_score": candidate["combined_score"],
                "confidence": candidate["confidence"],
                "explanation": _json(
                    {
                        "summary": "这位成员符合你设置的基本条件，建议通过交流进一步了解。",
                        "mutual_strengths": [],
                        "relevant_preferences": [],
                        "topics_to_explore": [
                            {
                                "explanation_code": "showcase_conversation",
                                "display_text": "可以从共同兴趣与生活节奏开始交流",
                            }
                        ],
                        "information_gaps": [],
                        "caveat": "推荐仅用于帮助发现可能适合认识的人，不代表结果或承诺。",
                        "relaxation_notices": [],
                        "explanation_policy_version": "1.0.0",
                    }
                ),
                "visible": _json(visible),
                "expires": batch["expires_at"],
            },
        )
    generated_size = int(
        await session.scalar(
            text("SELECT count(*) FROM recommendation_items WHERE recommendation_batch_id=:batch"),
            {"batch": batch["id"]},
        )
        or 0
    )
    await session.execute(
        text("UPDATE recommendation_batches SET generated_size=:size WHERE id=:batch"),
        {"size": generated_size, "batch": batch["id"]},
    )
    for index in range(1, 3):
        await session.execute(
            text(
                "INSERT INTO recommendation_batches "
                "(id,user_id,batch_number,batch_type,strategy_id,profile_projection_version,preference_version,"
                "privacy_settings_version,status,requested_size,generated_size,ranking_seed,period_key,idempotency_key,"
                "generated_at,activated_at,expires_at,generation_report,created_at) "
                "VALUES (:id,:user,:number,'daily',:strategy,:projection,:preference,:privacy,'expired',3,3,:seed,:period,:key,"
                "now()-CAST(:days AS integer)*interval '1 day',now()-CAST(:days AS integer)*interval '1 day',"
                "now()-CAST(:expired_days AS integer)*interval '1 day','{\"fixture\"\\:true}'::jsonb,"
                "now()-CAST(:days AS integer)*interval '1 day') "
                "ON CONFLICT (user_id,idempotency_key) DO UPDATE SET status='expired',generated_size=3,"
                "expires_at=EXCLUDED.expires_at"
            ),
            {
                "id": _id(f"recommendation-history-batch:{index}"),
                "user": user_id,
                "number": 800000 + index,
                "strategy": batch["strategy_id"],
                "projection": batch["profile_projection_version"],
                "preference": batch["preference_version"],
                "privacy": batch["privacy_settings_version"],
                "seed": f"{SHOWCASE_PREFIX}:history:{index}",
                "period": f"test-showcase-history-{index}",
                "key": f"{SHOWCASE_PREFIX}:history:{index}",
                "days": 14 + index * 14,
                "expired_days": 7 + index * 14,
            },
        )


def _canonical_pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    return (first, second) if str(first) < str(second) else (second, first)


async def _seed_matchmaking_and_relationships(session: AsyncSession, user_id: UUID) -> None:
    target_emails = (
        "recommendation-fixture-jonathan@example.com",
        "recommendation-fixture-daniel@example.com",
        "recommendation-fixture-peter@example.com",
    )
    targets = list(
        (
            await session.execute(
                text(
                    "SELECT id,email FROM users WHERE email=ANY(CAST(:emails AS citext[])) "
                    "ORDER BY array_position(CAST(:emails AS citext[]),email)"
                ),
                {"emails": list(target_emails)},
            )
        ).mappings()
    )
    if len(targets) != 3:
        raise RuntimeError("Three recommendation fixture members are required for matchmaking.")
    checkin_definition_id = await session.scalar(
        text(
            "SELECT id FROM relationship_checkin_definitions WHERE status='active' "
            "ORDER BY activated_at DESC NULLS LAST LIMIT 1"
        )
    )
    for index, target in enumerate(targets, start=1):
        target_id = target["id"]
        target_contact_id = _id(f"match-target-contact:{index}")
        target_email = str(target["email"])
        await session.execute(
            text(
                "INSERT INTO user_contact_points "
                "(id,user_id,contact_type,value_encrypted,value_hmac,status,verified_at,is_primary,visibility) "
                "VALUES (:id,:user,'email',:value,:hmac,'verified',now(),true,'mutual_matches') "
                "ON CONFLICT (id) DO UPDATE SET value_encrypted=EXCLUDED.value_encrypted,value_hmac=EXCLUDED.value_hmac,"
                "status='verified',visibility='mutual_matches',updated_at=now()"
            ),
            {
                "id": target_contact_id,
                "user": target_id,
                "value": encrypt_private(target_email),
                "hmac": searchable_hmac(target_email),
            },
        )
        low, high = _canonical_pair(user_id, target_id)
        pair_id = _id(f"matchmaking-pair:{index}")
        await session.execute(
            text(
                "INSERT INTO matchmaking_pairs (id,user_low_id,user_high_id,status,pair_version) "
                "VALUES (:id,:low,:high,'interacting',1) ON CONFLICT (user_low_id,user_high_id) DO UPDATE SET "
                "status='interacting',pair_version=matchmaking_pairs.pair_version+1,updated_at=now()"
            ),
            {"id": pair_id, "low": low, "high": high},
        )
        pair_id = await session.scalar(
            text("SELECT id FROM matchmaking_pairs WHERE user_low_id=:low AND user_high_id=:high"),
            {"low": low, "high": high},
        )
        if pair_id is None:
            raise RuntimeError("Matchmaking pair could not be created.")
        user_like_id = _id(f"matchmaking-like:user:{index}")
        target_like_id = _id(f"matchmaking-like:target:{index}")
        for like_id, actor, target_user, direction in (
            (user_like_id, user_id, target_id, "user"),
            (target_like_id, target_id, user_id, "target"),
        ):
            await session.execute(
                text(
                    "INSERT INTO matchmaking_likes "
                    "(id,pair_id,actor_user_id,target_user_id,source,status,idempotency_key,matched_at) "
                    "VALUES (:id,:pair,:actor,:target,'recommendation','matched',:key,"
                    "now()-CAST(:days AS integer)*interval '1 day') "
                    "ON CONFLICT (actor_user_id,idempotency_key) DO UPDATE SET status='matched',matched_at=EXCLUDED.matched_at,"
                    "withdrawn_at=NULL,invalidated_at=NULL"
                ),
                {
                    "id": like_id,
                    "pair": pair_id,
                    "actor": actor,
                    "target": target_user,
                    "key": f"{SHOWCASE_PREFIX}:like:{index}:{direction}",
                    "days": index * 3,
                },
            )
        match_id = _id(f"mutual-match:{index}")
        await session.execute(
            text(
                "INSERT INTO matchmaking_mutual_matches "
                "(id,match_number,pair_id,user_low_id,user_high_id,source,low_to_high_like_id,high_to_low_like_id,status,matched_at) "
                "VALUES (:id,:number,:pair,:low,:high,'recommendation',:low_like,:high_like,'active',"
                "now()-CAST(:days AS integer)*interval '1 day') ON CONFLICT (pair_id) DO UPDATE SET status='active',closed_at=NULL,"
                "invalidated_at=NULL,updated_at=now()"
            ),
            {
                "id": match_id,
                "number": f"MATCH-TEST-{index:03d}",
                "pair": pair_id,
                "low": low,
                "high": high,
                "low_like": user_like_id if low == user_id else target_like_id,
                "high_like": target_like_id if high == target_id else user_like_id,
                "days": index * 3,
            },
        )
        match_id = await session.scalar(
            text("SELECT id FROM matchmaking_mutual_matches WHERE pair_id=:pair"),
            {"pair": pair_id},
        )
        await session.execute(
            text(
                "UPDATE matchmaking_pairs SET status='matched',active_mutual_match_id=:match,updated_at=now() WHERE id=:pair"
            ),
            {"match": match_id, "pair": pair_id},
        )
        accepted = True
        sender = target_id if index in {1, 3} else user_id
        recipient = user_id if sender == target_id else target_id
        invitation_id = _id(f"matchmaking-invitation:{index}")
        handoff_id = _id(f"relationship-handoff:{index}") if accepted else None
        await session.execute(
            text(
                "INSERT INTO matchmaking_introduction_invitations "
                "(id,invitation_number,mutual_match_id,pair_id,sender_user_id,recipient_user_id,status,invitation_version,"
                "message_encrypted,message_screening,policy_snapshot,idempotency_key,sent_at,expires_at,accepted_at,relationship_handoff_id) "
                "VALUES (:id,:number,:match,:pair,:sender,:recipient,:status,1,:message,'{\"safe\"\\:true}'::jsonb,"
                "'{\"fixture\"\\:true}'::jsonb,:key,now()-CAST(:days AS integer)*interval '1 day',now()+interval '30 days',"
                "CASE WHEN :accepted THEN now()-CAST(:accepted_days AS integer)*interval '1 day' ELSE NULL END,:handoff) "
                "ON CONFLICT (invitation_number) DO UPDATE SET status=EXCLUDED.status,accepted_at=EXCLUDED.accepted_at,"
                "relationship_handoff_id=EXCLUDED.relationship_handoff_id,updated_at=now()"
            ),
            {
                "id": invitation_id,
                "number": f"INV-TEST-{index:03d}",
                "match": match_id,
                "pair": pair_id,
                "sender": sender,
                "recipient": recipient,
                "status": "accepted" if accepted else "pending",
                "message": encrypt_private("愿意在平台内继续认识，并一起参加一次轻松的活动吗？"),
                "key": f"{SHOWCASE_PREFIX}:invitation:{index}",
                "days": index * 2,
                "accepted": accepted,
                "accepted_days": index,
                "handoff": handoff_id,
            },
        )
        if not accepted:
            continue
        journey_id = _id(f"relationship-journey:{index}")
        await session.execute(
            text(
                "INSERT INTO relationship_journeys "
                "(id,journey_number,matchmaking_pair_id,mutual_match_id,introduction_invitation_id,relationship_handoff_id,"
                "user_low_id,user_high_id,status,current_stage_code,started_at) "
                "VALUES (:id,:number,:pair,:match,:invitation,:handoff,:low,:high,'active',:stage,"
                "now()-CAST(:days AS integer)*interval '1 day') ON CONFLICT (journey_number) DO UPDATE SET status='active',"
                "current_stage_code=EXCLUDED.current_stage_code,updated_at=now()"
            ),
            {
                "id": journey_id,
                "number": f"REL-TEST-{index:03d}",
                "pair": pair_id,
                "match": match_id,
                "invitation": invitation_id,
                "handoff": handoff_id,
                "low": low,
                "high": high,
                "stage": "getting_to_know" if index == 1 else "introduction_accepted",
                "days": 14 - index * 2,
            },
        )
        await session.execute(
            text(
                "UPDATE matchmaking_introduction_invitations SET relationship_handoff_id=:handoff WHERE id=:invitation"
            ),
            {"handoff": handoff_id, "invitation": invitation_id},
        )
        for history_index, (event_type, from_stage, to_stage) in enumerate(
            (
                ("relationship_started", None, "introduction_accepted"),
                ("stage_changed", "introduction_accepted", "getting_to_know"),
                ("milestone_created", "getting_to_know", "getting_to_know"),
            ),
            start=1,
        ):
            await session.execute(
                text(
                    "INSERT INTO relationship_status_history "
                    "(id,journey_id,actor_user_id,event_type,from_status,to_status,from_stage_code,to_stage_code,reason_code,"
                    "safe_metadata,occurred_at) VALUES (:id,:journey,:user,:event,'active','active',:from_stage,:to_stage,"
                    "'test_showcase','{\"fixture\"\\:true}'::jsonb,now()-CAST(:days AS integer)*interval '1 day') "
                    "ON CONFLICT (id) DO UPDATE SET event_type=EXCLUDED.event_type,from_stage_code=EXCLUDED.from_stage_code,"
                    "to_stage_code=EXCLUDED.to_stage_code,occurred_at=EXCLUDED.occurred_at"
                ),
                {
                    "id": _id(f"relationship-history:{index}:{history_index}"),
                    "journey": journey_id,
                    "user": user_id,
                    "event": event_type,
                    "from_stage": from_stage,
                    "to_stage": to_stage,
                    "days": 15 - history_index * 3,
                },
            )
        for participant_index, participant_user in enumerate((user_id, target_id), start=1):
            await session.execute(
                text(
                    "INSERT INTO relationship_participants "
                    "(id,journey_id,user_id,status,personal_state,notification_preferences,last_acknowledged_stage_code) "
                    "VALUES (:id,:journey,:user,'active','participating','{\"reminders\"\\:true}'::jsonb,:stage) "
                    "ON CONFLICT (journey_id,user_id) DO UPDATE SET status='active',personal_state='participating',updated_at=now()"
                ),
                {
                    "id": _id(f"relationship-participant:{index}:{participant_index}"),
                    "journey": journey_id,
                    "user": participant_user,
                    "stage": "getting_to_know" if index == 1 else "introduction_accepted",
                },
            )
        milestones = (
            ("introduction", "接受平台介绍", 12),
            ("conversation", "完成第一次深入交流", 8),
            ("shared_activity", "一起参加成长活动", 3),
        )
        for milestone_index, (milestone_type, title, days_ago) in enumerate(milestones, start=1):
            await session.execute(
                text(
                    "INSERT INTO relationship_milestones "
                    "(id,journey_id,created_by_user_id,milestone_type,title,description_encrypted,visibility,occurred_on,status) "
                    "VALUES (:id,:journey,:user,:type,:title,:description,'shared',:occurred,'active') "
                    "ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title,description_encrypted=EXCLUDED.description_encrypted,"
                    "status='active',deleted_at=NULL,updated_at=now()"
                ),
                {
                    "id": _id(f"relationship-milestone:{index}:{milestone_index}"),
                    "journey": journey_id,
                    "user": user_id,
                    "type": milestone_type,
                    "title": title,
                    "description": encrypt_private(f"{title}，这是 test 展示账户的合成记录。"),
                    "occurred": date.today() - timedelta(days=days_ago),
                },
            )
        for checkin_index in range(1, 4):
            checkin_id = _id(f"relationship-checkin:{index}:{checkin_index}")
            await session.execute(
                text(
                    "INSERT INTO relationship_checkins "
                    "(id,journey_id,definition_id,initiated_by_user_id,visibility,status,scheduled_for,completed_at) "
                    "VALUES (:id,:journey,:definition,:user,'shared','completed',"
                    "now()-CAST(:days AS integer)*interval '1 day',now()-CAST(:days AS integer)*interval '1 day') "
                    "ON CONFLICT (id) DO UPDATE SET status='completed',updated_at=now()"
                ),
                {
                    "id": checkin_id,
                    "journey": journey_id,
                    "definition": checkin_definition_id,
                    "user": user_id,
                    "days": checkin_index * 2,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO relationship_checkin_responses "
                    "(id,checkin_id,respondent_user_id,response_encrypted) VALUES (:id,:checkin,:user,:response) "
                    "ON CONFLICT (checkin_id,respondent_user_id) DO UPDATE SET response_encrypted=EXCLUDED.response_encrypted,updated_at=now()"
                ),
                {
                    "id": _id(f"relationship-checkin-response:{index}:{checkin_index}"),
                    "checkin": checkin_id,
                    "user": user_id,
                    "response": encrypt_private(
                        {"connection": 4, "communication": 4, "next_step": "安排一次共同活动"}
                    ),
                },
            )
        for reflection_index, reflection in enumerate(
            (
                "这次交流中，我更清楚地表达了自己的需要。",
                "我欣赏对方愿意倾听并提出具体问题。",
                "下一步想保持轻松、稳定而不过度急促的节奏。",
            ),
            start=1,
        ):
            await session.execute(
                text(
                    "INSERT INTO relationship_reflections "
                    "(id,journey_id,author_user_id,reflection_encrypted,status) VALUES (:id,:journey,:user,:reflection,'active') "
                    "ON CONFLICT (id) DO UPDATE SET reflection_encrypted=EXCLUDED.reflection_encrypted,status='active',deleted_at=NULL,updated_at=now()"
                ),
                {
                    "id": _id(f"relationship-reflection:{index}:{reflection_index}"),
                    "journey": journey_id,
                    "user": user_id,
                    "reflection": encrypt_private(reflection),
                },
            )
        contact_request_id = _id(f"contact-exchange:{index}")
        own_contact = _id("contact:email")
        await session.execute(
            text(
                "INSERT INTO matchmaking_contact_exchange_requests "
                "(id,mutual_match_id,invitation_id,pair_id,requested_by_user_id,status,policy_version,policy,consent_version,activated_at) "
                "VALUES (:id,:match,:invitation,:pair,:user,'active','1.0.0','mutual_confirmation_required',1,now()) "
                "ON CONFLICT (mutual_match_id) DO UPDATE SET status='active',activated_at=now(),updated_at=now()"
            ),
            {
                "id": contact_request_id,
                "match": match_id,
                "invitation": invitation_id,
                "pair": pair_id,
                "user": user_id,
            },
        )
        for consent_index, (owner, contact_id) in enumerate(
            ((user_id, own_contact), (target_id, target_contact_id)), start=1
        ):
            await session.execute(
                text(
                    "INSERT INTO matchmaking_contact_exchange_consents "
                    "(id,contact_exchange_request_id,user_id,status,selected_contact_point_ids,contact_point_hash_snapshot,"
                    "platform_only_preferred,consented_at) VALUES (:id,:request,:user,'granted',CAST(:contacts AS jsonb),"
                    "CAST(:snapshot AS jsonb),false,now()) ON CONFLICT (contact_exchange_request_id,user_id) DO UPDATE SET "
                    "status='granted',selected_contact_point_ids=EXCLUDED.selected_contact_point_ids,consented_at=now(),updated_at=now()"
                ),
                {
                    "id": _id(f"contact-consent:{index}:{consent_index}"),
                    "request": contact_request_id,
                    "user": owner,
                    "contacts": _json([str(contact_id)]),
                    "snapshot": _json({str(contact_id): "test-showcase"}),
                },
            )
        for grant_index, (viewer, owner, contact_id) in enumerate(
            ((user_id, target_id, target_contact_id), (target_id, user_id, own_contact)), start=1
        ):
            await session.execute(
                text(
                    "INSERT INTO matchmaking_contact_exchange_grants "
                    "(id,contact_exchange_request_id,viewer_user_id,owner_user_id,contact_point_ids,contact_hash_snapshot,status,granted_at) "
                    "VALUES (:id,:request,:viewer,:owner,CAST(:contacts AS jsonb),CAST(:snapshot AS jsonb),'active',now()) "
                    "ON CONFLICT (contact_exchange_request_id,viewer_user_id,owner_user_id) DO UPDATE SET "
                    "contact_point_ids=EXCLUDED.contact_point_ids,status='active',revoked_at=NULL,suspended_at=NULL"
                ),
                {
                    "id": _id(f"contact-grant:{index}:{grant_index}"),
                    "request": contact_request_id,
                    "viewer": viewer,
                    "owner": owner,
                    "contacts": _json([str(contact_id)]),
                    "snapshot": _json({str(contact_id): "test-showcase"}),
                },
            )
    skip_emails = (
        "recommendation-fixture-hannah@example.com",
        "recommendation-fixture-mei@example.com",
        "recommendation-fixture-grace@example.com",
    )
    skipped_targets = list(
        (
            await session.execute(
                text(
                    "SELECT id,email FROM users WHERE email=ANY(CAST(:emails AS citext[])) "
                    "ORDER BY array_position(CAST(:emails AS citext[]),email)"
                ),
                {"emails": list(skip_emails)},
            )
        ).mappings()
    )
    if len(skipped_targets) != 3:
        raise RuntimeError("Three skip-history fixture members are required.")
    for index, skipped_target in enumerate(skipped_targets, start=1):
        target_id = cast(UUID, skipped_target["id"])
        low, high = _canonical_pair(user_id, target_id)
        skip_pair_id = _id(f"matchmaking-skip-pair:{index}")
        await session.execute(
            text(
                "INSERT INTO matchmaking_pairs (id,user_low_id,user_high_id,status,pair_version) "
                "VALUES (:id,:low,:high,'interacting',1) ON CONFLICT (user_low_id,user_high_id) DO NOTHING"
            ),
            {"id": skip_pair_id, "low": low, "high": high},
        )
        pair_id = await session.scalar(
            text("SELECT id FROM matchmaking_pairs WHERE user_low_id=:low AND user_high_id=:high"),
            {"low": low, "high": high},
        )
        await session.execute(
            text(
                "INSERT INTO matchmaking_skips "
                "(id,pair_id,actor_user_id,target_user_id,skip_type,reason_code,reason_details_encrypted,status,cooldown_until,"
                "undo_available_until,idempotency_key) VALUES (:id,:pair,:actor,:target,'not_now','timing',:details,'active',"
                "now()+interval '14 days',now()+interval '1 hour',:key) ON CONFLICT (actor_user_id,idempotency_key) DO UPDATE SET "
                "status='active',cooldown_until=EXCLUDED.cooldown_until,withdrawn_at=NULL,expired_at=NULL"
            ),
            {
                "id": _id(f"matchmaking-skip:{index}"),
                "pair": pair_id,
                "actor": user_id,
                "target": target_id,
                "details": encrypt_private("目前希望放慢节奏。"),
                "key": f"{SHOWCASE_PREFIX}:skip:{index}",
            },
        )


async def _seed_safety(session: AsyncSession, user_id: UUID) -> None:
    target_rows = list(
        (
            await session.execute(
                text(
                    "SELECT id,email FROM users WHERE email IN "
                    "('dating-fixture-anna@example.test','dating-fixture-ben@example.test',"
                    "'dating-fixture-clara@example.test') ORDER BY email"
                )
            )
        ).mappings()
    )
    if len(target_rows) != 3:
        raise RuntimeError("Three synthetic safety target accounts are required.")
    categories = ("spam", "privacy_violation", "harassment")
    for index, (target, category) in enumerate(zip(target_rows, categories, strict=True), start=1):
        report_id = _id(f"safety-report:{index}")
        await session.execute(
            text(
                "INSERT INTO safety_reports "
                "(id,report_number,reporter_user_id,reported_user_id,target_type,category,severity_claim,status,"
                "description_encrypted,user_safety_state,block_requested,immediate_danger_claimed,source_context,idempotency_key,"
                "submitted_at,closed_at) VALUES (:id,:number,:reporter,:reported,'user',:category,'low',:status,:description,"
                "'{\"immediate_support_shown\"\\:false}'::jsonb,true,false,'{\"fixture\"\\:true}'::jsonb,:key,"
                "now()-CAST(:days AS integer)*interval '1 day',"
                "CASE WHEN CAST(:status AS varchar)='closed' THEN now()-interval '1 day' ELSE NULL END) "
                "ON CONFLICT (report_number) DO UPDATE SET status=EXCLUDED.status,closed_at=EXCLUDED.closed_at,updated_at=now()"
            ),
            {
                "id": report_id,
                "number": f"SR-TEST-{index:03d}",
                "reporter": user_id,
                "reported": target["id"],
                "category": category,
                "status": "submitted" if index == 1 else "closed",
                "description": encrypt_safety(
                    {"description": "这是 test 展示账户使用的合成安全报告，不对应真实事件。"}
                ),
                "key": f"{SHOWCASE_PREFIX}:safety-report:{index}",
                "days": index * 4,
            },
        )
        await session.execute(
            text(
                "INSERT INTO user_blocks "
                "(id,blocker_user_id,blocked_user_id,status,source,source_report_id,reason_code,private_reason_encrypted) "
                "VALUES (:id,:blocker,:blocked,'active','report',:report,'test_showcase',:reason) "
                "ON CONFLICT (id) DO UPDATE SET status='active',lifted_at=NULL,version=user_blocks.version+1"
            ),
            {
                "id": _id(f"user-block:{index}"),
                "blocker": user_id,
                "blocked": target["id"],
                "report": report_id,
                "reason": encrypt_safety({"reason": "Synthetic test-account block history"}),
            },
        )
        low, high = _canonical_pair(user_id, target["id"])
        await session.execute(
            text(
                "INSERT INTO safety_pair_versions (user_low_id,user_high_id,restriction_version) "
                "VALUES (:low,:high,1) ON CONFLICT (user_low_id,user_high_id) DO UPDATE SET "
                "restriction_version=safety_pair_versions.restriction_version+1,updated_at=now()"
            ),
            {"low": low, "high": high},
        )
    restriction_ids: list[UUID] = []
    for index, (scope, user_message) in enumerate(
        (
            ("identity", "身份资料修改会进入人工复核演示流程。"),
            ("faith", "信仰资料修改会进入人工复核演示流程。"),
            ("photos", "照片修改会进入人工复核演示流程。"),
        ),
        start=1,
    ):
        restriction_id = _id(f"account-restriction:{index}")
        restriction_ids.append(restriction_id)
        await session.execute(
            text(
                "INSERT INTO account_restrictions "
                "(id,user_id,restriction_type,scope_definition,status,source_type,source_reference_id,reason_code,user_message_safe,"
                "internal_reason_encrypted,starts_at,ends_at,appeal_allowed,imposed_by,approved_by) "
                "VALUES (:id,:user,'profile_edit_review_required',CAST(:scope AS jsonb),'active','migration',"
                ":source,'test_showcase_review',:message,:reason,now()-CAST(:days AS integer)*interval '1 day',"
                "now()+interval '20 days',true,NULL,NULL) ON CONFLICT (id) DO UPDATE SET status='active',"
                "scope_definition=EXCLUDED.scope_definition,ends_at=EXCLUDED.ends_at,user_message_safe=EXCLUDED.user_message_safe,updated_at=now()"
            ),
            {
                "id": restriction_id,
                "user": user_id,
                "scope": _json({"profile_fields": scope}),
                "source": _id(f"account-restriction-source:{index}"),
                "message": user_message,
                "reason": encrypt_safety({"reason": "Synthetic showcase restriction"}),
                "days": 8 + index * 2,
            },
        )
    for index, (status, outcome, message) in enumerate(
        (
            ("decided", "modified", "复核后缩小了限制范围。"),
            ("closed", "upheld", "复核确认该演示限制保持不变。"),
            ("decided", "modified", "复核后进一步缩小了演示限制范围。"),
        ),
        start=1,
    ):
        await session.execute(
            text(
                "INSERT INTO safety_appeals "
                "(id,appeal_number,appellant_user_id,restriction_id,status,appeal_reason_encrypted,evidence_manifest,submitted_at,"
                "review_due_at,outcome,outcome_message_safe,internal_review_encrypted,decided_at) "
                "VALUES (:id,:number,:user,:restriction,:status,:reason,'[]'::jsonb,"
                "now()-CAST(:days AS integer)*interval '1 day',"
                "now()+interval '7 days',:outcome,:message,:review,now()-interval '1 day') "
                "ON CONFLICT (appeal_number) DO UPDATE SET status=EXCLUDED.status,outcome=EXCLUDED.outcome,"
                "outcome_message_safe=EXCLUDED.outcome_message_safe,decided_at=EXCLUDED.decided_at,updated_at=now()"
            ),
            {
                "id": _id(f"safety-appeal:{index}"),
                "number": f"SA-TEST-{index:03d}",
                "user": user_id,
                "restriction": restriction_ids[index - 1],
                "status": status,
                "reason": encrypt_safety({"reason": "希望复核展示限制的范围与期限。"}),
                "days": index * 5,
                "outcome": outcome,
                "message": message,
                "review": encrypt_safety({"review": "Synthetic independent review record"}),
            },
        )


async def _coverage_counts(session: AsyncSession, user_id: UUID) -> dict[str, int]:
    queries = {
        "published_pages": "SELECT count(*) FROM content_entries WHERE entry_type='page' AND status='published' "
        "AND canonical_slug IN ('home','about','services','contact','privacy','terms','refund-policy','ai-disclaimer')",
        "articles": "SELECT count(*) FROM content_entries WHERE entry_type='article' AND status='published' "
        "AND canonical_slug LIKE 'test-showcase-%'",
        "stories": "SELECT count(*) FROM content_entries WHERE entry_type='testimonial' AND status='published' "
        "AND canonical_slug LIKE 'test-showcase-%'",
        "contact_points": "SELECT count(*) FROM user_contact_points WHERE user_id=:user "
        "AND id IN (:contact_email,:contact_phone,:contact_wechat)",
        "consents": "SELECT count(*) FROM user_consents WHERE user_id=:user AND id IN (:consent_a,:consent_b,:consent_c)",
        "notifications": "SELECT count(*) FROM user_notifications WHERE user_id=:user AND id IN (:a,:b,:c)",
        "notification_preferences": "SELECT count(*) FROM notification_preferences WHERE user_id=:user "
        "AND id IN (:notification_pref_a,:notification_pref_b,:notification_pref_c)",
        "ai_conversations": "SELECT count(*) FROM ai_conversations WHERE user_id=:user AND conversation_number LIKE 'AI-TEST-%'",
        "privacy_requests": "SELECT count(*) FROM data_subject_requests WHERE user_id=:user AND request_number LIKE 'PRQ-TEST-%'",
        "ai_memories": "SELECT count(*) FROM ai_memory_items WHERE user_id=:user AND source_type='test_showcase'",
        "auth_sessions": "SELECT count(*) FROM auth_sessions WHERE user_id=:user AND audience='user' AND status='active' "
        "AND device_name IN ('Safari · macOS','Chrome · Windows','Mobile Safari · iPhone')",
        "activity_registrations": "SELECT count(*) FROM activity_registrations WHERE user_id=:user AND registration_number LIKE 'REG-TEST-%'",
        "activity_waitlist": "SELECT count(*) FROM activity_waitlist_entries WHERE user_id=:user",
        "activity_participants": "SELECT count(*) FROM activity_participant_profiles p JOIN activities a ON a.id=p.activity_id "
        "WHERE a.activity_code='activity-showcase-walk' AND p.user_id<>:user AND p.visibility_status='visible'",
        "activity_choices": "SELECT count(*) FROM activity_post_event_choices c JOIN activities a ON a.id=c.activity_id "
        "WHERE a.activity_code='activity-showcase-walk' AND c.chooser_user_id=:user AND c.status='active'",
        "activity_matches": "SELECT count(*) FROM activity_mutual_choices m JOIN activities a ON a.id=m.activity_id "
        "WHERE a.activity_code='activity-showcase-walk' AND (m.user_a_id=:user OR m.user_b_id=:user) AND m.status='matched_private'",
        "course_enrollments": "SELECT count(*) FROM course_enrollments e JOIN courses c ON c.id=e.course_id "
        "WHERE e.user_id=:user AND c.course_code IN ('course-e2e-foundations','course-showcase-communication','course-showcase-growth-plan')",
        "course_certificates": "SELECT count(*) FROM course_certificates WHERE user_id=:user "
        "AND certificate_number LIKE 'CERT-TEST-%'",
        "counseling_appointments": "SELECT count(*) FROM counseling_appointments WHERE user_id=:user AND appointment_number LIKE 'APT-TEST-%'",
        "counseling_followups": "SELECT count(*) FROM counseling_follow_ups WHERE user_id=:user AND id IN "
        "(:followup_a,:followup_b,:followup_c)",
        "cart_items": "SELECT count(*) FROM cart_items i JOIN carts c ON c.id=i.cart_id "
        "WHERE c.user_id=:user AND c.currency_code='USD' AND c.status IN ('active','checkout_started')",
        "orders": "SELECT count(*) FROM orders WHERE user_id=:user AND order_number LIKE 'ORD-TEST-%'",
        "subscriptions": "SELECT count(*) FROM subscriptions WHERE user_id=:user "
        "AND provider='fixture' AND provider_subscription_id LIKE 'test-showcase-subscription-%'",
        "entitlements": "SELECT count(*) FROM entitlements WHERE user_id=:user AND id IN "
        "(:entitlement_a,:entitlement_b,:entitlement_c)",
        "membership_history": "SELECT count(*) FROM membership_accounts WHERE user_id=:user AND source_type='admin_grant' "
        "AND id IN (:membership_a,:membership_b,:membership_c)",
        "dating_photos": "SELECT count(*) FROM dating_profile_photos ph JOIN dating_profiles p ON p.id=ph.dating_profile_id "
        "WHERE p.user_id=:user AND ph.status='approved' AND ph.deleted_at IS NULL",
        "preference_criteria": "SELECT count(*) FROM partner_preference_criteria c "
        "JOIN partner_preference_profiles p ON p.id=c.partner_preference_profile_id WHERE p.user_id=:user",
        "recommendations": "SELECT count(*) FROM recommendation_items WHERE viewer_user_id=:user AND status IN ('ready','exposed','viewed')",
        "recommendation_batches": "SELECT count(*) FROM recommendation_batches WHERE user_id=:user",
        "likes": "SELECT count(*) FROM matchmaking_likes WHERE actor_user_id=:user "
        "AND idempotency_key LIKE 'test-showcase%' AND split_part(idempotency_key,':',2)='like' "
        "AND split_part(idempotency_key,':',4)='user'",
        "skips": "SELECT count(*) FROM matchmaking_skips WHERE actor_user_id=:user AND idempotency_key LIKE 'test-showcase:skip:%'",
        "matches": "SELECT count(*) FROM matchmaking_mutual_matches WHERE (user_low_id=:user OR user_high_id=:user) AND status='active'",
        "invitations": "SELECT count(*) FROM matchmaking_introduction_invitations WHERE "
        "(sender_user_id=:user OR recipient_user_id=:user) AND invitation_number LIKE 'INV-TEST-%'",
        "contact_exchanges": "SELECT count(*) FROM matchmaking_contact_exchange_requests r "
        "JOIN matchmaking_pairs p ON p.id=r.pair_id WHERE (p.user_low_id=:user OR p.user_high_id=:user) AND r.status='active'",
        "relationships": "SELECT count(*) FROM relationship_journeys WHERE (user_low_id=:user OR user_high_id=:user) AND status='active'",
        "relationship_timeline": "SELECT count(*) FROM relationship_status_history h JOIN relationship_journeys j ON j.id=h.journey_id "
        "WHERE (j.user_low_id=:user OR j.user_high_id=:user) AND j.journey_number LIKE 'REL-TEST-%'",
        "relationship_milestones": "SELECT count(*) FROM relationship_milestones m JOIN relationship_journeys j ON j.id=m.journey_id "
        "WHERE (j.user_low_id=:user OR j.user_high_id=:user) AND j.journey_number LIKE 'REL-TEST-%' AND m.status='active'",
        "relationship_checkins": "SELECT count(*) FROM relationship_checkins c JOIN relationship_journeys j ON j.id=c.journey_id "
        "WHERE (j.user_low_id=:user OR j.user_high_id=:user) AND j.journey_number LIKE 'REL-TEST-%'",
        "relationship_reflections": "SELECT count(*) FROM relationship_reflections r JOIN relationship_journeys j ON j.id=r.journey_id "
        "WHERE r.author_user_id=:user AND j.journey_number LIKE 'REL-TEST-%' AND r.status='active'",
        "safety_reports": "SELECT count(*) FROM safety_reports WHERE reporter_user_id=:user AND report_number LIKE 'SR-TEST-%'",
        "blocks": "SELECT count(*) FROM user_blocks WHERE blocker_user_id=:user AND status='active'",
        "restrictions": "SELECT count(*) FROM account_restrictions WHERE user_id=:user AND status='active' "
        "AND reason_code='test_showcase_review'",
        "appeals": "SELECT count(*) FROM safety_appeals WHERE appellant_user_id=:user AND appeal_number LIKE 'SA-TEST-%'",
        "membership_plans": "SELECT count(*) FROM membership_plans WHERE status='active'",
        "experience_tasks": "SELECT count(*) FROM experience_user_tasks WHERE user_id=:user AND deduplication_key LIKE 'test-showcase:%'",
        "experience_journeys": "SELECT count(*) FROM experience_journey_instances WHERE user_id=:user "
        "AND source_module='test_showcase'",
    }
    parameters = {
        "user": user_id,
        "a": _id("notification:1"),
        "b": _id("notification:2"),
        "c": _id("notification:3"),
        "contact_email": _id("contact:email"),
        "contact_phone": _id("contact:phone"),
        "contact_wechat": _id("contact:wechat"),
        "consent_a": _id("consent:platform_terms"),
        "consent_b": _id("consent:privacy_policy"),
        "consent_c": _id("consent:ai_assistant_use"),
        "notification_pref_a": _id("notification-preference:1"),
        "notification_pref_b": _id("notification-preference:2"),
        "notification_pref_c": _id("notification-preference:3"),
        "followup_a": _id("counseling-followup:1"),
        "followup_b": _id("counseling-followup:2"),
        "followup_c": _id("counseling-followup:3"),
        "entitlement_a": _id("entitlement:1"),
        "entitlement_b": _id("entitlement:2"),
        "entitlement_c": _id("entitlement:3"),
        "membership_a": _id("membership-history:1"),
        "membership_b": _id("membership-history:2"),
        "membership_c": _id("membership-history:3"),
    }
    counts: dict[str, int] = {}
    for name, query in queries.items():
        counts[name] = int(await session.scalar(text(query), parameters) or 0)
    minimums = {
        "published_pages": 8,
        "articles": 3,
        "stories": 3,
        "contact_points": 3,
        "consents": 3,
        "notifications": 3,
        "notification_preferences": 3,
        "ai_conversations": 3,
        "privacy_requests": 3,
        "ai_memories": 3,
        "auth_sessions": 3,
        "activity_registrations": 3,
        "activity_waitlist": 3,
        "activity_participants": 3,
        "activity_choices": 3,
        "activity_matches": 3,
        "course_enrollments": 3,
        "course_certificates": 3,
        "counseling_appointments": 3,
        "counseling_followups": 3,
        "cart_items": 3,
        "orders": 3,
        "subscriptions": 3,
        "entitlements": 3,
        "membership_history": 3,
        "dating_photos": 3,
        "preference_criteria": 3,
        "recommendations": 3,
        "recommendation_batches": 3,
        "likes": 3,
        "skips": 3,
        "matches": 3,
        "invitations": 3,
        "contact_exchanges": 3,
        "relationships": 3,
        "relationship_timeline": 9,
        "relationship_milestones": 9,
        "relationship_checkins": 9,
        "relationship_reflections": 9,
        "safety_reports": 3,
        "blocks": 3,
        "restrictions": 3,
        "appeals": 3,
        "membership_plans": 3,
        "experience_tasks": 3,
        "experience_journeys": 3,
    }
    missing = {
        name: {"expected_at_least": minimum, "actual": counts[name]}
        for name, minimum in minimums.items()
        if counts[name] < minimum
    }
    if missing:
        raise RuntimeError(f"Test showcase coverage is incomplete: {_json(missing)}")
    return counts


async def _seed_reference_data() -> None:
    await seed_permissions()
    await seed_test_user()
    await seed_cms()
    await seed_catalog()
    await seed_privacy()
    await seed_notification_templates()
    await seed_notifications()
    await seed_ai_assistant()
    await seed_experience()
    await seed_memberships()
    await seed_activities()
    await seed_courses()
    await seed_counseling()
    await seed_relationships()
    await seed_trust_safety()
    await seed_recommendations()
    await seed_fixtures()
    await seed_dating_profiles()


async def seed_test_showcase() -> dict[str, int]:
    environment = get_settings().environment
    if environment in PROTECTED_ENVIRONMENTS:
        raise RuntimeError(
            f"Refusing to seed the insecure test showcase in protected environment: {environment}."
        )
    await _seed_reference_data()
    async with session_factory() as session:
        user_id = await _test_user_id(session)
        await _seed_public_content(session)
        await _seed_profile_and_privacy(session, user_id)
        await _seed_notifications(session, user_id)
        await _seed_ai_conversations(session, user_id)
        await _seed_sessions_and_experience(session, user_id)
        await _seed_activity_registrations(session, user_id)
        await _seed_activity_experience(session, user_id)
        await _seed_course_learning(session, user_id)
        await _seed_counseling_appointments(session, user_id)
        await _seed_commerce(session, user_id)
        await _seed_membership(session, user_id)
        profile_id = await _seed_dating_profile(session, user_id)
        await _seed_recommendations(session, user_id, profile_id)
        await _seed_matchmaking_and_relationships(session, user_id)
        await _seed_safety(session, user_id)
        await session.commit()
        counts = await _coverage_counts(session, user_id)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-test-showcase",
        action="store_true",
        help="Acknowledge that synthetic data will be attached to the insecure test/test account.",
    )
    args = parser.parse_args()
    if not args.confirm_test_showcase:
        raise SystemExit("Refusing to seed test showcase data without explicit confirmation.")
    counts = asyncio.run(seed_test_showcase())
    print(f"Test showcase ready for {TEST_USER_EMAIL}: {_json(counts)}")


if __name__ == "__main__":
    main()
