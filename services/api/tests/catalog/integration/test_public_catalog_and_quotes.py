from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from vav.core.database import session_factory
from vav.main import app
from vav.models.catalog import (
    Price,
    PriceBook,
    Product,
    ProductLocalization,
    ProductSku,
    SupportedCurrency,
)
from vav.models.identity import User
from vav.modules.catalog.pricing import pricing_engine
from vav.modules.identity.domain import UserStatus


async def create_sellable_product(
    *,
    status: str = "active",
    inventory_policy: str = "unlimited",
) -> tuple[Product, ProductSku, str]:
    suffix = uuid4().hex
    async with session_factory() as session:
        actor = User(
            email=f"catalog-{suffix}@example.com",
            display_email=f"catalog-{suffix}@example.com",
            password_hash=None,
            status=UserStatus.SUSPENDED,
        )
        session.add(actor)
        await session.flush()
        product = Product(
            product_code=f"TEST-{suffix.upper()}",
            product_type="digital_service",
            fulfillment_type="digital_access",
            internal_name="Internal integration product",
            status=status,
            visibility="public",
            default_locale="zh-CN",
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(product)
        await session.flush()
        slug = f"catalog-{suffix}"
        session.add(
            ProductLocalization(
                product_id=product.id,
                locale="zh-CN",
                slug=slug,
                name="测试服务",
                short_description="用于目录集成测试",
                description_blocks=[],
                translation_status="ready",
            )
        )
        sku = ProductSku(
            product_id=product.id,
            sku_code=f"SKU-{suffix.upper()}",
            internal_name="Internal SKU",
            billing_type="one_time",
            status="active",
            fulfillment_configuration={"service_code": f"test-{suffix}"},
            inventory_policy=inventory_policy,
        )
        session.add(sku)
        await session.flush()
        currency = await session.get(SupportedCurrency, "USD")
        if currency is None:
            session.add(
                SupportedCurrency(currency_code="USD", exponent=2, enabled=True, display_order=10)
            )
        book = await session.scalar(
            select(PriceBook).where(PriceBook.price_book_code == "GLOBAL_STANDARD")
        )
        if book is None:
            book = PriceBook(
                price_book_code="GLOBAL_STANDARD",
                name="Global standard",
                status="active",
                priority=0,
            )
            session.add(book)
            await session.flush()
        session.add(
            Price(
                sku_id=sku.id,
                price_book_id=book.id,
                currency_code="USD",
                unit_amount_minor=1999,
                billing_type="one_time",
                valid_from=datetime.now(UTC) - timedelta(minutes=1),
                status="active",
                created_by=actor.id,
            )
        )
        await session.commit()
        return product, sku, slug


@pytest.mark.asyncio
async def test_public_catalog_exposes_only_safe_sellable_fields() -> None:
    product, _, slug = await create_sellable_product()

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/public/catalog/products/{slug}",
            params={"locale": "zh-CN", "currency": "USD"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == str(product.id)
    assert data["name"] == "测试服务"
    assert data["skus"][0]["prices"][0]["unit_amount_minor"] == 1999
    assert "internal_name" not in data
    assert "fulfillment_configuration" not in data["skus"][0]


@pytest.mark.asyncio
async def test_draft_product_is_hidden_from_public_catalog() -> None:
    _, _, slug = await create_sellable_product(status="draft")
    with TestClient(app) as client:
        response = client.get(f"/api/v1/public/catalog/products/{slug}", params={"locale": "zh-CN"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pricing_quote_is_exact_snapshot_not_payment_proof() -> None:
    _, sku, _ = await create_sellable_product()
    anonymous_session_id = uuid4()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/public/catalog/pricing/quote",
            json={
                "sku_id": str(sku.id),
                "quantity": 2,
                "requested_currency": "USD",
                "locale": "zh-CN",
                "anonymous_session_id": str(anonymous_session_id),
                "pricing_context": {
                    "channel": "user_web",
                    "requested_at": datetime.now(UTC).isoformat(),
                },
            },
        )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["subtotal_minor"] == 3998
    assert data["total_minor"] == 3998
    assert data["payment_status"] == "not_paid"
    assert data["grants_entitlement"] is False


@pytest.mark.asyncio
async def test_missing_explicit_currency_fails_with_available_options() -> None:
    _, sku, _ = await create_sellable_product()
    async with session_factory() as session:
        with pytest.raises(Exception) as raised:
            await pricing_engine.calculate(
                session,
                sku_id=sku.id,
                quantity=1,
                currency="HKD",
                requested_at=datetime.now(UTC),
                region_code=None,
                customer_segment=None,
                coupon_code=None,
                user_id=None,
            )
    error = raised.value
    assert getattr(error, "code", None) == "PRICE_NOT_AVAILABLE_IN_CURRENCY"
    assert error.details == [{"available_currencies": ["USD"]}]
