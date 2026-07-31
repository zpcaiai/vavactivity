from __future__ import annotations

import asyncio

from sqlalchemy import select

from vav.cli.seed_cms import ensure_system_user
from vav.core.database import session_factory
from vav.models.catalog import (
    PriceBook,
    ProductCategory,
    ProductCategoryLocalization,
    SupportedCurrency,
)

CURRENCIES = {
    "CNY": (2, 10),
    "USD": (2, 20),
    "TWD": (0, 30),
    "HKD": (2, 40),
}

CATEGORIES = {
    "activities": ("活动", "活動", "Activities"),
    "courses": ("课程", "課程", "Courses"),
    "course_bundles": ("课程套餐", "課程套裝", "Course bundles"),
    "counseling": ("真人辅导", "真人輔導", "Counseling"),
    "ai_coaching": ("AI 辅导", "AI 輔導", "AI coaching"),
    "memberships": ("婚恋会员", "婚戀會員", "Memberships"),
}


async def seed_catalog() -> None:
    await ensure_system_user()
    async with session_factory() as session:
        for code, (exponent, display_order) in CURRENCIES.items():
            currency = await session.get(SupportedCurrency, code)
            if currency is None:
                session.add(
                    SupportedCurrency(
                        currency_code=code,
                        exponent=exponent,
                        display_order=display_order,
                    )
                )

        for code, labels in CATEGORIES.items():
            category = await session.scalar(
                select(ProductCategory).where(ProductCategory.category_code == code)
            )
            if category is None:
                category = ProductCategory(
                    category_code=code,
                    internal_name=code.replace("_", " ").title(),
                    status="active",
                )
                session.add(category)
                await session.flush()
            for locale, label in zip(("zh-CN", "zh-TW", "en"), labels, strict=True):
                localized = await session.get(ProductCategoryLocalization, (category.id, locale))
                if localized is None:
                    session.add(
                        ProductCategoryLocalization(
                            category_id=category.id,
                            locale=locale,
                            name=label,
                            slug=code.replace("_", "-"),
                        )
                    )

        book = await session.scalar(
            select(PriceBook).where(PriceBook.price_book_code == "GLOBAL_STANDARD")
        )
        if book is None:
            session.add(
                PriceBook(
                    price_book_code="GLOBAL_STANDARD",
                    name="Global standard explicit prices",
                    status="active",
                    priority=0,
                )
            )
        await session.commit()
    print("Catalog seed complete: currencies, localized categories and global price book")


if __name__ == "__main__":
    asyncio.run(seed_catalog())
