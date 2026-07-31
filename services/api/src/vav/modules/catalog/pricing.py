from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.catalog import (
    Coupon,
    InventoryItem,
    Price,
    PriceBook,
    PricingQuote,
    Product,
    ProductSku,
    Promotion,
    SupportedCurrency,
)
from vav.models.commerce import Order
from vav.modules.catalog.domain import (
    AppliedDiscount,
    InventoryPolicy,
    PromotionApplicationMode,
    PromotionBenefits,
    PromotionCandidate,
    PromotionContext,
    PromotionRules,
    PromotionType,
    Stackability,
    apply_promotions,
)
from vav.modules.identity.audit import record_security_event


@dataclass(frozen=True, slots=True)
class PricingCalculation:
    sku_id: UUID
    product_id: UUID
    price_id: UUID
    price_book_id: UUID
    quantity: int
    currency: str
    unit_amount_minor: int
    subtotal_minor: int
    discounts: list[AppliedDiscount]
    discount_total_minor: int
    tax_estimate_minor: int | None
    total_minor: int
    inventory_reservation_required: bool
    resolved_at: datetime

    def snapshot(self) -> dict[str, object]:
        return {
            "algorithm_version": "pricing-v1",
            "product_id": str(self.product_id),
            "sku_id": str(self.sku_id),
            "price_id": str(self.price_id),
            "price_book_id": str(self.price_book_id),
            "quantity": self.quantity,
            "currency": self.currency,
            "unit_amount_minor": self.unit_amount_minor,
            "subtotal_minor": self.subtotal_minor,
            "discounts": [
                {
                    **asdict(discount),
                    "promotion_id": str(discount.promotion_id),
                }
                for discount in self.discounts
            ],
            "discount_total_minor": self.discount_total_minor,
            "tax_estimate_minor": self.tax_estimate_minor,
            "total_minor": self.total_minor,
            "inventory_reservation_required": self.inventory_reservation_required,
            "resolved_at": self.resolved_at.isoformat(),
        }


def quote_payload(quote: PricingQuote) -> dict[str, object]:
    snapshot = quote.calculation_snapshot
    discounts = snapshot.get("discounts", []) if isinstance(snapshot, dict) else []
    return {
        "quote_id": str(quote.id),
        "sku_id": str(quote.sku_id),
        "quantity": quote.quantity,
        "currency": quote.currency_code,
        "unit_amount_minor": quote.unit_amount_minor,
        "subtotal_minor": quote.subtotal_minor,
        "discounts": discounts,
        "discount_total_minor": quote.discount_total_minor,
        "tax_estimate_minor": quote.tax_estimate_minor,
        "total_minor": quote.total_minor,
        "price_id": str(quote.price_id),
        "price_book_id": str(quote.price_book_id),
        "inventory_reservation_required": bool(
            snapshot.get("inventory_reservation_required", False)
            if isinstance(snapshot, dict)
            else False
        ),
        "expires_at": quote.expires_at.isoformat(),
        "expired": quote.expires_at <= datetime.now(UTC),
        "consumed": quote.consumed_at is not None,
        "payment_status": "not_paid",
        "grants_entitlement": False,
    }


class PricingEngine:
    async def calculate(
        self,
        session: AsyncSession,
        *,
        sku_id: UUID,
        quantity: int,
        currency: str,
        requested_at: datetime,
        region_code: str | None,
        customer_segment: str | None,
        coupon_code: str | None,
        user_id: UUID | None,
    ) -> PricingCalculation:
        currency = currency.upper()
        if quantity <= 0 or quantity > get_settings().pricing_max_quantity_per_quote:
            raise VavError(
                "PRICING_QUANTITY_INVALID",
                "Requested quantity is outside the allowed range.",
                status_code=422,
            )
        currency_metadata = await session.get(SupportedCurrency, currency)
        if currency_metadata is None or not currency_metadata.enabled:
            raise VavError(
                "CURRENCY_NOT_SUPPORTED",
                "The requested currency is not supported.",
                status_code=422,
            )
        sku = await session.get(ProductSku, sku_id)
        product = await session.get(Product, sku.product_id) if sku else None
        if sku is None or product is None:
            raise VavError("CATALOG_SKU_NOT_FOUND", "SKU was not found.", status_code=404)
        self._validate_purchasable(product, sku, requested_at)
        price, price_book = await self.resolve_price(
            session,
            sku=sku,
            currency=currency,
            requested_at=requested_at,
            region_code=region_code,
            customer_segment=customer_segment,
        )
        subtotal = price.unit_amount_minor * quantity
        promotions = await self._promotion_candidates(
            session,
            product=product,
            sku=sku,
            currency=currency,
            requested_at=requested_at,
            coupon_code=coupon_code,
            user_id=user_id,
        )
        has_prior_purchase = False
        if user_id is not None:
            has_prior_purchase = (
                await session.scalar(
                    select(Order.id)
                    .where(
                        Order.user_id == user_id,
                        Order.status.in_(
                            (
                                "paid",
                                "fulfilling",
                                "fulfilled",
                                "partially_refunded",
                                "refunded",
                            )
                        ),
                    )
                    .limit(1)
                )
                is not None
            )
        applied, discount_total = apply_promotions(
            promotions,
            PromotionContext(
                product_id=product.id,
                sku_id=sku.id,
                category_id=product.category_id,
                currency=currency,
                subtotal_minor=subtotal,
                quantity=quantity,
                customer_segment=customer_segment,
                is_first_purchase=not has_prior_purchase,
            ),
            max_stacked_count=get_settings().promotion_max_stacked_count,
        )
        inventory = await session.scalar(
            select(InventoryItem).where(InventoryItem.sku_id == sku.id)
        )
        return PricingCalculation(
            sku_id=sku.id,
            product_id=product.id,
            price_id=price.id,
            price_book_id=price_book.id,
            quantity=quantity,
            currency=currency,
            unit_amount_minor=price.unit_amount_minor,
            subtotal_minor=subtotal,
            discounts=applied,
            discount_total_minor=discount_total,
            tax_estimate_minor=None,
            total_minor=max(0, subtotal - discount_total),
            inventory_reservation_required=(
                inventory is not None and inventory.inventory_policy != InventoryPolicy.UNLIMITED
            ),
            resolved_at=requested_at,
        )

    async def resolve_price(
        self,
        session: AsyncSession,
        *,
        sku: ProductSku,
        currency: str,
        requested_at: datetime,
        region_code: str | None,
        customer_segment: str | None,
    ) -> tuple[Price, PriceBook]:
        query_rows = (
            await session.execute(
                select(Price, PriceBook)
                .join(PriceBook, PriceBook.id == Price.price_book_id)
                .where(
                    Price.sku_id == sku.id,
                    Price.currency_code == currency,
                    Price.status == "active",
                    Price.valid_from <= requested_at,
                    or_(Price.valid_until.is_(None), Price.valid_until > requested_at),
                    PriceBook.status == "active",
                    or_(PriceBook.valid_from.is_(None), PriceBook.valid_from <= requested_at),
                    or_(PriceBook.valid_until.is_(None), PriceBook.valid_until > requested_at),
                    or_(PriceBook.region_code.is_(None), PriceBook.region_code == region_code),
                    or_(
                        PriceBook.customer_segment.is_(None),
                        PriceBook.customer_segment == customer_segment,
                    ),
                )
            )
        ).all()
        rows: list[tuple[Price, PriceBook]] = [(row[0], row[1]) for row in query_rows]
        if not rows:
            currencies = list(
                (
                    await session.scalars(
                        select(Price.currency_code)
                        .where(
                            Price.sku_id == sku.id,
                            Price.status == "active",
                            Price.valid_from <= requested_at,
                            or_(Price.valid_until.is_(None), Price.valid_until > requested_at),
                        )
                        .distinct()
                        .order_by(Price.currency_code)
                    )
                ).all()
            )
            raise VavError(
                "PRICE_NOT_AVAILABLE_IN_CURRENCY",
                "No active explicit price is available in the requested currency.",
                status_code=409,
                details=[{"available_currencies": currencies}],
            )

        def rank(row: tuple[Price, PriceBook]) -> tuple[int, int, int, datetime, str]:
            price, book = row
            return (
                book.priority,
                int(book.region_code is not None and book.region_code == region_code),
                int(
                    book.customer_segment is not None and book.customer_segment == customer_segment
                ),
                price.valid_from,
                str(price.id),
            )

        ranked = sorted(rows, key=rank, reverse=True)
        if len(ranked) > 1 and rank(ranked[0])[:-1] == rank(ranked[1])[:-1]:
            record_security_event(
                session,
                event_type="catalog.pricing.configuration_conflict",
                severity="error",
                actor_type="system",
                target_type="product_sku",
                target_id=sku.id,
                metadata={
                    "currency": currency,
                    "candidate_price_ids": [str(ranked[0][0].id), str(ranked[1][0].id)],
                },
            )
            await session.commit()
            raise VavError(
                "PRICING_CONFIGURATION_CONFLICT",
                "Multiple indistinguishable prices match this request.",
                status_code=409,
            )
        return ranked[0]

    @staticmethod
    def _validate_purchasable(product: Product, sku: ProductSku, requested_at: datetime) -> None:
        if product.status != "active" or product.visibility != "public" or sku.status != "active":
            raise VavError(
                "CATALOG_NOT_PURCHASABLE", "This SKU is not purchasable.", status_code=409
            )
        for starts_at, ends_at in (
            (product.purchasable_from, product.purchasable_until),
            (sku.purchasable_from, sku.purchasable_until),
        ):
            if starts_at and requested_at < starts_at:
                raise VavError(
                    "CATALOG_PURCHASE_NOT_STARTED",
                    "The purchase window has not started.",
                    status_code=409,
                )
            if ends_at and requested_at >= ends_at:
                raise VavError(
                    "CATALOG_PURCHASE_ENDED",
                    "The purchase window has ended.",
                    status_code=409,
                )

    async def _promotion_candidates(
        self,
        session: AsyncSession,
        *,
        product: Product,
        sku: ProductSku,
        currency: str,
        requested_at: datetime,
        coupon_code: str | None,
        user_id: UUID | None,
    ) -> list[PromotionCandidate]:
        promotions = list(
            (
                await session.scalars(
                    select(Promotion).where(
                        Promotion.status == "active",
                        Promotion.valid_from <= requested_at,
                        or_(
                            Promotion.valid_until.is_(None),
                            Promotion.valid_until > requested_at,
                        ),
                        or_(
                            Promotion.total_redemption_limit.is_(None),
                            Promotion.current_redemption_count < Promotion.total_redemption_limit,
                        ),
                        or_(
                            Promotion.budget_limit_minor.is_(None),
                            Promotion.current_discount_total_minor < Promotion.budget_limit_minor,
                        ),
                        Promotion.application_mode == PromotionApplicationMode.AUTOMATIC,
                    )
                )
            ).all()
        )
        if coupon_code:
            normalized = coupon_code.strip().upper()
            coupon_row = await session.execute(
                select(Coupon, Promotion)
                .join(Promotion, Promotion.id == Coupon.promotion_id)
                .where(
                    Coupon.coupon_code_normalized == normalized,
                    Coupon.status == "active",
                    or_(Coupon.valid_from.is_(None), Coupon.valid_from <= requested_at),
                    or_(Coupon.valid_until.is_(None), Coupon.valid_until > requested_at),
                    or_(
                        Coupon.total_redemption_limit.is_(None),
                        Coupon.current_redemption_count < Coupon.total_redemption_limit,
                    ),
                    Promotion.status == "active",
                    Promotion.valid_from <= requested_at,
                    or_(Promotion.valid_until.is_(None), Promotion.valid_until > requested_at),
                )
            )
            matched = coupon_row.one_or_none()
            if matched is None or (
                matched[0].assigned_user_id is not None and matched[0].assigned_user_id != user_id
            ):
                raise VavError(
                    "COUPON_NOT_APPLICABLE",
                    "The coupon cannot be applied to this quote.",
                    status_code=409,
                )
            if matched[1] not in promotions:
                promotions.append(matched[1])

        candidates: list[PromotionCandidate] = []
        for promotion in promotions:
            try:
                candidates.append(
                    PromotionCandidate(
                        id=promotion.id,
                        code=promotion.promotion_code,
                        promotion_type=PromotionType(promotion.promotion_type),
                        application_mode=PromotionApplicationMode(promotion.application_mode),
                        priority=promotion.priority,
                        stackability=Stackability(promotion.stackability),
                        rules=PromotionRules.model_validate(promotion.rules),
                        benefits=PromotionBenefits.model_validate(promotion.benefits),
                    )
                )
            except (ValueError, TypeError) as error:
                record_security_event(
                    session,
                    event_type="catalog.pricing.configuration_conflict",
                    severity="error",
                    actor_type="system",
                    target_type="promotion",
                    target_id=promotion.id,
                    reason=str(error),
                )
                await session.commit()
                raise VavError(
                    "PRICING_CONFIGURATION_CONFLICT",
                    "A promotion has an invalid rule configuration.",
                    status_code=409,
                ) from error
        return candidates

    async def create_quote(
        self,
        session: AsyncSession,
        calculation: PricingCalculation,
        *,
        anonymous_session_id: UUID,
        user_id: UUID | None = None,
        commit: bool = True,
    ) -> PricingQuote:
        quote = PricingQuote(
            user_id=user_id,
            anonymous_session_id=None if user_id else anonymous_session_id,
            sku_id=calculation.sku_id,
            price_id=calculation.price_id,
            price_book_id=calculation.price_book_id,
            quantity=calculation.quantity,
            currency_code=calculation.currency,
            unit_amount_minor=calculation.unit_amount_minor,
            subtotal_minor=calculation.subtotal_minor,
            discount_total_minor=calculation.discount_total_minor,
            tax_estimate_minor=calculation.tax_estimate_minor,
            total_minor=calculation.total_minor,
            calculation_snapshot=calculation.snapshot(),
            expires_at=datetime.now(UTC)
            + timedelta(minutes=get_settings().pricing_quote_ttl_minutes),
        )
        session.add(quote)
        await session.flush()
        record_security_event(
            session,
            event_type="catalog.pricing.quote_created",
            actor_type="user" if user_id else "anonymous",
            actor_user_id=user_id,
            target_type="pricing_quote",
            target_id=quote.id,
            metadata={
                "currency": quote.currency_code,
                "quantity": quote.quantity,
                "sku_id": str(quote.sku_id),
            },
        )
        if commit:
            await session.commit()
        return quote


pricing_engine = PricingEngine()
