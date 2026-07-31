from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from vav.cli.seed_cms import SYSTEM_USER_ID, ensure_system_user
from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.models.catalog import Price, PriceBook, Product, ProductLocalization, ProductSku


async def seed_local_checkout_fixture() -> None:
    """Create an explicit local-only paid SKU for browser acceptance tests."""
    settings = get_settings()
    if (
        settings.environment not in {"development", "test"}
        or not settings.payment_test_fake_enabled
    ):
        return
    await ensure_system_user()
    system_id = SYSTEM_USER_ID
    async with session_factory() as session:
        product = await session.scalar(
            select(Product).where(Product.product_code == "COMMERCE_E2E_PRODUCT")
        )
        if product is None:
            product = Product(
                product_code="COMMERCE_E2E_PRODUCT",
                product_type="digital_service",
                fulfillment_type="digital_access",
                internal_name="Local commerce browser fixture",
                status="active",
                visibility="public",
                default_locale="zh-CN",
                created_by=system_id,
                updated_by=system_id,
            )
            session.add(product)
            await session.flush()
            for locale, name in (
                ("zh-CN", "本地支付闭环测试服务"),
                ("zh-TW", "本機付款閉環測試服務"),
                ("en", "Local payment-loop test service"),
            ):
                session.add(
                    ProductLocalization(
                        product_id=product.id,
                        locale=locale,
                        slug="commerce-e2e-service",
                        name=name,
                        short_description="Development and test environments only.",
                        description_blocks=[],
                        translation_status="ready",
                    )
                )
        sku = await session.scalar(
            select(ProductSku).where(ProductSku.sku_code == "COMMERCE_E2E_USD")
        )
        if sku is None:
            sku = ProductSku(
                product_id=product.id,
                sku_code="COMMERCE_E2E_USD",
                internal_name="Local one-time USD fixture",
                billing_type="one_time",
                status="active",
                fulfillment_configuration={"validity_days": 30},
                inventory_policy="unlimited",
            )
            session.add(sku)
            await session.flush()
        book = await session.scalar(
            select(PriceBook).where(PriceBook.price_book_code == "GLOBAL_STANDARD")
        )
        if book is None:
            raise RuntimeError("Run catalog seed before commerce seed.")
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
                    unit_amount_minor=1299,
                    billing_type="one_time",
                    valid_from=datetime.now(UTC),
                    status="active",
                    created_by=system_id,
                )
            )
        await session.commit()


async def seed_commerce() -> None:
    settings = get_settings()
    await seed_local_checkout_fixture()
    mode = "local signed fake" if settings.payment_test_fake_enabled else "configured adapters"
    print(
        "Commerce seed complete: RBAC is seeded by seed_permissions; "
        f"providers={','.join(settings.payment_enabled_providers)}; mode={mode}"
    )


if __name__ == "__main__":
    asyncio.run(seed_commerce())
