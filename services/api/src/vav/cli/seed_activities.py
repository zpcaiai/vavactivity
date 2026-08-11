from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.models.activities import (
    Activity,
    ActivityLocalization,
    ActivityLocation,
    ActivityRegistrationForm,
    ActivityTicketType,
)
from vav.models.catalog import Price, PriceBook, Product, ProductLocalization, ProductSku
from vav.modules.activities.crypto import encrypt_private


async def seed_activities() -> None:
    if get_settings().environment not in {"development", "test", "staging"}:
        print("Activity fixtures skipped outside development/test/staging.")
        return
    await ensure_system_user()
    async with session_factory() as session:
        book = await session.scalar(
            select(PriceBook).where(PriceBook.price_book_code == "GLOBAL_STANDARD")
        )
        if book is None:
            raise RuntimeError("Run catalog seed before activity seed.")
        starts_at = datetime.now(UTC) + timedelta(days=30)
        product = await session.scalar(
            select(Product).where(Product.product_code == "ACTIVITY_E2E_SOCIAL")
        )
        if product is None:
            product = Product(
                product_code="ACTIVITY_E2E_SOCIAL",
                product_type="activity_ticket",
                fulfillment_type="event_admission",
                internal_name="Local activity acceptance fixture",
                status="active",
                visibility="public",
                default_locale="zh-CN",
                created_by=SYSTEM_USER_ID,
                updated_by=SYSTEM_USER_ID,
            )
            session.add(product)
            await session.flush()
            for locale, name in (
                ("zh-CN", "城市同行交流夜"),
                ("zh-TW", "城市同行交流夜"),
                ("en", "City Connections Evening"),
            ):
                session.add(
                    ProductLocalization(
                        product_id=product.id,
                        locale=locale,
                        slug="activity-e2e-social",
                        name=name,
                        short_description="Development and test environments only.",
                        description_blocks=[],
                        translation_status="ready",
                    )
                )
        sku = await session.scalar(
            select(ProductSku).where(ProductSku.sku_code == "ACTIVITY_E2E_FREE")
        )
        activity = await session.scalar(
            select(Activity).where(Activity.activity_code == "activity-e2e-social")
        )
        if activity is None:
            activity = Activity(
                activity_code="activity-e2e-social",
                internal_name="Local activity acceptance fixture",
                activity_format="in_person",
                status="registration_open",
                visibility="public",
                default_locale="zh-CN",
                timezone="Asia/Shanghai",
                registration_opens_at=datetime.now(UTC) - timedelta(days=1),
                registration_closes_at=starts_at - timedelta(hours=1),
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=3),
                post_event_choice_opens_at=starts_at + timedelta(hours=3),
                post_event_choice_closes_at=starts_at + timedelta(hours=75),
                approval_policy="automatic",
                payment_timing_policy="before_approval",
                waitlist_enabled=True,
                post_event_choice_enabled=True,
                cancellation_policy_snapshot={
                    "status": "configuration_required",
                    "default": "manual_review",
                },
                created_by=SYSTEM_USER_ID,
                updated_by=SYSTEM_USER_ID,
            )
            session.add(activity)
            await session.flush()
            for locale, slug, title in (
                ("zh-CN", "city-connections-evening", "城市同行交流夜"),
                ("zh-TW", "city-connections-evening", "城市同行交流夜"),
                ("en", "city-connections-evening", "City Connections Evening"),
            ):
                session.add(
                    ActivityLocalization(
                        activity_id=activity.id,
                        locale=locale,
                        slug=slug,
                        title=title,
                        summary="安全、尊重、以真实交流为核心的小型活动。",
                        description_blocks=[
                            {
                                "type": "paragraph",
                                "text": "报名、名额与支付结果均由服务端确认。",
                            }
                        ],
                        venue_display_name="VAV 城市活动空间",
                        address_display_text="上海市；完整地址仅向已确认参与者开放",
                        translation_status="ready",
                    )
                )
            session.add(
                ActivityLocation(
                    activity_id=activity.id,
                    location_type="in_person",
                    venue_name="VAV 城市活动空间",
                    country_code="CN",
                    region="上海",
                    city="上海",
                    address_line_1_encrypted=encrypt_private(
                        {"value": "浦东新区示例路 100 号（仅限本地验收数据）"}
                    ),
                    public_address_precision="city_only",
                )
            )
            session.add(
                ActivityRegistrationForm(
                    activity_id=activity.id,
                    schema_version=1,
                    form_schema={
                        "fields": [
                            {
                                "key": "expectations",
                                "type": "textarea",
                                "label": "你对活动有什么期待？",
                                "required": True,
                            }
                        ]
                    },
                    consent_requirements=[
                        {
                            "key": "activity_rules_v1",
                            "label": "我同意活动守则与隐私边界",
                            "required": True,
                        }
                    ],
                    created_by=SYSTEM_USER_ID,
                )
            )
        if sku is None:
            sku = ProductSku(
                product_id=product.id,
                sku_code="ACTIVITY_E2E_FREE",
                internal_name="Local free admission",
                billing_type="free",
                status="active",
                fulfillment_configuration={
                    "activity_id": str(activity.id),
                    "ticket_type": "general",
                },
                inventory_policy="unlimited",
                purchase_limit_per_user=1,
            )
            session.add(sku)
            await session.flush()
        location = await session.scalar(
            select(ActivityLocation).where(ActivityLocation.activity_id == activity.id)
        )
        if location is not None and location.address_line_1_encrypted is None:
            location.address_line_1_encrypted = encrypt_private(
                {"value": "浦东新区示例路 100 号（仅限本地验收数据）"}
            )
        price = await session.scalar(
            select(Price).where(
                Price.sku_id == sku.id,
                Price.price_book_id == book.id,
                Price.currency_code == "USD",
                Price.status == "active",
            )
        )
        if price is None:
            session.add(
                Price(
                    sku_id=sku.id,
                    price_book_id=book.id,
                    currency_code="USD",
                    unit_amount_minor=0,
                    billing_type="free",
                    valid_from=datetime.now(UTC),
                    status="active",
                    created_by=SYSTEM_USER_ID,
                )
            )
        ticket = await session.scalar(
            select(ActivityTicketType).where(
                ActivityTicketType.activity_id == activity.id,
                ActivityTicketType.ticket_code == "general",
            )
        )
        if ticket is None:
            session.add(
                ActivityTicketType(
                    activity_id=activity.id,
                    ticket_code="general",
                    internal_name="免费普通票",
                    catalog_product_id=product.id,
                    catalog_sku_id=sku.id,
                    status="active",
                    waitlist_enabled=True,
                    max_quantity_per_user=1,
                    eligibility_rules={},
                )
            )
        companion_specs = (
            {
                "code": "activity-showcase-boundaries",
                "product": "ACTIVITY_SHOWCASE_BOUNDARIES",
                "sku": "ACTIVITY_SHOWCASE_BOUNDARIES_FREE",
                "slug": "healthy-boundaries-workshop",
                "title": "健康边界练习工作坊",
                "summary": "通过情境练习学习表达需要、倾听与尊重边界。",
                "venue": "VAV 线上活动室",
                "format": "online",
                "day_offset": 37,
            },
            {
                "code": "activity-showcase-walk",
                "product": "ACTIVITY_SHOWCASE_WALK",
                "sku": "ACTIVITY_SHOWCASE_WALK_FREE",
                "slug": "weekend-city-walk",
                "title": "周末城市同行漫步",
                "summary": "轻松、安全的小组漫步，在真实交流中认识新朋友。",
                "venue": "VAV 城市集合点",
                "format": "in_person",
                "day_offset": 45,
            },
        )
        for spec in companion_specs:
            companion_product = await session.scalar(
                select(Product).where(Product.product_code == spec["product"])
            )
            if companion_product is None:
                companion_product = Product(
                    product_code=spec["product"],
                    product_type="activity_ticket",
                    fulfillment_type="event_admission",
                    internal_name=f"Test showcase: {spec['title']}",
                    status="active",
                    visibility="public",
                    default_locale="zh-CN",
                    created_by=SYSTEM_USER_ID,
                    updated_by=SYSTEM_USER_ID,
                )
                session.add(companion_product)
                await session.flush()
                session.add(
                    ProductLocalization(
                        product_id=companion_product.id,
                        locale="zh-CN",
                        slug=str(spec["slug"]),
                        name=str(spec["title"]),
                        short_description=str(spec["summary"]),
                        description_blocks=[],
                        translation_status="ready",
                    )
                )
            companion_activity = await session.scalar(
                select(Activity).where(Activity.activity_code == spec["code"])
            )
            companion_starts_at = datetime.now(UTC) + timedelta(days=cast(int, spec["day_offset"]))
            if companion_activity is None:
                companion_activity = Activity(
                    activity_code=str(spec["code"]),
                    internal_name=f"Test showcase: {spec['title']}",
                    activity_format=str(spec["format"]),
                    status="registration_open",
                    visibility="public",
                    default_locale="zh-CN",
                    timezone="Asia/Shanghai",
                    registration_opens_at=datetime.now(UTC) - timedelta(days=1),
                    registration_closes_at=companion_starts_at - timedelta(hours=1),
                    starts_at=companion_starts_at,
                    ends_at=companion_starts_at + timedelta(hours=2),
                    post_event_choice_opens_at=companion_starts_at + timedelta(hours=2),
                    post_event_choice_closes_at=companion_starts_at + timedelta(hours=74),
                    approval_policy="automatic",
                    payment_timing_policy="before_approval",
                    waitlist_enabled=True,
                    post_event_choice_enabled=True,
                    cancellation_policy_snapshot={"mode": "manual_review"},
                    created_by=SYSTEM_USER_ID,
                    updated_by=SYSTEM_USER_ID,
                )
                session.add(companion_activity)
                await session.flush()
                session.add_all(
                    (
                        ActivityLocalization(
                            activity_id=companion_activity.id,
                            locale="zh-CN",
                            slug=str(spec["slug"]),
                            title=str(spec["title"]),
                            summary=str(spec["summary"]),
                            description_blocks=[
                                {"type": "paragraph", "text": "本活动为 test 账户展示数据。"}
                            ],
                            venue_display_name=str(spec["venue"]),
                            address_display_text="线上" if spec["format"] == "online" else "上海市",
                            translation_status="ready",
                        ),
                        ActivityLocation(
                            activity_id=companion_activity.id,
                            location_type=str(spec["format"]),
                            venue_name=str(spec["venue"]),
                            country_code="CN",
                            region="上海",
                            city="上海",
                            address_line_1_encrypted=encrypt_private(
                                {"value": "test showcase location"}
                            ),
                            public_address_precision="city_only",
                        ),
                        ActivityRegistrationForm(
                            activity_id=companion_activity.id,
                            schema_version=1,
                            form_schema={"fields": []},
                            consent_requirements=[],
                            created_by=SYSTEM_USER_ID,
                        ),
                    )
                )
            companion_sku = await session.scalar(
                select(ProductSku).where(ProductSku.sku_code == spec["sku"])
            )
            if companion_sku is None:
                companion_sku = ProductSku(
                    product_id=companion_product.id,
                    sku_code=str(spec["sku"]),
                    internal_name=f"{spec['title']} 免费票",
                    billing_type="free",
                    status="active",
                    fulfillment_configuration={
                        "activity_id": str(companion_activity.id),
                        "ticket_type": "general",
                    },
                    inventory_policy="unlimited",
                    purchase_limit_per_user=1,
                )
                session.add(companion_sku)
                await session.flush()
                session.add(
                    Price(
                        sku_id=companion_sku.id,
                        price_book_id=book.id,
                        currency_code="USD",
                        unit_amount_minor=0,
                        billing_type="free",
                        valid_from=datetime.now(UTC),
                        status="active",
                        created_by=SYSTEM_USER_ID,
                    )
                )
            companion_ticket = await session.scalar(
                select(ActivityTicketType).where(
                    ActivityTicketType.activity_id == companion_activity.id,
                    ActivityTicketType.ticket_code == "general",
                )
            )
            if companion_ticket is None:
                session.add(
                    ActivityTicketType(
                        activity_id=companion_activity.id,
                        ticket_code="general",
                        internal_name=f"{spec['title']} 免费票",
                        catalog_product_id=companion_product.id,
                        catalog_sku_id=companion_sku.id,
                        status="active",
                        waitlist_enabled=True,
                        max_quantity_per_user=1,
                        eligibility_rules={},
                    )
                )
        await session.commit()
    print("Activity seed complete: 3 public fixtures with Catalog tickets")


if __name__ == "__main__":
    asyncio.run(seed_activities())
