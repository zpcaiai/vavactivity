from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.base import Base


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    category_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_categories.id")
    )
    internal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProductCategoryLocalization(Base):
    __tablename__ = "product_category_localizations"
    __table_args__ = (
        PrimaryKeyConstraint("category_id", "locale"),
        UniqueConstraint("locale", "slug"),
    )

    category_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_categories.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    slug: Mapped[str] = mapped_column(String(200), nullable=False)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    product_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    fulfillment_type: Mapped[str] = mapped_column(String(64), nullable=False)
    internal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'public'")
    )
    default_locale: Mapped[str] = mapped_column(String(16), nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_categories.id")
    )
    purchasable_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purchasable_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    product_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductLocalization(Base):
    __tablename__ = "product_localizations"
    __table_args__ = (
        UniqueConstraint("product_id", "locale"),
        UniqueConstraint("locale", "slug"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(500))
    description_blocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    seo_title: Mapped[str | None] = mapped_column(String(300))
    seo_description: Mapped[str | None] = mapped_column(String(500))
    cover_media_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id")
    )
    translation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'draft'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProductSku(Base):
    __tablename__ = "product_skus"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    sku_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    internal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    billing_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    service_quantity: Mapped[int | None] = mapped_column(Integer)
    service_unit: Mapped[str | None] = mapped_column(String(64))
    entitlement_definition: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    fulfillment_configuration: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    inventory_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    purchase_limit_per_user: Mapped[int | None] = mapped_column(Integer)
    purchase_limit_total: Mapped[int | None] = mapped_column(Integer)
    purchasable_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purchasable_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportedCurrency(Base):
    __tablename__ = "supported_currencies"

    currency_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    exponent: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PriceBook(Base):
    __tablename__ = "price_books"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    price_book_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    region_code: Mapped[str | None] = mapped_column(String(64))
    customer_segment: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    sku_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_skus.id"), nullable=False
    )
    price_book_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("price_books.id"), nullable=False
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), ForeignKey("supported_currencies.currency_code"), nullable=False
    )
    unit_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compare_at_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    billing_type: Mapped[str] = mapped_column(String(32), nullable=False)
    billing_interval: Mapped[str | None] = mapped_column(String(32))
    billing_interval_count: Mapped[int | None] = mapped_column(Integer)
    tax_behavior: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'unspecified'")
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    external_price_references: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    supersedes_price_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("prices.id")
    )


class ExchangeRateSnapshot(Base):
    __tablename__ = "exchange_rate_snapshots"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_scaled: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scale: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    sku_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_skus.id"), nullable=False, unique=True
    )
    inventory_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    total_capacity: Mapped[int | None] = mapped_column(Integer)
    reserved_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    sold_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    overselling_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    oversell_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False
    )
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    before_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    after_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(64))
    reference_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    promotion_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    internal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    promotion_type: Mapped[str] = mapped_column(String(32), nullable=False)
    application_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    stackability: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'exclusive'")
    )
    rules: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    benefits: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_redemption_limit: Mapped[int | None] = mapped_column(Integer)
    per_user_redemption_limit: Mapped[int | None] = mapped_column(Integer)
    budget_limit_minor: Mapped[int | None] = mapped_column(BigInteger)
    budget_currency: Mapped[str | None] = mapped_column(String(3))
    current_redemption_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    current_discount_total_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    promotion_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("promotions.id"), nullable=False
    )
    coupon_code_normalized: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_code: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_redemption_limit: Mapped[int | None] = mapped_column(Integer)
    per_user_redemption_limit: Mapped[int | None] = mapped_column(Integer)
    current_redemption_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    assigned_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PricingQuote(Base):
    __tablename__ = "pricing_quotes"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    anonymous_session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    sku_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_skus.id"), nullable=False
    )
    price_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("prices.id"), nullable=False
    )
    price_book_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("price_books.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_estimate_minor: Mapped[int | None] = mapped_column(BigInteger)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    calculation_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InventoryReservation(Base):
    __tablename__ = "inventory_reservations"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False
    )
    sku_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("product_skus.id"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    anonymous_session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    pricing_quote_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pricing_quotes.id")
    )
    order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("orders.id"))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CouponRedemptionReservation(Base):
    __tablename__ = "coupon_redemption_reservations"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    coupon_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("coupons.id"))
    promotion_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("promotions.id"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    pricing_quote_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pricing_quotes.id"), nullable=False
    )
    order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("orders.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reserved_discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
