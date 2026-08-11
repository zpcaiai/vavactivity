from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.models.catalog import Price, PriceBook, Product, ProductLocalization, ProductSku
from vav.models.counseling import (
    CounselingAvailabilityRule,
    CounselingMentor,
    CounselingMentorLocalization,
    CounselingMentorService,
    CounselingServiceDefinition,
    CounselingServiceLocalization,
)


async def seed_counseling() -> None:
    if get_settings().environment not in {"development", "test", "staging"}:
        print("Counseling fixtures skipped outside development/test/staging.")
        return
    await ensure_system_user()
    async with session_factory() as session:
        book = await session.scalar(
            select(PriceBook).where(PriceBook.price_book_code == "GLOBAL_STANDARD")
        )
        if book is None:
            raise RuntimeError("Run catalog seed before counseling seed.")

        product = await session.scalar(
            select(Product).where(Product.product_code == "COUNSELING_E2E_SESSION")
        )
        if product is None:
            product = Product(
                product_code="COUNSELING_E2E_SESSION",
                product_type="counseling_session",
                fulfillment_type="appointment_credits",
                internal_name="Local counseling acceptance fixture",
                status="active",
                visibility="public",
                default_locale="zh-CN",
                created_by=SYSTEM_USER_ID,
                updated_by=SYSTEM_USER_ID,
            )
            session.add(product)
            await session.flush()
            session.add(
                ProductLocalization(
                    product_id=product.id,
                    locale="zh-CN",
                    slug="counseling-e2e-session",
                    name="关系成长支持会谈",
                    short_description="开发与验收环境的一对一支持服务。",
                    description_blocks=[],
                    translation_status="ready",
                )
            )
        sku = await session.scalar(
            select(ProductSku).where(ProductSku.sku_code == "COUNSELING_E2E_SINGLE")
        )
        if sku is None:
            sku = ProductSku(
                product_id=product.id,
                sku_code="COUNSELING_E2E_SINGLE",
                internal_name="单次关系成长支持会谈",
                billing_type="one_time",
                status="active",
                service_quantity=1,
                service_unit="session",
                entitlement_definition={"type": "counseling_credits"},
                fulfillment_configuration={"session_count": 1, "validity_days": 365},
                inventory_policy="unlimited",
            )
            session.add(sku)
            await session.flush()
            session.add(
                Price(
                    sku_id=sku.id,
                    price_book_id=book.id,
                    currency_code="USD",
                    unit_amount_minor=4900,
                    billing_type="one_time",
                    valid_from=datetime.now(UTC),
                    status="active",
                    created_by=SYSTEM_USER_ID,
                )
            )

        mentor = await session.scalar(
            select(CounselingMentor).where(CounselingMentor.mentor_code == "counseling-e2e-mentor")
        )
        if mentor is None:
            mentor = CounselingMentor(
                mentor_code="counseling-e2e-mentor",
                display_name="VAV 成长导师",
                status="active",
                timezone="Asia/Shanghai",
                service_languages=["zh-CN", "en"],
                specialty_topics=["communication", "boundaries"],
                created_by=SYSTEM_USER_ID,
            )
            session.add(mentor)
            await session.flush()
            session.add(
                CounselingMentorLocalization(
                    mentor_id=mentor.id,
                    locale="zh-CN",
                    slug="vav-growth-mentor",
                    public_name="VAV 成长导师",
                    headline="陪伴练习边界、沟通与关系成长",
                    biography_blocks=[{"type": "paragraph", "text": "提供教育性成长支持。"}],
                    scope_statement="本服务不提供心理治疗、医疗诊断、法律意见或紧急危机服务。",
                    translation_status="ready",
                )
            )

        service = await session.scalar(
            select(CounselingServiceDefinition).where(
                CounselingServiceDefinition.service_code == "counseling-e2e-growth-session"
            )
        )
        if service is None:
            service = CounselingServiceDefinition(
                service_code="counseling-e2e-growth-session",
                internal_name="Local growth support session",
                status="published",
                delivery_mode="online",
                participant_mode="individual",
                duration_minutes=60,
                booking_mode="direct_booking",
                payment_policy="free",
                free_access=True,
                catalog_product_id=product.id,
                catalog_sku_id=sku.id,
                cancellation_policy={"mode": "manual_review"},
                no_show_policy={"consume_credit": False, "mode": "manual_review"},
                scope_policy={
                    "therapy": False,
                    "medical": False,
                    "legal": False,
                    "emergency": False,
                },
                min_notice_minutes=0,
                max_advance_days=120,
                created_by=SYSTEM_USER_ID,
            )
            session.add(service)
            await session.flush()
            session.add(
                CounselingServiceLocalization(
                    service_id=service.id,
                    locale="zh-CN",
                    slug="growth-support-session",
                    name="关系成长支持会谈",
                    summary="围绕沟通、边界和关系实践的一对一教育性支持。",
                    description_blocks=[
                        {"type": "paragraph", "text": "通过结构化对话形成可执行的练习计划。"}
                    ],
                    scope_notice="本服务不替代心理治疗、医疗诊断、法律意见或紧急危机处置。",
                    translation_status="ready",
                )
            )

        link = await session.scalar(
            select(CounselingMentorService).where(
                CounselingMentorService.mentor_id == mentor.id,
                CounselingMentorService.service_id == service.id,
            )
        )
        if link is None:
            session.add(
                CounselingMentorService(mentor_id=mentor.id, service_id=service.id, status="active")
            )
        for weekday in range(7):
            rule = await session.scalar(
                select(CounselingAvailabilityRule).where(
                    CounselingAvailabilityRule.mentor_id == mentor.id,
                    CounselingAvailabilityRule.service_id == service.id,
                    CounselingAvailabilityRule.weekday == weekday,
                )
            )
            if rule is None:
                session.add(
                    CounselingAvailabilityRule(
                        mentor_id=mentor.id,
                        service_id=service.id,
                        timezone="Asia/Shanghai",
                        weekday=weekday,
                        local_start_time=time(9),
                        local_end_time=time(18),
                        valid_from=date.today() - timedelta(days=1),
                        valid_until=date.today() + timedelta(days=150),
                        status="active",
                    )
                )
        companion_specs = (
            (
                "counseling-showcase-communication",
                "communication-practice-session",
                "沟通练习支持会谈",
                "聚焦倾听、表达需要与冲突后的修复练习。",
                45,
            ),
            (
                "counseling-showcase-decisions",
                "relationship-decisions-session",
                "关系决策梳理会谈",
                "用结构化问题梳理价值、选择与下一步行动。",
                50,
            ),
        )
        for service_code, slug, name, summary, duration in companion_specs:
            companion = await session.scalar(
                select(CounselingServiceDefinition).where(
                    CounselingServiceDefinition.service_code == service_code
                )
            )
            if companion is None:
                companion = CounselingServiceDefinition(
                    service_code=service_code,
                    internal_name=f"Test showcase: {name}",
                    status="published",
                    delivery_mode="online",
                    participant_mode="individual",
                    duration_minutes=duration,
                    booking_mode="direct_booking",
                    payment_policy="free",
                    free_access=True,
                    catalog_product_id=product.id,
                    catalog_sku_id=sku.id,
                    cancellation_policy={"mode": "manual_review"},
                    no_show_policy={"consume_credit": False, "mode": "manual_review"},
                    scope_policy={
                        "therapy": False,
                        "medical": False,
                        "legal": False,
                        "emergency": False,
                    },
                    min_notice_minutes=0,
                    max_advance_days=120,
                    created_by=SYSTEM_USER_ID,
                )
                session.add(companion)
                await session.flush()
                session.add(
                    CounselingServiceLocalization(
                        service_id=companion.id,
                        locale="zh-CN",
                        slug=slug,
                        name=name,
                        summary=summary,
                        description_blocks=[
                            {"type": "paragraph", "text": "本服务为 test 账户展示数据。"}
                        ],
                        scope_notice="本服务不替代心理治疗、医疗诊断、法律意见或紧急危机处置。",
                        translation_status="ready",
                    )
                )
            companion_link = await session.scalar(
                select(CounselingMentorService).where(
                    CounselingMentorService.mentor_id == mentor.id,
                    CounselingMentorService.service_id == companion.id,
                )
            )
            if companion_link is None:
                session.add(
                    CounselingMentorService(
                        mentor_id=mentor.id, service_id=companion.id, status="active"
                    )
                )
            for weekday in range(7):
                companion_rule = await session.scalar(
                    select(CounselingAvailabilityRule).where(
                        CounselingAvailabilityRule.mentor_id == mentor.id,
                        CounselingAvailabilityRule.service_id == companion.id,
                        CounselingAvailabilityRule.weekday == weekday,
                    )
                )
                if companion_rule is None:
                    session.add(
                        CounselingAvailabilityRule(
                            mentor_id=mentor.id,
                            service_id=companion.id,
                            timezone="Asia/Shanghai",
                            weekday=weekday,
                            local_start_time=time(9),
                            local_end_time=time(18),
                            valid_from=date.today() - timedelta(days=1),
                            valid_until=date.today() + timedelta(days=150),
                            status="active",
                        )
                    )
        await session.commit()
    print("Counseling seed complete: 3 public services.")


if __name__ == "__main__":
    asyncio.run(seed_counseling())
