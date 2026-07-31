import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.catalog import (
    Coupon,
    Price,
    PriceBook,
    PricingQuote,
    Product,
    ProductSku,
    Promotion,
    SupportedCurrency,
)
from vav.models.identity import User
from vav.modules.catalog.promotions import coupon_redemption_service
from vav.modules.identity.domain import UserStatus


async def create_limited_coupon_quotes() -> tuple[Coupon, Promotion, list[PricingQuote]]:
    suffix = uuid4().hex
    async with session_factory() as session:
        actor = User(
            email=f"coupon-race-{suffix}@example.com",
            display_email=f"coupon-race-{suffix}@example.com",
            password_hash=None,
            status=UserStatus.SUSPENDED,
        )
        session.add(actor)
        await session.flush()
        product = Product(
            product_code=f"COUPON-RACE-{suffix.upper()}",
            product_type="digital_service",
            fulfillment_type="digital_access",
            internal_name="Coupon race",
            status="active",
            visibility="public",
            default_locale="zh-CN",
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(product)
        await session.flush()
        sku = ProductSku(
            product_id=product.id,
            sku_code=f"COUPON-SKU-{suffix.upper()}",
            internal_name="Coupon race SKU",
            billing_type="one_time",
            status="active",
            fulfillment_configuration={"service_code": "coupon-race"},
            inventory_policy="unlimited",
        )
        session.add(sku)
        await session.flush()
        if await session.get(SupportedCurrency, "USD") is None:
            session.add(SupportedCurrency(currency_code="USD", exponent=2))
            await session.flush()
        book = await session.scalar(
            select(PriceBook).where(PriceBook.price_book_code == "GLOBAL_STANDARD")
        )
        if book is None:
            book = PriceBook(
                price_book_code="GLOBAL_STANDARD",
                name="Global standard",
                status="active",
            )
            session.add(book)
            await session.flush()
        price = Price(
            sku_id=sku.id,
            price_book_id=book.id,
            currency_code="USD",
            unit_amount_minor=1000,
            billing_type="one_time",
            valid_from=datetime.now(UTC) - timedelta(minutes=1),
            status="active",
            created_by=actor.id,
        )
        session.add(price)
        promotion = Promotion(
            promotion_code=f"LIMIT-{suffix.upper()}",
            internal_name="Single redemption",
            promotion_type="fixed_amount",
            application_mode="coupon_required",
            status="active",
            priority=1,
            stackability="exclusive",
            rules={"schema_version": 1},
            benefits={"schema_version": 1, "amounts": {"USD": 100}},
            valid_from=datetime.now(UTC) - timedelta(minutes=1),
            total_redemption_limit=1,
            created_by=actor.id,
        )
        session.add(promotion)
        await session.flush()
        coupon = Coupon(
            promotion_id=promotion.id,
            coupon_code_normalized=f"ONLY-{suffix.upper()}",
            display_code=f"ONLY-{suffix.upper()}",
            status="active",
            total_redemption_limit=1,
        )
        session.add(coupon)
        await session.flush()
        quotes: list[PricingQuote] = []
        for _ in range(2):
            quote = PricingQuote(
                anonymous_session_id=uuid4(),
                sku_id=sku.id,
                price_id=price.id,
                price_book_id=book.id,
                quantity=1,
                currency_code="USD",
                unit_amount_minor=1000,
                subtotal_minor=1000,
                discount_total_minor=100,
                total_minor=900,
                calculation_snapshot={
                    "discounts": [
                        {
                            "promotion_id": str(promotion.id),
                            "discount_amount_minor": 100,
                        }
                    ]
                },
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
            session.add(quote)
            quotes.append(quote)
        await session.commit()
        return coupon, promotion, quotes


@pytest.mark.asyncio
async def test_coupon_global_limit_is_concurrency_safe() -> None:
    coupon, promotion, quotes = await create_limited_coupon_quotes()

    async def attempt(quote: PricingQuote) -> str:
        async with session_factory() as session:
            try:
                await coupon_redemption_service.reserve(
                    session,
                    pricing_quote_id=quote.id,
                    promotion_id=promotion.id,
                    coupon_id=coupon.id,
                    user_id=None,
                )
                return "success"
            except VavError as error:
                return error.code

    outcomes = await asyncio.gather(*(attempt(quote) for quote in quotes))
    assert sorted(outcomes) == ["COUPON_NOT_APPLICABLE", "success"]
