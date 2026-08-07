from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, PositiveInt, model_validator

from vav.common.exceptions import VavError


class ProductType(StrEnum):
    ACTIVITY_TICKET = "activity_ticket"
    COURSE = "course"
    COURSE_BUNDLE = "course_bundle"
    COUNSELING_SESSION = "counseling_session"
    COUNSELING_PACKAGE = "counseling_package"
    AI_CREDIT_PACKAGE = "ai_credit_package"
    AI_SUBSCRIPTION = "ai_subscription"
    MEMBERSHIP = "membership"
    DIGITAL_SERVICE = "digital_service"


class FulfillmentType(StrEnum):
    EVENT_ADMISSION = "event_admission"
    DIGITAL_ACCESS = "digital_access"
    APPOINTMENT_CREDITS = "appointment_credits"
    AI_CREDITS = "ai_credits"
    MEMBERSHIP_ENTITLEMENT = "membership_entitlement"
    MANUAL_FULFILLMENT = "manual_fulfillment"


EXPECTED_FULFILLMENT_TYPES: dict[ProductType, frozenset[FulfillmentType]] = {
    ProductType.ACTIVITY_TICKET: frozenset({FulfillmentType.EVENT_ADMISSION}),
    ProductType.COURSE: frozenset({FulfillmentType.DIGITAL_ACCESS}),
    ProductType.COURSE_BUNDLE: frozenset({FulfillmentType.DIGITAL_ACCESS}),
    ProductType.COUNSELING_SESSION: frozenset({FulfillmentType.APPOINTMENT_CREDITS}),
    ProductType.COUNSELING_PACKAGE: frozenset({FulfillmentType.APPOINTMENT_CREDITS}),
    ProductType.AI_CREDIT_PACKAGE: frozenset({FulfillmentType.AI_CREDITS}),
    ProductType.AI_SUBSCRIPTION: frozenset({FulfillmentType.AI_CREDITS}),
    ProductType.MEMBERSHIP: frozenset({FulfillmentType.MEMBERSHIP_ENTITLEMENT}),
    ProductType.DIGITAL_SERVICE: frozenset(
        {FulfillmentType.DIGITAL_ACCESS, FulfillmentType.MANUAL_FULFILLMENT}
    ),
}


class ProductStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class SkuStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class BillingType(StrEnum):
    ONE_TIME = "one_time"
    RECURRING = "recurring"
    FREE = "free"


class InventoryPolicy(StrEnum):
    UNLIMITED = "unlimited"
    FINITE = "finite"
    SERVICE_CAPACITY = "service_capacity"
    EXTERNAL = "external"


class ReservationStatus(StrEnum):
    ACTIVE = "active"
    CONFIRMED = "confirmed"
    RELEASED = "released"
    EXPIRED = "expired"


class PromotionType(StrEnum):
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"
    FIXED_PRICE = "fixed_price"
    FREE_ITEM = "free_item"


class PromotionApplicationMode(StrEnum):
    AUTOMATIC = "automatic"
    COUPON_REQUIRED = "coupon_required"


class Stackability(StrEnum):
    EXCLUSIVE = "exclusive"
    STACKABLE = "stackable"
    STACKABLE_WITH_AUTOMATIC_ONLY = "stackable_with_automatic_only"


class PurchasabilityStatus(StrEnum):
    AVAILABLE = "available"
    LOW_STOCK = "low_stock"
    SOLD_OUT = "sold_out"
    NOT_STARTED = "not_started"
    ENDED = "ended"
    UNAVAILABLE_IN_REGION = "unavailable_in_region"
    PRICE_UNAVAILABLE = "price_unavailable"
    LOGIN_REQUIRED = "login_required"


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        normalized = self.currency.strip().upper()
        if len(normalized) != 3:
            raise VavError("CURRENCY_INVALID", "Currency must be a three-letter code.")
        if self.amount_minor < 0:
            raise VavError("MONEY_NEGATIVE", "Money cannot be negative.")
        object.__setattr__(self, "currency", normalized)

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        if other.amount_minor > self.amount_minor:
            raise VavError("MONEY_NEGATIVE", "Money cannot be negative.")
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def multiply(self, quantity: int) -> Money:
        if quantity <= 0:
            raise VavError("QUANTITY_INVALID", "Quantity must be positive.")
        return Money(self.amount_minor * quantity, self.currency)

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise VavError("CURRENCY_MISMATCH", "Different currencies cannot be combined.")


def round_discount(amount_minor: int, basis_points: int) -> int:
    if amount_minor < 0 or not 0 <= basis_points <= 10_000:
        raise VavError("DISCOUNT_INVALID", "Discount inputs are invalid.")
    raw = Decimal(amount_minor) * Decimal(basis_points) / Decimal(10_000)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class ActivityTicketConfig(BaseModel):
    activity_id: UUID
    ticket_type: str = Field(min_length=1, max_length=128)


class CourseConfig(BaseModel):
    course_id: UUID
    access_duration_days: PositiveInt | None = None


class CounselingConfig(BaseModel):
    counseling_service_id: UUID
    session_count: PositiveInt
    validity_days: PositiveInt


class AiCreditConfig(BaseModel):
    credit_count: PositiveInt
    validity_days: PositiveInt


class MembershipConfig(BaseModel):
    membership_tier: str = Field(min_length=1, max_length=128)
    duration_days: PositiveInt | None = None


class DigitalServiceConfig(BaseModel):
    service_code: str = Field(min_length=1, max_length=128)
    delivery_notes: str | None = Field(default=None, max_length=1000)


FULFILLMENT_SCHEMAS: dict[ProductType, type[BaseModel]] = {
    ProductType.ACTIVITY_TICKET: ActivityTicketConfig,
    ProductType.COURSE: CourseConfig,
    ProductType.COURSE_BUNDLE: CourseConfig,
    ProductType.COUNSELING_SESSION: CounselingConfig,
    ProductType.COUNSELING_PACKAGE: CounselingConfig,
    ProductType.AI_CREDIT_PACKAGE: AiCreditConfig,
    ProductType.AI_SUBSCRIPTION: AiCreditConfig,
    ProductType.MEMBERSHIP: MembershipConfig,
    ProductType.DIGITAL_SERVICE: DigitalServiceConfig,
}


def validate_fulfillment(
    product_type: ProductType, configuration: dict[str, object]
) -> dict[str, object]:
    schema = FULFILLMENT_SCHEMAS[product_type]
    return schema.model_validate(configuration).model_dump(mode="json", exclude_none=True)


class PromotionRules(BaseModel):
    schema_version: int = 1
    eligible_product_ids: list[UUID] = Field(default_factory=list)
    eligible_sku_ids: list[UUID] = Field(default_factory=list)
    eligible_category_ids: list[UUID] = Field(default_factory=list)
    excluded_product_ids: list[UUID] = Field(default_factory=list)
    allowed_currencies: list[str] = Field(default_factory=list)
    minimum_subtotal_minor: int = Field(default=0, ge=0)
    first_purchase_only: bool = False
    customer_segments: list[str] = Field(default_factory=list)
    minimum_quantity: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def normalize_currencies(self) -> PromotionRules:
        self.allowed_currencies = [item.upper() for item in self.allowed_currencies]
        return self


class PromotionBenefits(BaseModel):
    schema_version: int = 1
    percentage_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    maximum_discount_minor: int | None = Field(default=None, ge=0)
    amounts: dict[str, int] = Field(default_factory=dict)
    fixed_prices: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_amounts(self) -> PromotionBenefits:
        if any(amount < 0 for amount in [*self.amounts.values(), *self.fixed_prices.values()]):
            raise ValueError("promotion amounts cannot be negative")
        self.amounts = {code.upper(): value for code, value in self.amounts.items()}
        self.fixed_prices = {code.upper(): value for code, value in self.fixed_prices.items()}
        return self


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    id: UUID
    code: str
    promotion_type: PromotionType
    application_mode: PromotionApplicationMode
    priority: int
    stackability: Stackability
    rules: PromotionRules
    benefits: PromotionBenefits


@dataclass(frozen=True, slots=True)
class PromotionContext:
    product_id: UUID
    sku_id: UUID
    category_id: UUID | None
    currency: str
    subtotal_minor: int
    quantity: int
    customer_segment: str | None = None
    is_first_purchase: bool = False


@dataclass(frozen=True, slots=True)
class AppliedDiscount:
    promotion_id: UUID
    promotion_code: str
    discount_type: str
    discount_amount_minor: int
    description: str


def _eligible(candidate: PromotionCandidate, context: PromotionContext) -> bool:
    rules = candidate.rules
    if context.product_id in rules.excluded_product_ids:
        return False
    if rules.eligible_product_ids and context.product_id not in rules.eligible_product_ids:
        return False
    if rules.eligible_sku_ids and context.sku_id not in rules.eligible_sku_ids:
        return False
    if rules.eligible_category_ids and context.category_id not in rules.eligible_category_ids:
        return False
    if rules.allowed_currencies and context.currency not in rules.allowed_currencies:
        return False
    if context.subtotal_minor < rules.minimum_subtotal_minor:
        return False
    if context.quantity < rules.minimum_quantity:
        return False
    if rules.first_purchase_only and not context.is_first_purchase:
        return False
    return not (rules.customer_segments and context.customer_segment not in rules.customer_segments)


def apply_promotions(
    candidates: list[PromotionCandidate],
    context: PromotionContext,
    *,
    max_stacked_count: int = 3,
) -> tuple[list[AppliedDiscount], int]:
    eligible = sorted(
        (candidate for candidate in candidates if _eligible(candidate, context)),
        key=lambda candidate: (-candidate.priority, candidate.code, str(candidate.id)),
    )
    selected: list[PromotionCandidate] = []
    for candidate in eligible:
        if not selected:
            selected.append(candidate)
        elif selected[0].stackability == Stackability.EXCLUSIVE:
            break
        elif candidate.stackability == Stackability.EXCLUSIVE or (
            candidate.stackability == Stackability.STACKABLE_WITH_AUTOMATIC_ONLY
            and any(
                item.application_mode != PromotionApplicationMode.AUTOMATIC for item in selected
            )
        ):
            continue
        else:
            selected.append(candidate)
        if len(selected) >= max_stacked_count:
            break

    remaining = context.subtotal_minor
    applied: list[AppliedDiscount] = []
    for candidate in selected:
        benefits = candidate.benefits
        if candidate.promotion_type == PromotionType.PERCENTAGE:
            if benefits.percentage_basis_points is None:
                continue
            discount = round_discount(remaining, benefits.percentage_basis_points)
            if benefits.maximum_discount_minor is not None:
                discount = min(discount, benefits.maximum_discount_minor)
        elif candidate.promotion_type == PromotionType.FIXED_AMOUNT:
            discount = benefits.amounts.get(context.currency, 0)
        elif candidate.promotion_type == PromotionType.FIXED_PRICE:
            fixed_price = benefits.fixed_prices.get(context.currency)
            discount = max(0, remaining - fixed_price) if fixed_price is not None else 0
        elif candidate.promotion_type == PromotionType.FREE_ITEM:
            free_items = benefits.amounts.get(context.currency, 0)
            if free_items <= 0:
                continue
            if context.quantity <= 0:
                continue
            unit_amount = remaining // context.quantity
            discount = unit_amount * min(context.quantity, free_items)
        else:
            raise VavError(
                "PROMOTION_TYPE_NOT_IMPLEMENTED",
                "The configured promotion type is not implemented.",
                status_code=422,
            )
        discount = min(remaining, discount)
        if discount <= 0:
            continue
        remaining -= discount
        applied.append(
            AppliedDiscount(
                promotion_id=candidate.id,
                promotion_code=candidate.code,
                discount_type=candidate.promotion_type,
                discount_amount_minor=discount,
                description=f"{candidate.code} {candidate.promotion_type} discount",
            )
        )
    return applied, context.subtotal_minor - remaining


class PricingContextInput(BaseModel):
    region_code: str | None = None
    customer_segment: str | None = None
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    channel: Literal["user_web", "admin", "api"] = "user_web"
