from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.models.catalog import (
    Coupon,
    CouponRedemptionReservation,
    PricingQuote,
    Promotion,
)
from vav.modules.identity.audit import record_security_event


class CouponRedemptionService:
    async def reserve(
        self,
        session: AsyncSession,
        *,
        pricing_quote_id: UUID,
        promotion_id: UUID,
        coupon_id: UUID | None,
        user_id: UUID | None,
        order_id: UUID | None = None,
        commit: bool = True,
    ) -> CouponRedemptionReservation:
        quote = await session.scalar(
            select(PricingQuote).where(PricingQuote.id == pricing_quote_id).with_for_update()
        )
        if quote is None or quote.expires_at <= datetime.now(UTC) or quote.consumed_at is not None:
            raise VavError(
                "PRICING_QUOTE_INVALID",
                "Coupon redemption requires an active pricing quote.",
                status_code=409,
            )
        discount = self._quote_discount(quote, promotion_id)
        promotion = await session.scalar(
            select(Promotion).where(Promotion.id == promotion_id).with_for_update()
        )
        if promotion is None or promotion.status != "active":
            raise VavError(
                "COUPON_NOT_APPLICABLE",
                "The coupon cannot be applied to this quote.",
                status_code=409,
            )
        coupon: Coupon | None = None
        if coupon_id is not None:
            coupon = await session.scalar(
                select(Coupon).where(Coupon.id == coupon_id).with_for_update()
            )
            if (
                coupon is None
                or coupon.promotion_id != promotion.id
                or coupon.status != "active"
                or (coupon.assigned_user_id is not None and coupon.assigned_user_id != user_id)
            ):
                raise VavError(
                    "COUPON_NOT_APPLICABLE",
                    "The coupon cannot be applied to this quote.",
                    status_code=409,
                )
        active_statuses = ("reserved", "confirmed")
        pending_promotion = int(
            await session.scalar(
                select(func.count(CouponRedemptionReservation.id)).where(
                    CouponRedemptionReservation.promotion_id == promotion.id,
                    CouponRedemptionReservation.status.in_(active_statuses),
                )
            )
            or 0
        )
        if (
            promotion.total_redemption_limit is not None
            and pending_promotion >= promotion.total_redemption_limit
        ):
            raise self._not_applicable()
        if promotion.budget_limit_minor is not None:
            reserved_budget = int(
                await session.scalar(
                    select(
                        func.coalesce(
                            func.sum(CouponRedemptionReservation.reserved_discount_minor),
                            0,
                        )
                    ).where(
                        CouponRedemptionReservation.promotion_id == promotion.id,
                        CouponRedemptionReservation.status == "reserved",
                    )
                )
                or 0
            )
            if (
                promotion.current_discount_total_minor + reserved_budget + discount
                > promotion.budget_limit_minor
            ):
                raise self._not_applicable()
        if user_id is not None and promotion.per_user_redemption_limit is not None:
            per_user = int(
                await session.scalar(
                    select(func.count(CouponRedemptionReservation.id)).where(
                        CouponRedemptionReservation.promotion_id == promotion.id,
                        CouponRedemptionReservation.user_id == user_id,
                        CouponRedemptionReservation.status.in_(active_statuses),
                    )
                )
                or 0
            )
            if per_user >= promotion.per_user_redemption_limit:
                raise self._not_applicable()
        if coupon is not None:
            pending_coupon = int(
                await session.scalar(
                    select(func.count(CouponRedemptionReservation.id)).where(
                        CouponRedemptionReservation.coupon_id == coupon.id,
                        CouponRedemptionReservation.status.in_(active_statuses),
                    )
                )
                or 0
            )
            if (
                coupon.total_redemption_limit is not None
                and pending_coupon >= coupon.total_redemption_limit
            ):
                raise self._not_applicable()
            if user_id is not None and coupon.per_user_redemption_limit is not None:
                per_user_coupon = int(
                    await session.scalar(
                        select(func.count(CouponRedemptionReservation.id)).where(
                            CouponRedemptionReservation.coupon_id == coupon.id,
                            CouponRedemptionReservation.user_id == user_id,
                            CouponRedemptionReservation.status.in_(active_statuses),
                        )
                    )
                    or 0
                )
                if per_user_coupon >= coupon.per_user_redemption_limit:
                    raise self._not_applicable()
        reservation = CouponRedemptionReservation(
            coupon_id=coupon.id if coupon else None,
            promotion_id=promotion.id,
            user_id=user_id,
            pricing_quote_id=quote.id,
            order_id=order_id,
            status="reserved",
            reserved_discount_minor=discount,
            currency_code=quote.currency_code,
            expires_at=quote.expires_at,
        )
        session.add(reservation)
        await session.flush()
        record_security_event(
            session,
            event_type="catalog.coupon.redemption_reserved",
            actor_type="system",
            actor_user_id=user_id,
            target_type="coupon_redemption_reservation",
            target_id=reservation.id,
            metadata={
                "promotion_id": str(promotion.id),
                "currency": quote.currency_code,
            },
        )
        if commit:
            await session.commit()
        return reservation

    async def confirm(
        self, session: AsyncSession, reservation_id: UUID, *, commit: bool = True
    ) -> CouponRedemptionReservation:
        reservation = await session.scalar(
            select(CouponRedemptionReservation)
            .where(CouponRedemptionReservation.id == reservation_id)
            .with_for_update()
        )
        if reservation is None:
            raise VavError(
                "COUPON_RESERVATION_NOT_FOUND",
                "Coupon reservation was not found.",
                status_code=404,
            )
        if reservation.status == "confirmed":
            return reservation
        if reservation.status != "reserved" or reservation.expires_at <= datetime.now(UTC):
            raise VavError(
                "COUPON_RESERVATION_NOT_CONFIRMABLE",
                "Coupon reservation cannot be confirmed.",
                status_code=409,
            )
        promotion = await session.scalar(
            select(Promotion).where(Promotion.id == reservation.promotion_id).with_for_update()
        )
        coupon = (
            await session.scalar(
                select(Coupon).where(Coupon.id == reservation.coupon_id).with_for_update()
            )
            if reservation.coupon_id
            else None
        )
        if promotion is None:
            raise VavError("PROMOTION_NOT_FOUND", "Promotion was not found.", status_code=404)
        promotion.current_redemption_count += 1
        promotion.current_discount_total_minor += reservation.reserved_discount_minor
        if coupon is not None:
            coupon.current_redemption_count += 1
        reservation.status = "confirmed"
        reservation.confirmed_at = datetime.now(UTC)
        record_security_event(
            session,
            event_type="catalog.coupon.redeemed",
            actor_type="system",
            actor_user_id=reservation.user_id,
            target_type="coupon_redemption_reservation",
            target_id=reservation.id,
        )
        if commit:
            await session.commit()
        return reservation

    async def release(
        self,
        session: AsyncSession,
        reservation_id: UUID,
        *,
        expired: bool = False,
        commit: bool = True,
    ) -> CouponRedemptionReservation:
        reservation = await session.scalar(
            select(CouponRedemptionReservation)
            .where(CouponRedemptionReservation.id == reservation_id)
            .with_for_update()
        )
        if reservation is None:
            raise VavError(
                "COUPON_RESERVATION_NOT_FOUND",
                "Coupon reservation was not found.",
                status_code=404,
            )
        if reservation.status in {"released", "expired"}:
            return reservation
        if reservation.status == "confirmed":
            raise VavError(
                "COUPON_RESERVATION_CONFIRMED",
                "Confirmed coupon redemptions cannot be released.",
                status_code=409,
            )
        reservation.status = "expired" if expired else "released"
        reservation.released_at = datetime.now(UTC)
        if commit:
            await session.commit()
        return reservation

    async def expire_due(self, session: AsyncSession, limit: int = 500) -> int:
        ids = list(
            (
                await session.scalars(
                    select(CouponRedemptionReservation.id)
                    .where(
                        CouponRedemptionReservation.status == "reserved",
                        CouponRedemptionReservation.expires_at <= datetime.now(UTC),
                    )
                    .order_by(CouponRedemptionReservation.expires_at)
                    .limit(limit)
                )
            ).all()
        )
        for reservation_id in ids:
            await self.release(session, reservation_id, expired=True)
        return len(ids)

    @staticmethod
    def _quote_discount(quote: PricingQuote, promotion_id: UUID) -> int:
        discounts = quote.calculation_snapshot.get("discounts", [])
        if isinstance(discounts, list):
            for discount in discounts:
                if isinstance(discount, dict) and discount.get("promotion_id") == str(promotion_id):
                    amount = discount.get("discount_amount_minor")
                    if isinstance(amount, int) and amount >= 0:
                        return amount
        raise VavError(
            "COUPON_NOT_APPLICABLE",
            "The coupon cannot be applied to this quote.",
            status_code=409,
        )

    @staticmethod
    def _not_applicable() -> VavError:
        return VavError(
            "COUPON_NOT_APPLICABLE",
            "The coupon cannot be applied to this quote.",
            status_code=409,
        )


coupon_redemption_service = CouponRedemptionService()
