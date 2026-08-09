# ruff: noqa: B008

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.database import get_redis
from vav.core.request_context import request_id_from_request
from vav.models.catalog import (
    Coupon,
    InventoryItem,
    InventoryMovement,
    Price,
    PriceBook,
    PricingQuote,
    Product,
    ProductCategory,
    ProductCategoryLocalization,
    ProductLocalization,
    ProductSku,
    Promotion,
    SupportedCurrency,
)
from vav.models.content import MediaAsset, MediaAssetLocalization
from vav.modules.catalog.domain import (
    BillingType,
    InventoryPolicy,
    ProductStatus,
    ProductType,
    PromotionBenefits,
    PromotionRules,
    SkuStatus,
    validate_fulfillment,
)
from vav.modules.catalog.inventory import (
    availability_payload,
    inventory_service,
)
from vav.modules.catalog.pricing import pricing_engine, quote_payload
from vav.modules.catalog.promotions import coupon_redemption_service
from vav.modules.catalog.schemas import (
    CategoryCreateRequest,
    CouponBulkCreateRequest,
    CouponCreateRequest,
    CouponRedemptionReservationRequest,
    CouponUpdateRequest,
    CouponValidationRequest,
    InventoryAdjustRequest,
    InventoryConfigureRequest,
    InventoryReservationRequest,
    PriceBookCreateRequest,
    PriceBookUpdateRequest,
    PriceCreateRequest,
    PriceSupersedeRequest,
    PricingQuoteRequest,
    PricingSimulationRequest,
    ProductCreateRequest,
    ProductLocalizationUpdateRequest,
    ProductUpdateRequest,
    PromotionCreateRequest,
    PromotionUpdateRequest,
    ReasonRequest,
    SkuCreateRequest,
    SkuUpdateRequest,
)
from vav.modules.identity.abuse import enforce_rate_limit
from vav.modules.identity.audit import record_security_event
from vav.modules.identity.dependencies import AuthenticatedPrincipal, request_fingerprint
from vav.modules.identity.permissions import require_permission

router = APIRouter()


async def _bump_catalog_version() -> None:
    await get_redis().incr("catalog:version")


def _window_active(starts_at: datetime | None, ends_at: datetime | None, at: datetime) -> bool:
    return (starts_at is None or starts_at <= at) and (ends_at is None or ends_at > at)


async def _localization(
    session: AsyncSession, product_id: UUID, locale: str, fallback_locale: str = "zh-CN"
) -> tuple[ProductLocalization | None, bool]:
    localization = await session.scalar(
        select(ProductLocalization).where(
            ProductLocalization.product_id == product_id,
            ProductLocalization.locale == locale,
            ProductLocalization.translation_status == "ready",
        )
    )
    if localization is not None:
        return localization, False
    fallback = await session.scalar(
        select(ProductLocalization).where(
            ProductLocalization.product_id == product_id,
            ProductLocalization.locale == fallback_locale,
            ProductLocalization.translation_status == "ready",
        )
    )
    return fallback, fallback is not None


async def _public_product_payload(
    session: AsyncSession,
    product: Product,
    *,
    locale: str,
    currency: str | None,
    at: datetime,
) -> dict[str, object]:
    payloads = await _public_product_payloads(
        session, [product], locale=locale, currency=currency, at=at
    )
    payload = payloads.get(product.id)
    if payload is None:
        raise VavError(
            "CATALOG_TRANSLATION_UNAVAILABLE",
            "Product translation is unavailable.",
            status_code=404,
        )
    return payload


def _serialize_public_product(
    product: Product,
    *,
    localized: ProductLocalization,
    fallback_used: bool,
    skus: list[ProductSku],
    prices_by_sku: dict[UUID, list[Price]],
    inventory_by_sku: dict[UUID, InventoryItem],
    at: datetime,
) -> dict[str, object]:
    public_skus: list[dict[str, object]] = []
    for sku in skus:
        if not _window_active(sku.purchasable_from, sku.purchasable_until, at):
            continue
        prices = prices_by_sku.get(sku.id, [])
        public_skus.append(
            {
                "id": str(sku.id),
                "sku_code": sku.sku_code,
                "billing_type": sku.billing_type,
                "service_quantity": sku.service_quantity,
                "service_unit": sku.service_unit,
                "entitlement_definition": sku.entitlement_definition,
                "purchase_limit_per_user": sku.purchase_limit_per_user,
                "prices": [
                    {
                        "price_id": str(price.id),
                        "currency": price.currency_code,
                        "unit_amount_minor": price.unit_amount_minor,
                        "compare_at_amount_minor": price.compare_at_amount_minor,
                        "billing_type": price.billing_type,
                        "billing_interval": price.billing_interval,
                        "billing_interval_count": price.billing_interval_count,
                    }
                    for price in prices
                ],
                "availability": availability_payload(inventory_by_sku.get(sku.id)),
            }
        )
    return {
        "id": str(product.id),
        "product_code": product.product_code,
        "product_type": product.product_type,
        "fulfillment_type": product.fulfillment_type,
        "category_id": str(product.category_id) if product.category_id else None,
        "featured": product.featured,
        "purchasable_from": (
            product.purchasable_from.isoformat() if product.purchasable_from else None
        ),
        "purchasable_until": (
            product.purchasable_until.isoformat() if product.purchasable_until else None
        ),
        "locale": localized.locale,
        "fallback_used": fallback_used,
        "slug": localized.slug,
        "name": localized.name,
        "short_description": localized.short_description,
        "description_blocks": localized.description_blocks,
        "seo_title": localized.seo_title,
        "seo_description": localized.seo_description,
        "cover_media_id": (str(localized.cover_media_id) if localized.cover_media_id else None),
        "skus": public_skus,
    }


async def _public_product_payloads(
    session: AsyncSession,
    products: list[Product],
    *,
    locale: str,
    currency: str | None,
    at: datetime,
) -> dict[UUID, dict[str, object]]:
    if not products:
        return {}
    product_ids = [product.id for product in products]
    localizations = list(
        (
            await session.scalars(
                select(ProductLocalization).where(
                    ProductLocalization.product_id.in_(product_ids),
                    ProductLocalization.locale.in_((locale, "zh-CN")),
                    ProductLocalization.translation_status == "ready",
                )
            )
        ).all()
    )
    localization_by_product: dict[UUID, tuple[ProductLocalization, bool]] = {}
    for value in localizations:
        current = localization_by_product.get(value.product_id)
        if current is None or (value.locale == locale and current[0].locale != locale):
            localization_by_product[value.product_id] = (value, value.locale != locale)

    skus = list(
        (
            await session.scalars(
                select(ProductSku)
                .where(
                    ProductSku.product_id.in_(product_ids),
                    ProductSku.status == SkuStatus.ACTIVE,
                )
                .order_by(ProductSku.product_id, ProductSku.created_at, ProductSku.id)
            )
        ).all()
    )
    skus_by_product: dict[UUID, list[ProductSku]] = {}
    for sku in skus:
        skus_by_product.setdefault(sku.product_id, []).append(sku)
    sku_ids = [sku.id for sku in skus]
    prices_by_sku: dict[UUID, list[Price]] = {}
    inventory_by_sku: dict[UUID, InventoryItem] = {}
    if sku_ids:
        price_query = (
            select(Price)
            .join(PriceBook, PriceBook.id == Price.price_book_id)
            .where(
                Price.sku_id.in_(sku_ids),
                Price.status == "active",
                Price.valid_from <= at,
                or_(Price.valid_until.is_(None), Price.valid_until > at),
                PriceBook.status == "active",
                or_(PriceBook.valid_from.is_(None), PriceBook.valid_from <= at),
                or_(PriceBook.valid_until.is_(None), PriceBook.valid_until > at),
            )
            .order_by(Price.sku_id, Price.currency_code, Price.unit_amount_minor, Price.id)
        )
        if currency:
            price_query = price_query.where(Price.currency_code == currency.upper())
        for price in (await session.scalars(price_query)).all():
            prices_by_sku.setdefault(price.sku_id, []).append(price)
        inventory_by_sku = {
            item.sku_id: item
            for item in (
                await session.scalars(
                    select(InventoryItem).where(InventoryItem.sku_id.in_(sku_ids))
                )
            ).all()
        }
    return {
        product.id: _serialize_public_product(
            product,
            localized=localization_by_product[product.id][0],
            fallback_used=localization_by_product[product.id][1],
            skus=skus_by_product.get(product.id, []),
            prices_by_sku=prices_by_sku,
            inventory_by_sku=inventory_by_sku,
            at=at,
        )
        for product in products
        if product.id in localization_by_product
    }


async def _admin_product_payload(session: AsyncSession, product: Product) -> dict[str, object]:
    localizations = list(
        (
            await session.scalars(
                select(ProductLocalization)
                .where(ProductLocalization.product_id == product.id)
                .order_by(ProductLocalization.locale)
            )
        ).all()
    )
    sku_count = len(
        (
            await session.scalars(select(ProductSku.id).where(ProductSku.product_id == product.id))
        ).all()
    )
    return {
        "id": str(product.id),
        "product_code": product.product_code,
        "product_type": product.product_type,
        "fulfillment_type": product.fulfillment_type,
        "internal_name": product.internal_name,
        "status": product.status,
        "visibility": product.visibility,
        "default_locale": product.default_locale,
        "category_id": str(product.category_id) if product.category_id else None,
        "purchasable_from": (
            product.purchasable_from.isoformat() if product.purchasable_from else None
        ),
        "purchasable_until": (
            product.purchasable_until.isoformat() if product.purchasable_until else None
        ),
        "featured": product.featured,
        "sort_order": product.sort_order,
        "metadata": product.product_metadata,
        "version": product.version,
        "sku_count": sku_count,
        "updated_at": product.updated_at.isoformat(),
        "localizations": {
            item.locale: {
                "slug": item.slug,
                "name": item.name,
                "short_description": item.short_description,
                "description_blocks": item.description_blocks,
                "seo_title": item.seo_title,
                "seo_description": item.seo_description,
                "cover_media_id": str(item.cover_media_id) if item.cover_media_id else None,
                "translation_status": item.translation_status,
            }
            for item in localizations
        },
    }


def _sku_payload(sku: ProductSku) -> dict[str, object]:
    return {
        "id": str(sku.id),
        "product_id": str(sku.product_id),
        "sku_code": sku.sku_code,
        "internal_name": sku.internal_name,
        "billing_type": sku.billing_type,
        "status": sku.status,
        "service_quantity": sku.service_quantity,
        "service_unit": sku.service_unit,
        "entitlement_definition": sku.entitlement_definition,
        "fulfillment_configuration": sku.fulfillment_configuration,
        "inventory_policy": sku.inventory_policy,
        "purchase_limit_per_user": sku.purchase_limit_per_user,
        "purchase_limit_total": sku.purchase_limit_total,
        "purchasable_from": (sku.purchasable_from.isoformat() if sku.purchasable_from else None),
        "purchasable_until": (sku.purchasable_until.isoformat() if sku.purchasable_until else None),
        "version": sku.version,
    }


def _price_payload(price: Price) -> dict[str, object]:
    return {
        "id": str(price.id),
        "sku_id": str(price.sku_id),
        "price_book_id": str(price.price_book_id),
        "currency_code": price.currency_code,
        "unit_amount_minor": price.unit_amount_minor,
        "compare_at_amount_minor": price.compare_at_amount_minor,
        "billing_type": price.billing_type,
        "billing_interval": price.billing_interval,
        "billing_interval_count": price.billing_interval_count,
        "tax_behavior": price.tax_behavior,
        "valid_from": price.valid_from.isoformat(),
        "valid_until": price.valid_until.isoformat() if price.valid_until else None,
        "status": price.status,
        "external_price_references": price.external_price_references,
        "supersedes_price_id": (
            str(price.supersedes_price_id) if price.supersedes_price_id else None
        ),
    }


def _inventory_payload(item: InventoryItem) -> dict[str, object]:
    return {
        "id": str(item.id),
        "sku_id": str(item.sku_id),
        "inventory_policy": item.inventory_policy,
        "total_capacity": item.total_capacity,
        "reserved_quantity": item.reserved_quantity,
        "sold_quantity": item.sold_quantity,
        "safety_stock": item.safety_stock,
        "overselling_allowed": item.overselling_allowed,
        "oversell_limit": item.oversell_limit,
        "version": item.version,
        **availability_payload(item),
    }


@router.get("/public/catalog/categories")
async def public_categories(
    request: Request,
    locale: str = "zh-CN",
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(ProductCategory, ProductCategoryLocalization)
            .join(
                ProductCategoryLocalization,
                ProductCategoryLocalization.category_id == ProductCategory.id,
            )
            .where(
                ProductCategory.status == "active",
                ProductCategoryLocalization.locale == locale,
            )
            .order_by(ProductCategory.sort_order, ProductCategory.category_code)
        )
    ).all()
    return success(
        {
            "items": [
                {
                    "id": str(category.id),
                    "code": category.category_code,
                    "parent_id": str(category.parent_id) if category.parent_id else None,
                    "slug": localized.slug,
                    "name": localized.name,
                    "description": localized.description,
                }
                for category, localized in rows
            ]
        },
        request_id_from_request(request),
    )


@router.get("/public/catalog/currencies")
async def public_currencies(
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    currencies = list(
        (
            await session.scalars(
                select(SupportedCurrency)
                .where(SupportedCurrency.enabled.is_(True))
                .order_by(
                    SupportedCurrency.display_order,
                    SupportedCurrency.currency_code,
                )
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "currency_code": currency.currency_code,
                    "exponent": currency.exponent,
                }
                for currency in currencies
            ]
        },
        request_id_from_request(request),
    )


@router.get("/public/catalog/categories/{slug}")
async def public_category(
    slug: str,
    request: Request,
    locale: str = "zh-CN",
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        await session.execute(
            select(ProductCategory, ProductCategoryLocalization)
            .join(
                ProductCategoryLocalization,
                ProductCategoryLocalization.category_id == ProductCategory.id,
            )
            .where(
                ProductCategory.status == "active",
                ProductCategoryLocalization.locale == locale,
                ProductCategoryLocalization.slug == slug,
            )
        )
    ).one_or_none()
    if row is None:
        raise VavError("CATALOG_CATEGORY_NOT_FOUND", "Category was not found.", status_code=404)
    category, localized = row
    return success(
        {
            "id": str(category.id),
            "code": category.category_code,
            "slug": localized.slug,
            "name": localized.name,
            "description": localized.description,
        },
        request_id_from_request(request),
    )


@router.get("/public/catalog/products")
async def public_products(
    request: Request,
    locale: str = "zh-CN",
    category: str | None = None,
    product_type: str | None = None,
    currency: str | None = None,
    featured: bool | None = None,
    available_only: bool = False,
    purchasable_at: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: str = "featured",
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    at = purchasable_at or datetime.now(UTC)
    query = select(Product).where(
        Product.status == ProductStatus.ACTIVE,
        Product.visibility == "public",
        or_(Product.purchasable_from.is_(None), Product.purchasable_from <= at),
        or_(Product.purchasable_until.is_(None), Product.purchasable_until > at),
    )
    if product_type:
        query = query.where(Product.product_type == product_type)
    if featured is not None:
        query = query.where(Product.featured == featured)
    if category:
        category_id = await session.scalar(
            select(ProductCategory.id)
            .join(
                ProductCategoryLocalization,
                ProductCategoryLocalization.category_id == ProductCategory.id,
            )
            .where(
                ProductCategoryLocalization.locale == locale,
                ProductCategoryLocalization.slug == category,
            )
        )
        if category_id is None:
            return success(
                {"items": [], "page": page, "page_size": page_size},
                request_id_from_request(request),
            )
        query = query.where(Product.category_id == category_id)
    order = (
        (Product.sort_order, Product.updated_at.desc())
        if sort == "featured"
        else (Product.updated_at.desc(), Product.id)
    )
    products = list(
        (
            await session.scalars(
                query.order_by(*order).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    payloads = await _public_product_payloads(
        session, products, locale=locale, currency=currency, at=at
    )
    items: list[dict[str, object]] = []
    for product in products:
        payload = payloads.get(product.id)
        if payload is None:
            continue
        if available_only:
            public_skus = payload.get("skus")
            has_availability = False
            if isinstance(public_skus, list):
                for public_sku in public_skus:
                    if not isinstance(public_sku, dict):
                        continue
                    availability = public_sku.get("availability")
                    if isinstance(availability, dict) and availability.get("status") in {
                        "available",
                        "low_stock",
                    }:
                        has_availability = True
                        break
            if not has_availability:
                continue
        items.append(payload)
    return success(
        {"items": items, "page": page, "page_size": page_size},
        request_id_from_request(request),
    )


@router.get("/public/catalog/products/{slug}")
async def public_product(
    slug: str,
    request: Request,
    locale: str = "zh-CN",
    currency: str | None = None,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    product = await session.scalar(
        select(Product)
        .join(ProductLocalization, ProductLocalization.product_id == Product.id)
        .where(
            Product.status == ProductStatus.ACTIVE,
            Product.visibility == "public",
            ProductLocalization.locale == locale,
            ProductLocalization.slug == slug,
        )
    )
    if product is None:
        raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    payload = await _public_product_payload(
        session, product, locale=locale, currency=currency, at=datetime.now(UTC)
    )
    return success(payload, request_id_from_request(request))


@router.get("/public/catalog/products/{product_id}/availability")
async def public_product_availability(
    product_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    product = await session.get(Product, product_id)
    if product is None or product.status != ProductStatus.ACTIVE or product.visibility != "public":
        raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    skus = list(
        (
            await session.scalars(
                select(ProductSku).where(
                    ProductSku.product_id == product.id,
                    ProductSku.status == SkuStatus.ACTIVE,
                )
            )
        ).all()
    )
    items: list[dict[str, object]] = []
    for sku in skus:
        inventory = await session.scalar(
            select(InventoryItem).where(InventoryItem.sku_id == sku.id)
        )
        items.append({"sku_id": str(sku.id), **availability_payload(inventory)})
    return success({"items": items}, request_id_from_request(request))


@router.post("/public/catalog/pricing/quote", status_code=201)
async def create_pricing_quote(
    payload: PricingQuoteRequest,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    ip_hash, _ = request_fingerprint(request)
    await enforce_rate_limit(f"rate:pricing:ip:{ip_hash}", limit=60, window_seconds=3600)
    calculation = await pricing_engine.calculate(
        session,
        sku_id=payload.sku_id,
        quantity=payload.quantity,
        currency=payload.requested_currency,
        requested_at=payload.pricing_context.requested_at,
        region_code=payload.pricing_context.region_code,
        customer_segment=payload.pricing_context.customer_segment,
        coupon_code=payload.coupon_code,
        user_id=None,
    )
    quote = await pricing_engine.create_quote(
        session,
        calculation,
        anonymous_session_id=payload.anonymous_session_id,
    )
    return success(quote_payload(quote), request_id_from_request(request))


@router.get("/public/catalog/pricing/quotes/{quote_id}")
async def get_pricing_quote(
    quote_id: UUID,
    request: Request,
    anonymous_session_id: UUID,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    quote = await session.get(PricingQuote, quote_id)
    if quote is None or quote.anonymous_session_id != anonymous_session_id:
        raise VavError("PRICING_QUOTE_NOT_FOUND", "Quote was not found.", status_code=404)
    return success(quote_payload(quote), request_id_from_request(request))


@router.post("/public/catalog/coupons/validate")
async def validate_coupon(
    payload: CouponValidationRequest,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    ip_hash, _ = request_fingerprint(request)
    await enforce_rate_limit(f"rate:coupon:ip:{ip_hash}", limit=10, window_seconds=3600)
    try:
        calculation = await pricing_engine.calculate(
            session,
            sku_id=payload.sku_id,
            quantity=payload.quantity,
            currency=payload.requested_currency,
            requested_at=datetime.now(UTC),
            region_code=None,
            customer_segment=None,
            coupon_code=payload.coupon_code,
            user_id=None,
        )
    except VavError as error:
        if error.code.startswith("COUPON_"):
            raise VavError(
                "COUPON_NOT_APPLICABLE",
                "The coupon cannot be applied to this quote.",
                status_code=409,
            ) from error
        raise
    return success(
        {
            "applicable": calculation.discount_total_minor > 0,
            "discount_total_minor": calculation.discount_total_minor,
            "currency": calculation.currency,
            "total_minor": calculation.total_minor,
        },
        request_id_from_request(request),
    )


@router.get("/admin/catalog/categories")
async def admin_categories(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.products.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    categories = list(
        (
            await session.scalars(
                select(ProductCategory).order_by(
                    ProductCategory.sort_order, ProductCategory.category_code
                )
            )
        ).all()
    )
    items: list[dict[str, object]] = []
    for category in categories:
        localizations = list(
            (
                await session.scalars(
                    select(ProductCategoryLocalization)
                    .where(ProductCategoryLocalization.category_id == category.id)
                    .order_by(ProductCategoryLocalization.locale)
                )
            ).all()
        )
        items.append(
            {
                "id": str(category.id),
                "category_code": category.category_code,
                "parent_id": str(category.parent_id) if category.parent_id else None,
                "internal_name": category.internal_name,
                "status": category.status,
                "sort_order": category.sort_order,
                "localizations": {
                    item.locale: {
                        "name": item.name,
                        "description": item.description,
                        "slug": item.slug,
                    }
                    for item in localizations
                },
            }
        )
    return success({"items": items}, request_id_from_request(request))


@router.post("/admin/catalog/categories", status_code=201)
async def create_category(
    payload: CategoryCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.products.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.parent_id and await session.get(ProductCategory, payload.parent_id) is None:
        raise VavError(
            "CATALOG_PARENT_CATEGORY_NOT_FOUND",
            "Parent category was not found.",
            status_code=404,
        )
    category = ProductCategory(
        category_code=payload.category_code,
        parent_id=payload.parent_id,
        internal_name=payload.internal_name,
        sort_order=payload.sort_order,
    )
    session.add(category)
    await session.flush()
    for localized in payload.localizations:
        session.add(ProductCategoryLocalization(category_id=category.id, **localized.model_dump()))
    record_security_event(
        session,
        event_type="catalog.category.created",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="product_category",
        target_id=category.id,
    )
    await session.commit()
    await _bump_catalog_version()
    return success({"id": str(category.id)}, request_id_from_request(request))


@router.get("/admin/catalog/products")
async def admin_products(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.products.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    products = list(
        (
            await session.scalars(
                select(Product)
                .order_by(Product.updated_at.desc(), Product.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        {
            "items": [await _admin_product_payload(session, product) for product in products],
            "page": page,
            "page_size": page_size,
        },
        request_id_from_request(request),
    )


@router.post("/admin/catalog/products", status_code=201)
async def create_product(
    payload: ProductCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.products.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.category_id and await session.get(ProductCategory, payload.category_id) is None:
        raise VavError("CATALOG_CATEGORY_NOT_FOUND", "Category was not found.", status_code=404)
    product = Product(
        product_code=payload.product_code,
        product_type=payload.product_type,
        fulfillment_type=payload.fulfillment_type,
        internal_name=payload.internal_name,
        visibility=payload.visibility,
        default_locale=payload.default_locale,
        category_id=payload.category_id,
        purchasable_from=payload.purchasable_from,
        purchasable_until=payload.purchasable_until,
        featured=payload.featured,
        sort_order=payload.sort_order,
        product_metadata=payload.metadata,
        created_by=principal.user.id,
        updated_by=principal.user.id,
    )
    session.add(product)
    await session.flush()
    for localized in payload.localizations:
        localization_data = localized.model_dump(mode="json")
        localization_data["description_blocks"] = [
            block.model_dump(mode="json") for block in localized.description_blocks
        ]
        session.add(ProductLocalization(product_id=product.id, **localization_data))
    record_security_event(
        session,
        event_type="catalog.product.created",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="product",
        target_id=product.id,
        after_state={"status": product.status, "product_code": product.product_code},
    )
    await session.commit()
    return success(
        await _admin_product_payload(session, product),
        request_id_from_request(request),
    )


@router.get("/admin/catalog/products/{product_id}")
async def get_admin_product(
    product_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.products.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    product = await session.get(Product, product_id)
    if product is None:
        raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    return success(
        await _admin_product_payload(session, product),
        request_id_from_request(request),
    )


@router.patch("/admin/catalog/products/{product_id}")
async def update_product(
    product_id: UUID,
    payload: ProductUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.products.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    if product.version != payload.expected_version:
        raise VavError(
            "CATALOG_VERSION_CONFLICT",
            "Product changed since it was loaded.",
            status_code=409,
        )
    before = await _admin_product_payload(session, product)
    for field in (
        "internal_name",
        "visibility",
        "category_id",
        "purchasable_from",
        "purchasable_until",
        "featured",
        "sort_order",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(product, field, value)
    if payload.metadata is not None:
        product.product_metadata = payload.metadata
    if (
        product.purchasable_from
        and product.purchasable_until
        and product.purchasable_until <= product.purchasable_from
    ):
        raise VavError(
            "CATALOG_PURCHASE_WINDOW_INVALID",
            "Purchase end must follow purchase start.",
            status_code=422,
        )
    if product.status == ProductStatus.ACTIVE:
        product.status = ProductStatus.IN_REVIEW
    product.updated_by = principal.user.id
    product.version += 1
    record_security_event(
        session,
        event_type="catalog.product.updated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="product",
        target_id=product.id,
        reason=payload.reason,
        before_state=before,
        after_state={"version": product.version, "status": product.status},
    )
    await session.commit()
    await session.refresh(product)
    await _bump_catalog_version()
    return success(
        await _admin_product_payload(session, product),
        request_id_from_request(request),
    )


@router.put("/admin/catalog/products/{product_id}/localizations/{locale}")
async def update_product_localization(
    product_id: UUID,
    locale: str,
    payload: ProductLocalizationUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.products.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.locale != locale:
        raise VavError("LOCALE_MISMATCH", "Locale path and payload must match.")
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    if product.version != payload.expected_version:
        raise VavError(
            "CATALOG_VERSION_CONFLICT",
            "Product changed since it was loaded.",
            status_code=409,
        )
    localized = await session.scalar(
        select(ProductLocalization).where(
            ProductLocalization.product_id == product.id,
            ProductLocalization.locale == locale,
        )
    )
    values = payload.model_dump(exclude={"expected_version", "reason", "locale"}, mode="json")
    values["description_blocks"] = [
        block.model_dump(mode="json") for block in payload.description_blocks
    ]
    if localized is None:
        localized = ProductLocalization(product_id=product.id, locale=locale, **values)
        session.add(localized)
    else:
        for field, value in values.items():
            setattr(localized, field, value)
    product.version += 1
    product.updated_by = principal.user.id
    if product.status == ProductStatus.ACTIVE:
        product.status = ProductStatus.IN_REVIEW
    record_security_event(
        session,
        event_type="catalog.product.updated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="product",
        target_id=product.id,
        reason=payload.reason,
        metadata={"locale": locale},
    )
    await session.commit()
    await session.refresh(product)
    await _bump_catalog_version()
    return success(
        await _admin_product_payload(session, product),
        request_id_from_request(request),
    )


async def _validate_product_for_publish(session: AsyncSession, product: Product) -> list[str]:
    errors: list[str] = []
    ready_localizations = list(
        (
            await session.scalars(
                select(ProductLocalization).where(
                    ProductLocalization.product_id == product.id,
                    ProductLocalization.translation_status == "ready",
                )
            )
        ).all()
    )
    if not ready_localizations:
        errors.append("At least one READY localization is required.")
    for localization in ready_localizations:
        references: list[tuple[UUID, bool]] = []
        if localization.cover_media_id:
            references.append((localization.cover_media_id, False))
        for block in localization.description_blocks:
            if block.get("type") != "image":
                continue
            data = block.get("data")
            if not isinstance(data, dict) or not data.get("media_id"):
                continue
            try:
                references.append(
                    (
                        UUID(str(data["media_id"])),
                        bool(data.get("decorative", False)),
                    )
                )
            except ValueError:
                errors.append(f"{localization.locale}: invalid media reference.")
        for media_id, decorative in references:
            asset = await session.get(MediaAsset, media_id)
            if (
                asset is None
                or asset.deleted_at is not None
                or asset.processing_status != "ready"
                or asset.visibility != "public"
            ):
                errors.append(f"{localization.locale}: media {media_id} is not public and ready.")
                continue
            if not decorative:
                metadata = await session.get(
                    MediaAssetLocalization,
                    (media_id, localization.locale),
                )
                if metadata is None or not (metadata.alt_text or "").strip():
                    errors.append(f"{localization.locale}: media {media_id} requires alt text.")
    skus = list(
        (
            await session.scalars(
                select(ProductSku).where(
                    ProductSku.product_id == product.id,
                    ProductSku.status == SkuStatus.ACTIVE,
                )
            )
        ).all()
    )
    if not skus:
        errors.append("At least one ACTIVE SKU is required.")
    now = datetime.now(UTC)
    for sku in skus:
        if sku.billing_type != BillingType.FREE:
            price = await session.scalar(
                select(Price.id).where(
                    Price.sku_id == sku.id,
                    Price.status == "active",
                    Price.valid_from <= now,
                    or_(Price.valid_until.is_(None), Price.valid_until > now),
                )
            )
            if price is None:
                errors.append(f"SKU {sku.sku_code} requires an active price.")
        if sku.inventory_policy in {
            InventoryPolicy.FINITE,
            InventoryPolicy.SERVICE_CAPACITY,
        }:
            inventory = await session.scalar(
                select(InventoryItem.id).where(InventoryItem.sku_id == sku.id)
            )
            if inventory is None:
                errors.append(f"SKU {sku.sku_code} requires inventory configuration.")
    localizations = list(
        (
            await session.scalars(
                select(ProductLocalization).where(
                    ProductLocalization.product_id == product.id,
                    ProductLocalization.translation_status == "ready",
                )
            )
        ).all()
    )
    for localized in localizations:
        if localized.cover_media_id:
            media = await session.get(MediaAsset, localized.cover_media_id)
            if (
                media is None
                or media.visibility != "public"
                or media.processing_status != "ready"
                or media.deleted_at is not None
            ):
                errors.append(f"Localization {localized.locale} uses inaccessible cover media.")
    return errors


@router.post("/admin/catalog/products/{product_id}/submit-review")
async def submit_product_review(
    product_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.products.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    if product.status not in {ProductStatus.DRAFT, ProductStatus.INACTIVE}:
        raise VavError(
            "CATALOG_STATE_TRANSITION_INVALID",
            "Only draft or inactive products can enter review.",
            status_code=409,
        )
    product.status = ProductStatus.IN_REVIEW
    product.updated_by = principal.user.id
    product.version += 1
    record_security_event(
        session,
        event_type="catalog.product.submitted_review",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="product",
        target_id=product.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"status": product.status}, request_id_from_request(request))


@router.post("/admin/catalog/products/{product_id}/publish")
async def publish_product(
    product_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.products.publish")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    if product.status != ProductStatus.IN_REVIEW:
        raise VavError(
            "CATALOG_STATE_TRANSITION_INVALID",
            "Only reviewed products can be published.",
            status_code=409,
        )
    errors = await _validate_product_for_publish(session, product)
    if errors:
        raise VavError(
            "CATALOG_PUBLICATION_VALIDATION_FAILED",
            "Product cannot be published.",
            status_code=409,
            details=[{"errors": errors}],
        )
    product.status = ProductStatus.ACTIVE
    product.updated_by = principal.user.id
    product.version += 1
    record_security_event(
        session,
        event_type="catalog.product.published",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="product",
        target_id=product.id,
        reason=payload.reason,
    )
    await session.commit()
    await _bump_catalog_version()
    return success({"status": product.status}, request_id_from_request(request))


async def _unpublish_or_archive_product(
    *,
    product_id: UUID,
    new_status: ProductStatus,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    before = product.status
    product.status = new_status
    product.updated_by = principal.user.id
    product.version += 1
    if new_status == ProductStatus.ARCHIVED:
        product.archived_at = datetime.now(UTC)
    record_security_event(
        session,
        event_type=(
            "catalog.product.archived"
            if new_status == ProductStatus.ARCHIVED
            else "catalog.product.unpublished"
        ),
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="product",
        target_id=product.id,
        reason=payload.reason,
        before_state={"status": before},
        after_state={"status": product.status},
    )
    await session.commit()
    await _bump_catalog_version()
    return success({"status": product.status}, request_id_from_request(request))


@router.post("/admin/catalog/products/{product_id}/unpublish")
async def unpublish_product(
    product_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.products.publish")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _unpublish_or_archive_product(
        product_id=product_id,
        new_status=ProductStatus.INACTIVE,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/catalog/products/{product_id}/archive")
async def archive_product(
    product_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.products.archive")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _unpublish_or_archive_product(
        product_id=product_id,
        new_status=ProductStatus.ARCHIVED,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.get("/admin/catalog/products/{product_id}/skus")
async def product_skus(
    product_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.skus.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    skus = list(
        (
            await session.scalars(
                select(ProductSku)
                .where(ProductSku.product_id == product_id)
                .order_by(ProductSku.created_at, ProductSku.id)
            )
        ).all()
    )
    return success(
        {"items": [_sku_payload(sku) for sku in skus]},
        request_id_from_request(request),
    )


@router.post("/admin/catalog/products/{product_id}/skus", status_code=201)
async def create_sku(
    product_id: UUID,
    payload: SkuCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.skus.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    product = await session.get(Product, product_id)
    if product is None:
        raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    configuration = validate_fulfillment(
        ProductType(product.product_type), payload.fulfillment_configuration
    )
    sku = ProductSku(
        product_id=product.id,
        sku_code=payload.sku_code,
        internal_name=payload.internal_name,
        billing_type=payload.billing_type,
        service_quantity=payload.service_quantity,
        service_unit=payload.service_unit,
        entitlement_definition=payload.entitlement_definition,
        fulfillment_configuration=configuration,
        inventory_policy=payload.inventory_policy,
        purchase_limit_per_user=payload.purchase_limit_per_user,
        purchase_limit_total=payload.purchase_limit_total,
        purchasable_from=payload.purchasable_from,
        purchasable_until=payload.purchasable_until,
    )
    session.add(sku)
    await session.flush()
    record_security_event(
        session,
        event_type="catalog.sku.created",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="product_sku",
        target_id=sku.id,
        metadata={"product_id": str(product.id)},
    )
    await session.commit()
    return success(_sku_payload(sku), request_id_from_request(request))


@router.get("/admin/catalog/skus/{sku_id}")
async def get_sku(
    sku_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.skus.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    sku = await session.get(ProductSku, sku_id)
    if sku is None:
        raise VavError("CATALOG_SKU_NOT_FOUND", "SKU was not found.", status_code=404)
    return success(_sku_payload(sku), request_id_from_request(request))


@router.patch("/admin/catalog/skus/{sku_id}")
async def update_sku(
    sku_id: UUID,
    payload: SkuUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.skus.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    sku = await session.scalar(select(ProductSku).where(ProductSku.id == sku_id).with_for_update())
    if sku is None:
        raise VavError("CATALOG_SKU_NOT_FOUND", "SKU was not found.", status_code=404)
    if sku.version != payload.expected_version:
        raise VavError(
            "CATALOG_VERSION_CONFLICT", "SKU changed since it was loaded.", status_code=409
        )
    product = await session.get(Product, sku.product_id)
    if product is None:
        raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
    before = _sku_payload(sku)
    for field in (
        "internal_name",
        "service_quantity",
        "service_unit",
        "purchase_limit_per_user",
        "purchase_limit_total",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(sku, field, value)
    if payload.entitlement_definition is not None:
        sku.entitlement_definition = payload.entitlement_definition
    if payload.fulfillment_configuration is not None:
        sku.fulfillment_configuration = validate_fulfillment(
            ProductType(product.product_type), payload.fulfillment_configuration
        )
    sku.version += 1
    if sku.status == SkuStatus.ACTIVE:
        sku.status = SkuStatus.DRAFT
    record_security_event(
        session,
        event_type="catalog.sku.updated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="product_sku",
        target_id=sku.id,
        reason=payload.reason,
        before_state=before,
        after_state=_sku_payload(sku),
    )
    await session.commit()
    await _bump_catalog_version()
    return success(_sku_payload(sku), request_id_from_request(request))


async def _set_sku_status(
    *,
    sku_id: UUID,
    active: bool,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    sku = await session.scalar(select(ProductSku).where(ProductSku.id == sku_id).with_for_update())
    if sku is None:
        raise VavError("CATALOG_SKU_NOT_FOUND", "SKU was not found.", status_code=404)
    if active:
        product = await session.get(Product, sku.product_id)
        if product is None:
            raise VavError("CATALOG_PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
        validate_fulfillment(ProductType(product.product_type), sku.fulfillment_configuration)
        if sku.inventory_policy in {
            InventoryPolicy.FINITE,
            InventoryPolicy.SERVICE_CAPACITY,
        }:
            inventory = await session.scalar(
                select(InventoryItem.id).where(InventoryItem.sku_id == sku.id)
            )
            if inventory is None:
                raise VavError(
                    "INVENTORY_NOT_CONFIGURED",
                    "Finite and service-capacity SKUs require inventory configuration.",
                    status_code=409,
                )
    sku.status = SkuStatus.ACTIVE if active else SkuStatus.INACTIVE
    sku.version += 1
    record_security_event(
        session,
        event_type=("catalog.sku.activated" if active else "catalog.sku.deactivated"),
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="product_sku",
        target_id=sku.id,
        reason=payload.reason,
    )
    await session.commit()
    await _bump_catalog_version()
    return success({"status": sku.status}, request_id_from_request(request))


@router.post("/admin/catalog/skus/{sku_id}/activate")
async def activate_sku(
    sku_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.skus.activate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _set_sku_status(
        sku_id=sku_id,
        active=True,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/catalog/skus/{sku_id}/deactivate")
async def deactivate_sku(
    sku_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.skus.activate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _set_sku_status(
        sku_id=sku_id,
        active=False,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.get("/admin/catalog/price-books")
async def price_books(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.price_books.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    books = list(
        (
            await session.scalars(
                select(PriceBook).order_by(PriceBook.priority.desc(), PriceBook.price_book_code)
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(book.id),
                    "price_book_code": book.price_book_code,
                    "name": book.name,
                    "region_code": book.region_code,
                    "customer_segment": book.customer_segment,
                    "status": book.status,
                    "valid_from": (book.valid_from.isoformat() if book.valid_from else None),
                    "valid_until": (book.valid_until.isoformat() if book.valid_until else None),
                    "priority": book.priority,
                }
                for book in books
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/catalog/price-books", status_code=201)
async def create_price_book(
    payload: PriceBookCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.price_books.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    book = PriceBook(**payload.model_dump())
    session.add(book)
    await session.flush()
    record_security_event(
        session,
        event_type="catalog.price_book.created",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="price_book",
        target_id=book.id,
    )
    await session.commit()
    return success({"id": str(book.id), "status": book.status}, request_id_from_request(request))


@router.patch("/admin/catalog/price-books/{book_id}")
async def update_price_book(
    book_id: UUID,
    payload: PriceBookUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.price_books.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    book = await session.scalar(select(PriceBook).where(PriceBook.id == book_id).with_for_update())
    if book is None:
        raise VavError("PRICE_BOOK_NOT_FOUND", "Price book was not found.", status_code=404)
    if book.status == "active":
        raise VavError(
            "PRICE_BOOK_ACTIVE_IMMUTABLE",
            "Deactivate the price book before changing resolution fields.",
            status_code=409,
        )
    for field, value in payload.model_dump(exclude={"reason"}, exclude_none=True).items():
        setattr(book, field, value)
    record_security_event(
        session,
        event_type="catalog.price_book.updated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="price_book",
        target_id=book.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"status": book.status}, request_id_from_request(request))


async def _set_price_book_status(
    *,
    book_id: UUID,
    active: bool,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    book = await session.scalar(select(PriceBook).where(PriceBook.id == book_id).with_for_update())
    if book is None:
        raise VavError("PRICE_BOOK_NOT_FOUND", "Price book was not found.", status_code=404)
    book.status = "active" if active else "inactive"
    record_security_event(
        session,
        event_type=("catalog.price_book.activated" if active else "catalog.price_book.deactivated"),
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="price_book",
        target_id=book.id,
        reason=payload.reason,
    )
    await session.commit()
    await _bump_catalog_version()
    return success({"status": book.status}, request_id_from_request(request))


@router.post("/admin/catalog/price-books/{book_id}/activate")
async def activate_price_book(
    book_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.price_books.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _set_price_book_status(
        book_id=book_id,
        active=True,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/catalog/price-books/{book_id}/deactivate")
async def deactivate_price_book(
    book_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.price_books.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _set_price_book_status(
        book_id=book_id,
        active=False,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.get("/admin/catalog/skus/{sku_id}/prices")
async def sku_prices(
    sku_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.prices.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    prices = list(
        (
            await session.scalars(
                select(Price)
                .where(Price.sku_id == sku_id)
                .order_by(Price.valid_from.desc(), Price.id)
            )
        ).all()
    )
    return success(
        {"items": [_price_payload(price) for price in prices]},
        request_id_from_request(request),
    )


@router.get("/admin/catalog/prices")
async def admin_prices(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.prices.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    prices = list(
        (await session.scalars(select(Price).order_by(Price.created_at.desc(), Price.id))).all()
    )
    return success(
        {"items": [_price_payload(price) for price in prices]},
        request_id_from_request(request),
    )


@router.post("/admin/catalog/skus/{sku_id}/prices", status_code=201)
async def create_price(
    sku_id: UUID,
    payload: PriceCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.prices.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    sku = await session.get(ProductSku, sku_id)
    book = await session.get(PriceBook, payload.price_book_id)
    currency = await session.get(SupportedCurrency, payload.currency_code)
    if sku is None:
        raise VavError("CATALOG_SKU_NOT_FOUND", "SKU was not found.", status_code=404)
    if book is None:
        raise VavError("PRICE_BOOK_NOT_FOUND", "Price book was not found.", status_code=404)
    if currency is None or not currency.enabled:
        raise VavError(
            "CURRENCY_NOT_SUPPORTED", "The requested currency is not supported.", status_code=422
        )
    if payload.billing_type != sku.billing_type:
        raise VavError(
            "PRICE_BILLING_TYPE_MISMATCH",
            "Price billing type must match the SKU billing type.",
            status_code=422,
        )
    values = payload.model_dump(exclude={"supersedes_price_id"})
    price = Price(
        sku_id=sku.id,
        created_by=principal.user.id,
        supersedes_price_id=payload.supersedes_price_id,
        **values,
    )
    session.add(price)
    await session.flush()
    record_security_event(
        session,
        event_type="catalog.price.created",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="price",
        target_id=price.id,
        after_state=_price_payload(price),
    )
    await session.commit()
    return success(_price_payload(price), request_id_from_request(request))


@router.get("/admin/catalog/prices/{price_id}")
async def get_price(
    price_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.prices.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    price = await session.get(Price, price_id)
    if price is None:
        raise VavError("PRICE_NOT_FOUND", "Price was not found.", status_code=404)
    return success(_price_payload(price), request_id_from_request(request))


def _windows_overlap(
    left_start: datetime,
    left_end: datetime | None,
    right_start: datetime,
    right_end: datetime | None,
) -> bool:
    return (left_end is None or right_start < left_end) and (
        right_end is None or left_start < right_end
    )


@router.post("/admin/catalog/prices/{price_id}/activate")
async def activate_price(
    price_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.prices.activate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    price = await session.scalar(select(Price).where(Price.id == price_id).with_for_update())
    if price is None:
        raise VavError("PRICE_NOT_FOUND", "Price was not found.", status_code=404)
    peers = list(
        (
            await session.scalars(
                select(Price).where(
                    Price.id != price.id,
                    Price.sku_id == price.sku_id,
                    Price.price_book_id == price.price_book_id,
                    Price.currency_code == price.currency_code,
                    Price.status == "active",
                )
            )
        ).all()
    )
    if any(
        _windows_overlap(price.valid_from, price.valid_until, peer.valid_from, peer.valid_until)
        for peer in peers
    ):
        raise VavError(
            "PRICE_VALIDITY_CONFLICT",
            "An active price already overlaps this validity window.",
            status_code=409,
        )
    price.status = "active"
    record_security_event(
        session,
        event_type="catalog.price.activated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="price",
        target_id=price.id,
        reason=payload.reason,
    )
    await session.commit()
    await _bump_catalog_version()
    return success({"status": price.status}, request_id_from_request(request))


@router.post("/admin/catalog/prices/{price_id}/expire")
async def expire_price(
    price_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.prices.expire")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    price = await session.scalar(select(Price).where(Price.id == price_id).with_for_update())
    if price is None:
        raise VavError("PRICE_NOT_FOUND", "Price was not found.", status_code=404)
    price.status = "expired"
    price.valid_until = min(price.valid_until or datetime.now(UTC), datetime.now(UTC))
    record_security_event(
        session,
        event_type="catalog.price.expired",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="price",
        target_id=price.id,
        reason=payload.reason,
    )
    await session.commit()
    await _bump_catalog_version()
    return success({"status": price.status}, request_id_from_request(request))


@router.post("/admin/catalog/prices/{price_id}/supersede", status_code=201)
async def supersede_price(
    price_id: UUID,
    payload: PriceSupersedeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.prices.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    old = await session.scalar(select(Price).where(Price.id == price_id).with_for_update())
    if old is None:
        raise VavError("PRICE_NOT_FOUND", "Price was not found.", status_code=404)
    if (
        payload.price_book_id != old.price_book_id
        or payload.currency_code != old.currency_code
        or payload.billing_type != old.billing_type
    ):
        raise VavError(
            "PRICE_SUPERSEDE_IDENTITY_MISMATCH",
            "A superseding price must keep the price book, currency and billing type.",
            status_code=422,
        )
    if payload.valid_from <= datetime.now(UTC):
        raise VavError(
            "PRICE_SUPERSEDE_TIME_INVALID",
            "Superseding prices must start in the future.",
            status_code=422,
        )
    old_before = _price_payload(old)
    old.valid_until = payload.valid_from
    values = payload.model_dump(exclude={"reason", "supersedes_price_id"})
    new_price = Price(
        sku_id=old.sku_id,
        status="active",
        created_by=principal.user.id,
        supersedes_price_id=old.id,
        **values,
    )
    session.add(new_price)
    await session.flush()
    record_security_event(
        session,
        event_type="catalog.price.superseded",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="price",
        target_id=old.id,
        reason=payload.reason,
        before_state=old_before,
        after_state=_price_payload(new_price),
    )
    await session.commit()
    await _bump_catalog_version()
    return success(_price_payload(new_price), request_id_from_request(request))


@router.get("/admin/catalog/inventory")
async def admin_inventory(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.inventory.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    items = list(
        (
            await session.scalars(select(InventoryItem).order_by(InventoryItem.updated_at.desc()))
        ).all()
    )
    return success(
        {"items": [_inventory_payload(item) for item in items]},
        request_id_from_request(request),
    )


@router.get("/admin/catalog/inventory/{sku_id}")
async def get_admin_inventory(
    sku_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.inventory.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await session.scalar(select(InventoryItem).where(InventoryItem.sku_id == sku_id))
    if item is None:
        raise VavError("INVENTORY_NOT_CONFIGURED", "Inventory is not configured.", status_code=404)
    return success(_inventory_payload(item), request_id_from_request(request))


@router.put("/admin/catalog/inventory/{sku_id}")
async def configure_inventory(
    sku_id: UUID,
    payload: InventoryConfigureRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.inventory.adjust")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    sku = await session.get(ProductSku, sku_id)
    if sku is None:
        raise VavError("CATALOG_SKU_NOT_FOUND", "SKU was not found.", status_code=404)
    item = await inventory_service.configure(
        session,
        sku=sku,
        total_capacity=payload.total_capacity,
        safety_stock=payload.safety_stock,
        overselling_allowed=payload.overselling_allowed,
        oversell_limit=payload.oversell_limit,
        reason=payload.reason,
        actor_id=principal.user.id,
    )
    await _bump_catalog_version()
    return success(_inventory_payload(item), request_id_from_request(request))


@router.post("/admin/catalog/inventory/{sku_id}/adjust")
async def adjust_inventory(
    sku_id: UUID,
    payload: InventoryAdjustRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.inventory.adjust")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.quantity_delta == 0:
        raise VavError(
            "INVENTORY_ADJUSTMENT_INVALID",
            "Inventory adjustment must be non-zero.",
            status_code=422,
        )
    item = await inventory_service.adjust(
        session,
        sku_id=sku_id,
        quantity_delta=payload.quantity_delta,
        reason=payload.reason,
        expected_version=payload.expected_version,
        actor_id=principal.user.id,
    )
    await _bump_catalog_version()
    return success(_inventory_payload(item), request_id_from_request(request))


@router.get("/admin/catalog/inventory/{sku_id}/movements")
async def inventory_movements(
    sku_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.inventory.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await session.scalar(select(InventoryItem).where(InventoryItem.sku_id == sku_id))
    if item is None:
        raise VavError("INVENTORY_NOT_CONFIGURED", "Inventory is not configured.", status_code=404)
    movements = list(
        (
            await session.scalars(
                select(InventoryMovement)
                .where(InventoryMovement.inventory_item_id == item.id)
                .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id)
            )
        ).all()
    )
    return success(
        {
            "items": [
                {
                    "id": str(movement.id),
                    "movement_type": movement.movement_type,
                    "quantity_delta": movement.quantity_delta,
                    "before_quantity": movement.before_quantity,
                    "after_quantity": movement.after_quantity,
                    "reference_type": movement.reference_type,
                    "reference_id": (str(movement.reference_id) if movement.reference_id else None),
                    "reason": movement.reason,
                    "created_at": movement.created_at.isoformat(),
                }
                for movement in movements
            ]
        },
        request_id_from_request(request),
    )


@router.post("/internal/inventory/reservations", status_code=201)
async def create_inventory_reservation(
    payload: InventoryReservationRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.inventory.adjust")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.pricing_quote_id:
        quote = await session.get(PricingQuote, payload.pricing_quote_id)
        if (
            quote is None
            or quote.sku_id != payload.sku_id
            or quote.quantity != payload.quantity
            or quote.expires_at <= datetime.now(UTC)
            or quote.consumed_at is not None
        ):
            raise VavError(
                "PRICING_QUOTE_INVALID",
                "A reservation requires a matching, active quote.",
                status_code=409,
            )
    reservation = await inventory_service.reserve(
        session,
        sku_id=payload.sku_id,
        quantity=payload.quantity,
        user_id=payload.user_id,
        anonymous_session_id=payload.anonymous_session_id,
        pricing_quote_id=payload.pricing_quote_id,
    )
    if reservation is None:
        return success(
            {"status": "not_required", "reservation_id": None},
            request_id_from_request(request),
        )
    return success(
        {
            "reservation_id": str(reservation.id),
            "status": reservation.status,
            "expires_at": reservation.expires_at.isoformat(),
        },
        request_id_from_request(request),
    )


@router.post("/internal/inventory/reservations/{reservation_id}/confirm")
async def confirm_inventory_reservation(
    reservation_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.inventory.adjust")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    reservation = await inventory_service.confirm(session, reservation_id)
    return success(
        {"reservation_id": str(reservation.id), "status": reservation.status},
        request_id_from_request(request),
    )


@router.post("/internal/inventory/reservations/{reservation_id}/release")
async def release_inventory_reservation(
    reservation_id: UUID,
    payload: ReasonRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.inventory.adjust")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    reservation = await inventory_service.release(session, reservation_id, reason=payload.reason)
    return success(
        {"reservation_id": str(reservation.id), "status": reservation.status},
        request_id_from_request(request),
    )


def _promotion_payload(promotion: Promotion) -> dict[str, object]:
    return {
        "id": str(promotion.id),
        "promotion_code": promotion.promotion_code,
        "internal_name": promotion.internal_name,
        "promotion_type": promotion.promotion_type,
        "application_mode": promotion.application_mode,
        "status": promotion.status,
        "priority": promotion.priority,
        "stackability": promotion.stackability,
        "rules": promotion.rules,
        "benefits": promotion.benefits,
        "valid_from": promotion.valid_from.isoformat(),
        "valid_until": (promotion.valid_until.isoformat() if promotion.valid_until else None),
        "total_redemption_limit": promotion.total_redemption_limit,
        "per_user_redemption_limit": promotion.per_user_redemption_limit,
        "budget_limit_minor": promotion.budget_limit_minor,
        "budget_currency": promotion.budget_currency,
        "current_redemption_count": promotion.current_redemption_count,
        "current_discount_total_minor": promotion.current_discount_total_minor,
    }


def _coupon_payload(coupon: Coupon) -> dict[str, object]:
    return {
        "id": str(coupon.id),
        "promotion_id": str(coupon.promotion_id),
        "display_code": coupon.display_code,
        "status": coupon.status,
        "valid_from": coupon.valid_from.isoformat() if coupon.valid_from else None,
        "valid_until": coupon.valid_until.isoformat() if coupon.valid_until else None,
        "total_redemption_limit": coupon.total_redemption_limit,
        "per_user_redemption_limit": coupon.per_user_redemption_limit,
        "current_redemption_count": coupon.current_redemption_count,
        "assigned_user_id": (str(coupon.assigned_user_id) if coupon.assigned_user_id else None),
    }


@router.get("/admin/catalog/promotions")
async def admin_promotions(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.promotions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    promotions = list(
        (
            await session.scalars(
                select(Promotion).order_by(Promotion.priority.desc(), Promotion.created_at.desc())
            )
        ).all()
    )
    return success(
        {"items": [_promotion_payload(item) for item in promotions]},
        request_id_from_request(request),
    )


@router.post("/admin/catalog/promotions", status_code=201)
async def create_promotion(
    payload: PromotionCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.promotions.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    promotion = Promotion(
        **payload.model_dump(mode="json", exclude={"rules", "benefits"}),
        rules=payload.rules.model_dump(mode="json"),
        benefits=payload.benefits.model_dump(mode="json"),
        created_by=principal.user.id,
    )
    session.add(promotion)
    await session.flush()
    record_security_event(
        session,
        event_type="catalog.promotion.created",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="promotion",
        target_id=promotion.id,
    )
    await session.commit()
    return success(_promotion_payload(promotion), request_id_from_request(request))


@router.get("/admin/catalog/promotions/{promotion_id}")
async def get_promotion(
    promotion_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.promotions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    promotion = await session.get(Promotion, promotion_id)
    if promotion is None:
        raise VavError("PROMOTION_NOT_FOUND", "Promotion was not found.", status_code=404)
    return success(_promotion_payload(promotion), request_id_from_request(request))


@router.patch("/admin/catalog/promotions/{promotion_id}")
async def update_promotion(
    promotion_id: UUID,
    payload: PromotionUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.promotions.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    promotion = await session.scalar(
        select(Promotion).where(Promotion.id == promotion_id).with_for_update()
    )
    if promotion is None:
        raise VavError("PROMOTION_NOT_FOUND", "Promotion was not found.", status_code=404)
    if promotion.status == "active":
        raise VavError(
            "PROMOTION_ACTIVE_IMMUTABLE",
            "Deactivate a promotion before changing its rules.",
            status_code=409,
        )
    before = _promotion_payload(promotion)
    for field in ("internal_name", "priority", "stackability", "valid_from", "valid_until"):
        value = getattr(payload, field)
        if value is not None:
            setattr(promotion, field, value)
    if payload.rules is not None:
        promotion.rules = payload.rules.model_dump(mode="json")
    if payload.benefits is not None:
        promotion.benefits = payload.benefits.model_dump(mode="json")
    record_security_event(
        session,
        event_type="catalog.promotion.updated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="promotion",
        target_id=promotion.id,
        reason=payload.reason,
        before_state=before,
        after_state=_promotion_payload(promotion),
    )
    await session.commit()
    await _bump_catalog_version()
    return success(_promotion_payload(promotion), request_id_from_request(request))


async def _set_promotion_status(
    *,
    promotion_id: UUID,
    active: bool,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    promotion = await session.scalar(
        select(Promotion).where(Promotion.id == promotion_id).with_for_update()
    )
    if promotion is None:
        raise VavError("PROMOTION_NOT_FOUND", "Promotion was not found.", status_code=404)
    PromotionRules.model_validate(promotion.rules)
    PromotionBenefits.model_validate(promotion.benefits)
    promotion.status = "active" if active else "inactive"
    record_security_event(
        session,
        event_type=("catalog.promotion.activated" if active else "catalog.promotion.deactivated"),
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="promotion",
        target_id=promotion.id,
        reason=payload.reason,
    )
    await session.commit()
    await _bump_catalog_version()
    return success({"status": promotion.status}, request_id_from_request(request))


@router.post("/admin/catalog/promotions/{promotion_id}/activate")
async def activate_promotion(
    promotion_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.promotions.activate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _set_promotion_status(
        promotion_id=promotion_id,
        active=True,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/catalog/promotions/{promotion_id}/deactivate")
async def deactivate_promotion(
    promotion_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.promotions.activate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _set_promotion_status(
        promotion_id=promotion_id,
        active=False,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.get("/admin/catalog/coupons")
async def admin_coupons(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.coupons.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    coupons = list(
        (await session.scalars(select(Coupon).order_by(Coupon.created_at.desc(), Coupon.id))).all()
    )
    return success(
        {"items": [_coupon_payload(item) for item in coupons]},
        request_id_from_request(request),
    )


@router.post("/admin/catalog/coupons", status_code=201)
async def create_coupon(
    payload: CouponCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.coupons.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    promotion = await session.get(Promotion, payload.promotion_id)
    if promotion is None:
        raise VavError("PROMOTION_NOT_FOUND", "Promotion was not found.", status_code=404)
    normalized = payload.code.strip().upper()
    coupon = Coupon(
        promotion_id=payload.promotion_id,
        coupon_code_normalized=normalized,
        display_code=payload.code.strip(),
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        total_redemption_limit=payload.total_redemption_limit,
        per_user_redemption_limit=payload.per_user_redemption_limit,
        assigned_user_id=payload.assigned_user_id,
    )
    session.add(coupon)
    await session.flush()
    record_security_event(
        session,
        event_type="catalog.coupon.created",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="coupon",
        target_id=coupon.id,
        metadata={"promotion_id": str(promotion.id)},
    )
    await session.commit()
    return success(_coupon_payload(coupon), request_id_from_request(request))


@router.post("/admin/catalog/coupons/bulk-create", status_code=201)
async def bulk_create_coupons(
    payload: CouponBulkCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.coupons.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if await session.get(Promotion, payload.promotion_id) is None:
        raise VavError("PROMOTION_NOT_FOUND", "Promotion was not found.", status_code=404)
    items: list[Coupon] = []
    for _ in range(payload.count):
        code = f"{payload.prefix.upper()}-{secrets.token_hex(5).upper()}"
        coupon = Coupon(
            promotion_id=payload.promotion_id,
            coupon_code_normalized=code,
            display_code=code,
            valid_until=payload.valid_until,
        )
        session.add(coupon)
        items.append(coupon)
    await session.flush()
    record_security_event(
        session,
        event_type="catalog.coupon.bulk_created",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="promotion",
        target_id=payload.promotion_id,
        metadata={"count": payload.count},
    )
    await session.commit()
    return success(
        {"items": [_coupon_payload(item) for item in items]},
        request_id_from_request(request),
    )


@router.patch("/admin/catalog/coupons/{coupon_id}")
async def update_coupon(
    coupon_id: UUID,
    payload: CouponUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.coupons.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    coupon = await session.scalar(select(Coupon).where(Coupon.id == coupon_id).with_for_update())
    if coupon is None:
        raise VavError("COUPON_NOT_FOUND", "Coupon was not found.", status_code=404)
    for field, value in payload.model_dump(exclude={"reason"}, exclude_none=True).items():
        setattr(coupon, field, value)
    record_security_event(
        session,
        event_type="catalog.coupon.updated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="coupon",
        target_id=coupon.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(_coupon_payload(coupon), request_id_from_request(request))


@router.post("/admin/catalog/coupons/{coupon_id}/disable")
async def disable_coupon(
    coupon_id: UUID,
    payload: ReasonRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("catalog.coupons.disable")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    coupon = await session.scalar(select(Coupon).where(Coupon.id == coupon_id).with_for_update())
    if coupon is None:
        raise VavError("COUPON_NOT_FOUND", "Coupon was not found.", status_code=404)
    coupon.status = "disabled"
    record_security_event(
        session,
        event_type="catalog.coupon.disabled",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="coupon",
        target_id=coupon.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"status": coupon.status}, request_id_from_request(request))


@router.post("/admin/catalog/pricing/simulate")
async def simulate_pricing(
    payload: PricingSimulationRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.pricing.simulate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    calculation = await pricing_engine.calculate(
        session,
        sku_id=payload.sku_id,
        quantity=payload.quantity,
        currency=payload.requested_currency,
        requested_at=payload.pricing_context.requested_at,
        region_code=payload.pricing_context.region_code,
        customer_segment=payload.pricing_context.customer_segment,
        coupon_code=payload.coupon_code,
        user_id=payload.user_id,
    )
    return success(
        {
            **calculation.snapshot(),
            "simulation": True,
            "quote_id": None,
            "inventory_mutated": False,
            "coupon_state_mutated": False,
            "payment_status": "not_paid",
            "grants_entitlement": False,
        },
        request_id_from_request(request),
    )


@router.post("/internal/catalog/coupon-redemptions", status_code=201)
async def reserve_coupon_redemption(
    payload: CouponRedemptionReservationRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.coupons.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    reservation = await coupon_redemption_service.reserve(
        session,
        pricing_quote_id=payload.pricing_quote_id,
        promotion_id=payload.promotion_id,
        coupon_id=payload.coupon_id,
        user_id=payload.user_id,
    )
    return success(
        {
            "reservation_id": str(reservation.id),
            "status": reservation.status,
            "expires_at": reservation.expires_at.isoformat(),
        },
        request_id_from_request(request),
    )


@router.post("/internal/catalog/coupon-redemptions/{reservation_id}/confirm")
async def confirm_coupon_redemption(
    reservation_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.coupons.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    reservation = await coupon_redemption_service.confirm(session, reservation_id)
    return success(
        {"reservation_id": str(reservation.id), "status": reservation.status},
        request_id_from_request(request),
    )


@router.post("/internal/catalog/coupon-redemptions/{reservation_id}/release")
async def release_coupon_redemption(
    reservation_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("catalog.coupons.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    reservation = await coupon_redemption_service.release(session, reservation_id)
    return success(
        {"reservation_id": str(reservation.id), "status": reservation.status},
        request_id_from_request(request),
    )
