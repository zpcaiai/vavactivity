from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StringConstraints,
    model_validator,
)

from vav.modules.catalog.domain import (
    EXPECTED_FULFILLMENT_TYPES,
    BillingType,
    FulfillmentType,
    InventoryPolicy,
    PricingContextInput,
    ProductType,
    PromotionApplicationMode,
    PromotionBenefits,
    PromotionRules,
    PromotionType,
    Stackability,
)
from vav.modules.content.domain import ContentBlock

Code = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9_-]{1,127}$")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class CategoryLocalizationInput(BaseModel):
    locale: str
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    slug: Slug


class CategoryCreateRequest(BaseModel):
    category_code: Slug
    parent_id: UUID | None = None
    internal_name: str = Field(min_length=1, max_length=200)
    sort_order: int = 0
    localizations: list[CategoryLocalizationInput] = Field(min_length=1)


class ProductLocalizationInput(BaseModel):
    locale: str
    slug: Slug
    name: str = Field(min_length=1, max_length=300)
    short_description: str | None = Field(default=None, max_length=500)
    description_blocks: list[ContentBlock] = Field(default_factory=list)
    seo_title: str | None = Field(default=None, max_length=300)
    seo_description: str | None = Field(default=None, max_length=500)
    cover_media_id: UUID | None = None
    translation_status: str = "draft"


class ProductCreateRequest(BaseModel):
    product_code: Code
    product_type: ProductType
    fulfillment_type: FulfillmentType
    internal_name: str = Field(min_length=1, max_length=200)
    visibility: str = "public"
    default_locale: str = "zh-CN"
    category_id: UUID | None = None
    purchasable_from: datetime | None = None
    purchasable_until: datetime | None = None
    featured: bool = False
    sort_order: int = 0
    metadata: dict[str, object] = Field(default_factory=dict)
    localizations: list[ProductLocalizationInput] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_window_and_locales(self) -> ProductCreateRequest:
        if (
            self.purchasable_from
            and self.purchasable_until
            and self.purchasable_until <= self.purchasable_from
        ):
            raise ValueError("purchasable_until must follow purchasable_from")
        if len({item.locale for item in self.localizations}) != len(self.localizations):
            raise ValueError("localization locales must be unique")
        if self.default_locale not in {item.locale for item in self.localizations}:
            raise ValueError("default locale localization is required")
        if self.fulfillment_type not in EXPECTED_FULFILLMENT_TYPES[self.product_type]:
            raise ValueError("fulfillment type is incompatible with product type")
        return self


class ProductUpdateRequest(BaseModel):
    internal_name: str | None = Field(default=None, min_length=1, max_length=200)
    visibility: str | None = None
    category_id: UUID | None = None
    purchasable_from: datetime | None = None
    purchasable_until: datetime | None = None
    featured: bool | None = None
    sort_order: int | None = None
    metadata: dict[str, object] | None = None
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=2000)


class ProductLocalizationUpdateRequest(ProductLocalizationInput):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=2000)


class SkuCreateRequest(BaseModel):
    sku_code: Code
    internal_name: str = Field(min_length=1, max_length=200)
    billing_type: BillingType
    service_quantity: PositiveInt | None = None
    service_unit: str | None = Field(default=None, max_length=64)
    entitlement_definition: dict[str, object] = Field(default_factory=dict)
    fulfillment_configuration: dict[str, object]
    inventory_policy: InventoryPolicy
    purchase_limit_per_user: PositiveInt | None = None
    purchase_limit_total: PositiveInt | None = None
    purchasable_from: datetime | None = None
    purchasable_until: datetime | None = None


class SkuUpdateRequest(BaseModel):
    internal_name: str | None = Field(default=None, min_length=1, max_length=200)
    service_quantity: PositiveInt | None = None
    service_unit: str | None = Field(default=None, max_length=64)
    entitlement_definition: dict[str, object] | None = None
    fulfillment_configuration: dict[str, object] | None = None
    purchase_limit_per_user: PositiveInt | None = None
    purchase_limit_total: PositiveInt | None = None
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=2000)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class PriceBookCreateRequest(BaseModel):
    price_book_code: Code
    name: str = Field(min_length=1, max_length=200)
    region_code: str | None = Field(default=None, max_length=64)
    customer_segment: str | None = Field(default=None, max_length=64)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    priority: int = 0


class PriceBookUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    region_code: str | None = Field(default=None, max_length=64)
    customer_segment: str | None = Field(default=None, max_length=64)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    priority: int | None = None
    reason: str = Field(min_length=10, max_length=2000)


class PriceCreateRequest(BaseModel):
    price_book_id: UUID
    currency_code: CurrencyCode
    unit_amount_minor: int = Field(ge=0)
    compare_at_amount_minor: int | None = Field(default=None, ge=0)
    billing_type: BillingType
    billing_interval: str | None = None
    billing_interval_count: PositiveInt | None = None
    tax_behavior: str = "unspecified"
    valid_from: datetime
    valid_until: datetime | None = None
    external_price_references: dict[str, object] = Field(default_factory=dict)
    supersedes_price_id: UUID | None = None

    @model_validator(mode="after")
    def validate_billing(self) -> PriceCreateRequest:
        if self.billing_type == BillingType.RECURRING:
            if not self.billing_interval or not self.billing_interval_count:
                raise ValueError("recurring prices require billing interval")
        elif self.billing_interval is not None or self.billing_interval_count is not None:
            raise ValueError("one-time and free prices cannot define a billing interval")
        if self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must follow valid_from")
        if (
            self.compare_at_amount_minor is not None
            and self.compare_at_amount_minor < self.unit_amount_minor
        ):
            raise ValueError("compare-at amount cannot be lower than unit amount")
        return self


class PriceSupersedeRequest(PriceCreateRequest):
    reason: str = Field(min_length=10, max_length=2000)


class InventoryConfigureRequest(BaseModel):
    total_capacity: int | None = Field(default=None, ge=0)
    safety_stock: int = Field(default=0, ge=0)
    overselling_allowed: bool = False
    oversell_limit: int = Field(default=0, ge=0)
    reason: str = Field(min_length=10, max_length=2000)


class InventoryAdjustRequest(BaseModel):
    quantity_delta: int
    reason: str = Field(min_length=10, max_length=2000)
    expected_version: int = Field(ge=1)


class PricingQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    quantity: PositiveInt
    requested_currency: CurrencyCode
    locale: str = "zh-CN"
    anonymous_session_id: UUID
    coupon_code: str | None = Field(default=None, min_length=2, max_length=128)
    pricing_context: PricingContextInput = Field(default_factory=PricingContextInput)


class PricingSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    quantity: PositiveInt
    requested_currency: CurrencyCode
    locale: str = "zh-CN"
    user_id: UUID | None = None
    coupon_code: str | None = Field(default=None, min_length=2, max_length=128)
    pricing_context: PricingContextInput = Field(default_factory=PricingContextInput)


class InventoryReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    quantity: PositiveInt
    user_id: UUID | None = None
    anonymous_session_id: UUID | None = None
    pricing_quote_id: UUID | None = None

    @model_validator(mode="after")
    def validate_principal(self) -> InventoryReservationRequest:
        if self.user_id is None and self.anonymous_session_id is None:
            raise ValueError("reservation principal is required")
        return self


class PromotionCreateRequest(BaseModel):
    promotion_code: Code
    internal_name: str = Field(min_length=1, max_length=200)
    promotion_type: PromotionType
    application_mode: PromotionApplicationMode
    priority: int = 0
    stackability: Stackability = Stackability.EXCLUSIVE
    rules: PromotionRules
    benefits: PromotionBenefits
    valid_from: datetime
    valid_until: datetime | None = None
    total_redemption_limit: PositiveInt | None = None
    per_user_redemption_limit: PositiveInt | None = None
    budget_limit_minor: int | None = Field(default=None, ge=0)
    budget_currency: CurrencyCode | None = None


class PromotionUpdateRequest(BaseModel):
    internal_name: str | None = Field(default=None, min_length=1, max_length=200)
    priority: int | None = None
    stackability: Stackability | None = None
    rules: PromotionRules | None = None
    benefits: PromotionBenefits | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    reason: str = Field(min_length=10, max_length=2000)


class CouponCreateRequest(BaseModel):
    promotion_id: UUID
    code: str = Field(min_length=2, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    total_redemption_limit: PositiveInt | None = None
    per_user_redemption_limit: PositiveInt | None = None
    assigned_user_id: UUID | None = None


class CouponBulkCreateRequest(BaseModel):
    promotion_id: UUID
    prefix: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    count: int = Field(ge=1, le=1000)
    valid_until: datetime | None = None


class CouponUpdateRequest(BaseModel):
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    total_redemption_limit: PositiveInt | None = None
    per_user_redemption_limit: PositiveInt | None = None
    assigned_user_id: UUID | None = None
    reason: str = Field(min_length=10, max_length=2000)


class CouponValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    requested_currency: CurrencyCode
    subtotal_minor: int = Field(ge=0)
    quantity: PositiveInt
    coupon_code: str = Field(min_length=2, max_length=128)
    anonymous_session_id: UUID


class CouponRedemptionReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pricing_quote_id: UUID
    promotion_id: UUID
    coupon_id: UUID | None = None
    user_id: UUID | None = None
