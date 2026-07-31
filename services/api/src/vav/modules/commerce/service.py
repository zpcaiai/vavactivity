from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.catalog import (
    Coupon,
    CouponRedemptionReservation,
    InventoryReservation,
    Price,
    PricingQuote,
    Product,
    ProductLocalization,
    ProductSku,
)
from vav.models.commerce import (
    Cart,
    CartItem,
    Entitlement,
    EntitlementActivationJob,
    EntitlementConsumption,
    Order,
    OrderItem,
    OrderStatusHistory,
    PaymentAttempt,
    PaymentLedgerEntry,
    PaymentWebhookEvent,
    ReconciliationDiscrepancy,
    Refund,
    RefundPolicySnapshot,
    Subscription,
    SubscriptionBillingCycle,
)
from vav.models.identity import User
from vav.models.system import IdempotencyKey, OutboxEvent
from vav.modules.catalog.inventory import inventory_service
from vav.modules.catalog.pricing import pricing_engine, quote_payload
from vav.modules.catalog.promotions import coupon_redemption_service
from vav.modules.commerce.domain import (
    CartStatus,
    EntitlementStatus,
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    SubscriptionStatus,
    WebhookProcessingStatus,
    ensure_order_transition,
    entitlement_type_for,
)
from vav.modules.commerce.providers import get_payment_provider
from vav.modules.commerce.providers.base import (
    CreateProviderPaymentRequest,
    ProviderRefundRequest,
    VerifiedWebhookEvent,
)
from vav.modules.commerce.schemas import CheckoutOrderRequest, CheckoutPreviewRequest
from vav.modules.identity.audit import record_security_event


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _order_number() -> str:
    return f"VAV-{_now():%Y%m%d}-{secrets.token_hex(5).upper()}"


def _refund_number() -> str:
    return f"REF-{_now():%Y%m%d}-{secrets.token_hex(5).upper()}"


def _history(
    session: AsyncSession,
    order: Order,
    target: OrderStatus,
    *,
    actor_type: str,
    actor_id: UUID | None = None,
    reason: str | None = None,
    reason_code: str | None = None,
) -> None:
    before = order.status
    if before != target:
        ensure_order_transition(before, target)
        order.status = target
        order.version += 1
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=before,
            to_status=target,
            reason=reason,
            reason_code=reason_code,
            actor_type=actor_type,
            actor_user_id=actor_id,
        )
    )


async def _advisory_lock(session: AsyncSession, value: str) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:value))"), {"value": value})


def order_payload(order: Order, *, items: list[OrderItem] | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "id": str(order.id),
        "order_number": order.order_number,
        "status": order.status,
        "currency": order.currency_code,
        "subtotal_minor": order.subtotal_minor,
        "discount_total_minor": order.discount_total_minor,
        "tax_total_minor": order.tax_total_minor,
        "total_minor": order.total_minor,
        "refunded_total_minor": order.refunded_total_minor,
        "placed_at": order.placed_at.isoformat() if order.placed_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "fulfilled_at": order.fulfilled_at.isoformat() if order.fulfilled_at else None,
    }
    if items is not None:
        result["items"] = [
            {
                "id": str(item.id),
                "product_name": item.product_name_snapshot,
                "sku_name": item.sku_name_snapshot,
                "quantity": item.quantity,
                "unit_amount_minor": item.unit_amount_minor,
                "discount_total_minor": item.discount_total_minor,
                "total_minor": item.total_minor,
                "fulfillment_type": item.fulfillment_type,
            }
            for item in items
        ]
    return result


class CartService:
    async def get_or_create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID | None,
        anonymous_session_id: UUID | None,
        currency: str,
    ) -> Cart:
        if user_id is None and anonymous_session_id is None:
            raise VavError(
                "CART_OWNER_REQUIRED",
                "Authentication or an anonymous session ID is required.",
                status_code=401,
            )
        currency = currency.upper()
        query = select(Cart).where(
            Cart.currency_code == currency,
            Cart.status.in_((CartStatus.ACTIVE, CartStatus.CHECKOUT_STARTED)),
        )
        query = query.where(
            Cart.user_id == user_id
            if user_id is not None
            else Cart.anonymous_session_id == anonymous_session_id
        )
        cart = await session.scalar(query)
        if cart is None:
            cart = Cart(
                user_id=user_id,
                anonymous_session_id=None if user_id else anonymous_session_id,
                currency_code=currency,
                status=CartStatus.ACTIVE,
                expires_at=_now() + timedelta(days=get_settings().commerce_cart_expiration_days),
            )
            session.add(cart)
            await session.flush()
            record_security_event(
                session,
                event_type="cart.created",
                actor_type="user" if user_id else "anonymous",
                actor_user_id=user_id,
                target_type="cart",
                target_id=cart.id,
            )
            await session.commit()
        return cart

    @staticmethod
    def ensure_owner(cart: Cart, user_id: UUID | None, anonymous_session_id: UUID | None) -> None:
        if cart.user_id is not None:
            owned = user_id == cart.user_id
        else:
            owned = (
                anonymous_session_id is not None
                and anonymous_session_id == cart.anonymous_session_id
            )
        if not owned:
            raise VavError("CART_NOT_FOUND", "Cart was not found.", status_code=404)

    async def payload(self, session: AsyncSession, cart: Cart) -> dict[str, object]:
        items = list(
            (
                await session.scalars(
                    select(CartItem)
                    .where(CartItem.cart_id == cart.id)
                    .order_by(CartItem.added_at, CartItem.id)
                )
            ).all()
        )
        return {
            "id": str(cart.id),
            "status": cart.status,
            "currency": cart.currency_code,
            "version": cart.version,
            "expires_at": cart.expires_at.isoformat() if cart.expires_at else None,
            "items": [
                {
                    "id": str(item.id),
                    "sku_id": str(item.sku_id),
                    "quantity": item.quantity,
                    "coupon_code": item.coupon_code,
                    "last_quote_id": str(item.last_quote_id) if item.last_quote_id else None,
                }
                for item in items
            ],
        }

    async def preview(
        self,
        session: AsyncSession,
        *,
        cart: Cart,
        request: CheckoutPreviewRequest,
        user_id: UUID | None,
        commit: bool = True,
    ) -> dict[str, object]:
        self.ensure_owner(cart, user_id, request.anonymous_session_id)
        items = list(
            (
                await session.scalars(
                    select(CartItem)
                    .where(CartItem.cart_id == cart.id)
                    .order_by(CartItem.added_at, CartItem.id)
                    .with_for_update()
                )
            ).all()
        )
        if not items:
            raise VavError("CART_EMPTY", "Cart is empty.", status_code=409)
        quotes: list[PricingQuote] = []
        for item in items:
            calculation = await pricing_engine.calculate(
                session,
                sku_id=item.sku_id,
                quantity=item.quantity,
                currency=cart.currency_code,
                requested_at=_now(),
                region_code=request.region_code,
                customer_segment=None,
                coupon_code=item.coupon_code,
                user_id=user_id,
            )
            quote = await pricing_engine.create_quote(
                session,
                calculation,
                anonymous_session_id=cart.anonymous_session_id or uuid4(),
                user_id=user_id,
                commit=False,
            )
            item.last_quote_id = quote.id
            quotes.append(quote)
        cart.status = CartStatus.CHECKOUT_STARTED
        cart.version += 1
        if commit:
            await session.commit()
        return {
            "cart_id": str(cart.id),
            "currency": cart.currency_code,
            "items": [quote_payload(quote) for quote in quotes],
            "subtotal_minor": sum(quote.subtotal_minor for quote in quotes),
            "discount_total_minor": sum(quote.discount_total_minor for quote in quotes),
            "tax_estimate_minor": None,
            "total_minor": sum(quote.total_minor for quote in quotes),
            "quote_expires_at": min(quote.expires_at for quote in quotes).isoformat(),
            "available_payment_providers": get_settings().payment_enabled_providers,
        }


class OrderService:
    async def create(
        self,
        session: AsyncSession,
        *,
        user: User,
        request: CheckoutOrderRequest,
        idempotency_key: str,
    ) -> Order:
        request_data = request.model_dump(mode="json")
        request_hash = _hash(request_data)
        scope = f"checkout:{user.id}"
        await _advisory_lock(session, f"{scope}:{idempotency_key}")
        existing_key = await session.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.scope == scope, IdempotencyKey.key == idempotency_key
            )
        )
        if existing_key is not None:
            if existing_key.request_hash != request_hash:
                raise VavError(
                    "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST",
                    "The idempotency key was already used for a different request.",
                    status_code=409,
                )
            order_id = (existing_key.response_body or {}).get("order_id")
            order = await session.get(Order, UUID(str(order_id))) if order_id else None
            if order is not None:
                return order
        cart = await session.scalar(
            select(Cart).where(Cart.id == request.cart_id).with_for_update()
        )
        if cart is None:
            raise VavError("CART_NOT_FOUND", "Cart was not found.", status_code=404)
        cart_service.ensure_owner(cart, user.id, request.anonymous_session_id)
        preview = await cart_service.preview(
            session, cart=cart, request=request, user_id=user.id, commit=False
        )
        if (
            request.expected_total_minor is not None
            and request.expected_total_minor != preview["total_minor"]
        ):
            raise VavError(
                "CHECKOUT_TOTAL_CHANGED",
                "The server-calculated checkout total changed.",
                status_code=409,
                details=[{"authoritative_total_minor": preview["total_minor"]}],
            )
        cart_items = list(
            (
                await session.scalars(
                    select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)
                )
            ).all()
        )
        quotes = [
            await session.scalar(
                select(PricingQuote).where(PricingQuote.id == item.last_quote_id).with_for_update()
            )
            for item in cart_items
        ]
        if any(quote is None for quote in quotes):
            raise VavError("PRICING_QUOTE_INVALID", "A checkout quote is missing.", status_code=409)
        valid_quotes = [quote for quote in quotes if quote is not None]
        order = Order(
            id=uuid4(),
            order_number=_order_number(),
            user_id=user.id,
            status=OrderStatus.DRAFT,
            currency_code=cart.currency_code,
            subtotal_minor=sum(quote.subtotal_minor for quote in valid_quotes),
            discount_total_minor=sum(quote.discount_total_minor for quote in valid_quotes),
            tax_total_minor=0,
            total_minor=sum(quote.total_minor for quote in valid_quotes),
            pricing_quote_id=valid_quotes[0].id,
            billing_email=str(request.billing_email),
            billing_name=request.billing_name,
            locale=request.locale,
            region_code=request.region_code,
            placed_at=_now(),
        )
        session.add(order)
        await session.flush()
        for cart_item, quote in zip(cart_items, valid_quotes, strict=True):
            if quote.consumed_at or quote.expires_at <= _now() or quote.user_id != user.id:
                raise VavError(
                    "PRICING_QUOTE_INVALID",
                    "The checkout quote is expired, consumed or belongs to another user.",
                    status_code=409,
                )
            sku = await session.get(ProductSku, quote.sku_id)
            price = await session.get(Price, quote.price_id)
            product = await session.get(Product, sku.product_id) if sku else None
            localized = (
                await session.scalar(
                    select(ProductLocalization)
                    .where(
                        ProductLocalization.product_id == product.id,
                        ProductLocalization.locale.in_((request.locale, product.default_locale)),
                    )
                    .order_by((ProductLocalization.locale == request.locale).desc())
                    .limit(1)
                )
                if product
                else None
            )
            if not sku or not price or not product or not localized:
                raise VavError(
                    "CHECKOUT_SNAPSHOT_UNAVAILABLE",
                    "The order snapshot cannot be created.",
                    status_code=409,
                )
            discounts_snapshot = quote.calculation_snapshot.get("discounts", [])
            promotion_snapshot = (
                [entry for entry in discounts_snapshot if isinstance(entry, dict)]
                if isinstance(discounts_snapshot, list)
                else []
            )
            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                sku_id=sku.id,
                price_id=price.id,
                pricing_quote_id=quote.id,
                product_code=product.product_code,
                sku_code=sku.sku_code,
                product_name_snapshot=localized.name,
                sku_name_snapshot=sku.internal_name,
                product_type=product.product_type,
                fulfillment_type=product.fulfillment_type,
                quantity=quote.quantity,
                unit_amount_minor=quote.unit_amount_minor,
                subtotal_minor=quote.subtotal_minor,
                discount_total_minor=quote.discount_total_minor,
                total_minor=quote.total_minor,
                fulfillment_snapshot=sku.fulfillment_configuration,
                promotion_snapshot=promotion_snapshot,
            )
            session.add(order_item)
            await session.flush()
            session.add(
                RefundPolicySnapshot(
                    order_item_id=order_item.id,
                    policy_code="commerce-default-review",
                    policy_version=request.refund_policy_version,
                    policy_snapshot={
                        "approval_required": True,
                        "consumed_entitlement_action": "manual_review",
                    },
                )
            )
            reservation = await inventory_service.reserve(
                session,
                sku_id=sku.id,
                quantity=quote.quantity,
                user_id=user.id,
                anonymous_session_id=None,
                pricing_quote_id=quote.id,
                order_id=order.id,
                commit=False,
            )
            if reservation is not None:
                reservation.expires_at = _now() + timedelta(
                    minutes=get_settings().commerce_order_expiration_minutes
                )
            discounts = quote.calculation_snapshot.get("discounts", [])
            if isinstance(discounts, list):
                for discount in discounts:
                    if not isinstance(discount, dict) or not discount.get("promotion_id"):
                        continue
                    promotion_id = UUID(str(discount["promotion_id"]))
                    coupon = (
                        await session.scalar(
                            select(Coupon).where(
                                Coupon.promotion_id == promotion_id,
                                Coupon.coupon_code_normalized
                                == (cart_item.coupon_code or "").upper(),
                            )
                        )
                        if cart_item.coupon_code
                        else None
                    )
                    coupon_reservation = await coupon_redemption_service.reserve(
                        session,
                        pricing_quote_id=quote.id,
                        promotion_id=promotion_id,
                        coupon_id=coupon.id if coupon else None,
                        user_id=user.id,
                        order_id=order.id,
                        commit=False,
                    )
                    coupon_reservation.expires_at = _now() + timedelta(
                        minutes=get_settings().commerce_order_expiration_minutes
                    )
            quote.consumed_at = _now()
        _history(
            session,
            order,
            OrderStatus.PENDING_PAYMENT,
            actor_type="user",
            actor_id=user.id,
            reason_code="checkout_completed",
        )
        cart.status = CartStatus.CONVERTED
        cart.converted_order_id = order.id
        cart.user_id = user.id
        cart.anonymous_session_id = None
        session.add(
            OutboxEvent(
                topic="commerce.order.created",
                aggregate_type="order",
                aggregate_id=str(order.id),
                payload={"order_id": str(order.id), "order_number": order.order_number},
            )
        )
        record_security_event(
            session,
            event_type="order.created",
            actor_type="user",
            actor_user_id=user.id,
            target_type="order",
            target_id=order.id,
            metadata={"currency": order.currency_code, "total_minor": order.total_minor},
        )
        session.add(
            IdempotencyKey(
                scope=scope,
                key=idempotency_key,
                request_hash=request_hash,
                response_status=201,
                response_body={"order_id": str(order.id)},
                expires_at=_now()
                + timedelta(hours=get_settings().commerce_checkout_idempotency_ttl_hours),
            )
        )
        await session.commit()
        return order


class PaymentService:
    async def create(
        self,
        session: AsyncSession,
        *,
        order: Order,
        provider_name: str,
        user_id: UUID,
        idempotency_key: str,
    ) -> PaymentAttempt:
        if order.user_id != user_id:
            raise VavError("ORDER_NOT_FOUND", "Order was not found.", status_code=404)
        await _advisory_lock(session, f"payment:{provider_name}:{idempotency_key}")
        existing = await session.scalar(
            select(PaymentAttempt).where(
                PaymentAttempt.provider == provider_name,
                PaymentAttempt.provider_environment == get_settings().payment_environment,
                PaymentAttempt.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.order_id != order.id:
                raise VavError(
                    "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST",
                    "The payment key belongs to another order.",
                    status_code=409,
                )
            return existing
        if order.status not in {OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_FAILED}:
            raise VavError(
                "ORDER_NOT_PAYABLE", "This order cannot start a payment.", status_code=409
            )
        item = await session.scalar(select(OrderItem).where(OrderItem.order_id == order.id))
        price = await session.get(Price, item.price_id) if item else None
        if item is None or price is None:
            raise VavError(
                "ORDER_SNAPSHOT_INVALID", "Order snapshot is incomplete.", status_code=409
            )
        provider = get_payment_provider(provider_name)
        result = await provider.create_payment(
            CreateProviderPaymentRequest(
                order_id=order.id,
                order_number=order.order_number,
                user_id=user_id,
                amount_minor=order.total_minor,
                currency=order.currency_code,
                idempotency_key=idempotency_key,
                recurring=price.billing_type == "recurring",
                billing_interval=price.billing_interval,
                billing_interval_count=price.billing_interval_count,
            )
        )
        action = dict(result.client_action)
        if result.provider_subscription_id:
            action["provider_subscription_id"] = result.provider_subscription_id
        attempt = PaymentAttempt(
            order_id=order.id,
            provider=provider.name,
            provider_environment=provider.environment,
            provider_payment_id=result.provider_payment_id,
            provider_customer_id=result.provider_customer_id,
            status=result.status,
            amount_minor=order.total_minor,
            currency_code=order.currency_code,
            client_action=action,
            idempotency_key=idempotency_key,
        )
        session.add(attempt)
        _history(
            session,
            order,
            OrderStatus.PAYMENT_PROCESSING,
            actor_type="user",
            actor_id=user_id,
            reason_code="payment_attempt_created",
        )
        record_security_event(
            session,
            event_type="payment.attempt.created",
            actor_type="user",
            actor_user_id=user_id,
            target_type="payment_attempt",
            target_id=attempt.id,
            metadata={"provider": provider.name, "environment": provider.environment},
        )
        await session.commit()
        return attempt

    @staticmethod
    def payload(attempt: PaymentAttempt) -> dict[str, object]:
        return {
            "id": str(attempt.id),
            "order_id": str(attempt.order_id),
            "provider": attempt.provider,
            "environment": attempt.provider_environment,
            "status": attempt.status,
            "amount_minor": attempt.amount_minor,
            "currency": attempt.currency_code,
            "client_action": attempt.client_action,
        }


class EntitlementService:
    async def activate_order(self, session: AsyncSession, order: Order) -> list[Entitlement]:
        items = list(
            (
                await session.scalars(
                    select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
                )
            ).all()
        )
        entitlements: list[Entitlement] = []
        for item in items:
            kind = entitlement_type_for(item.fulfillment_type, item.product_type)
            existing = await session.scalar(
                select(Entitlement).where(
                    Entitlement.order_item_id == item.id,
                    Entitlement.entitlement_type == kind,
                )
            )
            if existing is not None:
                entitlements.append(existing)
                continue
            config = item.fulfillment_snapshot
            resource_value = next(
                (
                    config[key]
                    for key in ("activity_id", "course_id", "counseling_service_id")
                    if key in config
                ),
                None,
            )
            resource_id: UUID | None = None
            if resource_value:
                try:
                    resource_id = UUID(str(resource_value))
                except ValueError:
                    resource_id = None
            quantity = item.quantity
            if kind.value == "counseling_credits":
                quantity *= int(str(config.get("session_count", 1)))
            elif kind.value in {"ai_credits", "ai_subscription"}:
                quantity *= int(str(config.get("credit_count", 1)))
            elif kind.value in {"membership", "course_access", "activity_admission"}:
                quantity = 1
            validity_days = config.get("validity_days") or config.get("duration_days")
            expires_at = (
                _now() + timedelta(days=int(str(validity_days)))
                if validity_days is not None
                else None
            )
            entitlement = Entitlement(
                user_id=order.user_id,
                order_id=order.id,
                order_item_id=item.id,
                entitlement_type=kind,
                status=EntitlementStatus.ACTIVE,
                resource_type=item.product_type,
                resource_id=resource_id,
                quantity_granted=quantity,
                configuration_snapshot=config,
                starts_at=_now(),
                expires_at=expires_at,
                activated_at=_now(),
            )
            session.add(entitlement)
            await session.flush()
            session.add(
                EntitlementActivationJob(
                    order_item_id=item.id,
                    status="succeeded",
                    attempts=1,
                )
            )
            record_security_event(
                session,
                event_type="entitlement.activated",
                actor_type="system",
                target_type="entitlement",
                target_id=entitlement.id,
                metadata={"order_item_id": str(item.id), "type": kind},
            )
            session.add(
                OutboxEvent(
                    topic="entitlement.activated",
                    aggregate_type="entitlement",
                    aggregate_id=str(entitlement.id),
                    payload={
                        "entitlement_id": str(entitlement.id),
                        "order_id": str(order.id),
                        "order_item_id": str(item.id),
                        "user_id": str(order.user_id),
                        "entitlement_type": str(kind),
                    },
                )
            )
            if kind.value == "activity_admission":
                # Local import preserves the Commerce -> Activity event boundary
                # without creating an import cycle during application startup.
                from vav.modules.activities.service import registration_service

                await registration_service.project_entitlement(session, entitlement)
            if kind.value == "course_access":
                # Enrollment is projected only from the server-verified
                # entitlement event. A browser payment return is never trusted.
                from vav.modules.courses.service import enrollment_service

                await enrollment_service.project_entitlement(session, entitlement)
            if kind.value == "counseling_credits":
                # Paid appointments are confirmed only from the server-verified
                # entitlement projection, never from a browser return URL.
                from vav.modules.counseling.service import appointment_service

                await appointment_service.project_entitlement(session, entitlement)
            entitlements.append(entitlement)
        return entitlements

    async def consume(
        self,
        session: AsyncSession,
        *,
        entitlement_id: UUID,
        user_id: UUID,
        quantity: int,
        expected_version: int,
        idempotency_key: str,
        commit: bool = True,
    ) -> Entitlement:
        entitlement = await session.scalar(
            select(Entitlement).where(Entitlement.id == entitlement_id).with_for_update()
        )
        if entitlement is None or entitlement.user_id != user_id:
            raise VavError("ENTITLEMENT_NOT_FOUND", "Entitlement was not found.", status_code=404)
        existing = await session.scalar(
            select(EntitlementConsumption).where(
                EntitlementConsumption.entitlement_id == entitlement.id,
                EntitlementConsumption.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return entitlement
        if entitlement.version != expected_version:
            raise VavError(
                "ENTITLEMENT_VERSION_CONFLICT",
                "Entitlement changed since it was loaded.",
                status_code=409,
            )
        if (
            entitlement.status != EntitlementStatus.ACTIVE
            or (entitlement.starts_at and entitlement.starts_at > _now())
            or (entitlement.expires_at and entitlement.expires_at <= _now())
        ):
            raise VavError(
                "ENTITLEMENT_NOT_CONSUMABLE",
                "Entitlement is not active in the current period.",
                status_code=409,
            )
        granted = entitlement.quantity_granted
        if granted is None or entitlement.quantity_consumed + quantity > granted:
            raise VavError(
                "ENTITLEMENT_QUANTITY_EXCEEDED",
                "The requested entitlement quantity is unavailable.",
                status_code=409,
            )
        entitlement.quantity_consumed += quantity
        entitlement.version += 1
        if entitlement.quantity_consumed == granted:
            entitlement.status = EntitlementStatus.EXHAUSTED
        session.add(
            EntitlementConsumption(
                entitlement_id=entitlement.id,
                idempotency_key=idempotency_key,
                quantity=quantity,
                status="confirmed",
            )
        )
        if commit:
            await session.commit()
        return entitlement


class WebhookService:
    async def ingest(
        self,
        session: AsyncSession,
        *,
        provider_name: str,
        headers: dict[str, str],
        raw_body: bytes,
        replay_event: PaymentWebhookEvent | None = None,
    ) -> PaymentWebhookEvent:
        provider = get_payment_provider(provider_name)
        if replay_event is None:
            verified = await provider.verify_webhook(headers, raw_body)
            await _advisory_lock(
                session,
                f"webhook:{provider.name}:{provider.environment}:{verified.provider_event_id}",
            )
            duplicate = await session.scalar(
                select(PaymentWebhookEvent).where(
                    PaymentWebhookEvent.provider == provider.name,
                    PaymentWebhookEvent.provider_environment == provider.environment,
                    PaymentWebhookEvent.provider_event_id == verified.provider_event_id,
                )
            )
            if duplicate is not None:
                record_security_event(
                    session,
                    event_type="webhook.duplicate_received",
                    actor_type="provider",
                    target_type="payment_webhook_event",
                    target_id=duplicate.id,
                )
                await session.commit()
                return duplicate
            event = PaymentWebhookEvent(
                provider=provider.name,
                provider_environment=provider.environment,
                provider_event_id=verified.provider_event_id,
                event_type=verified.event_type,
                signature_verified=True,
                payload=verified.payload,
                payload_hash=hashlib.sha256(raw_body).hexdigest(),
                processing_status=WebhookProcessingStatus.RECEIVED,
            )
            session.add(event)
            await session.flush()
            record_security_event(
                session,
                event_type="webhook.received",
                actor_type="provider",
                target_type="payment_webhook_event",
                target_id=event.id,
                metadata={"provider": provider.name, "event_type": event.event_type},
            )
        else:
            event = replay_event
            replay_data = event.payload.get("data", {})
            verified = VerifiedWebhookEvent(
                provider_event_id=event.provider_event_id,
                event_type=event.event_type,
                data=dict(replay_data) if isinstance(replay_data, dict) else {},
                payload=event.payload,
            )
        event.processing_status = WebhookProcessingStatus.PROCESSING
        event.processing_attempts += 1
        try:
            await self._process(session, event, verified)
            event.processing_status = WebhookProcessingStatus.PROCESSED
            event.processed_at = _now()
            event.last_error_code = None
            event.last_error_safe = None
        except VavError as error:
            event.processing_status = WebhookProcessingStatus.FAILED
            event.last_error_code = error.code
            event.last_error_safe = error.message
            record_security_event(
                session,
                event_type="webhook.processing_failed",
                severity="error",
                actor_type="system",
                target_type="payment_webhook_event",
                target_id=event.id,
                reason=error.message,
                metadata={"error_code": error.code},
            )
            await session.commit()
            return event
        await session.commit()
        return event

    async def _process(
        self,
        session: AsyncSession,
        event: PaymentWebhookEvent,
        verified: VerifiedWebhookEvent,
    ) -> None:
        normalized = self._event_kind(event.provider, verified.event_type)
        if normalized == "payment_succeeded":
            await self._payment_succeeded(session, event, verified.data)
        elif normalized == "payment_failed":
            await self._payment_failed(session, event, verified.data)
        elif normalized == "refund_succeeded":
            await self._refund_succeeded(session, event, verified.data)
        elif normalized == "renewal_succeeded":
            await self._renewal(session, event, verified.data, succeeded=True)
        elif normalized == "renewal_failed":
            await self._renewal(session, event, verified.data, succeeded=False)
        else:
            event.processing_status = WebhookProcessingStatus.IGNORED

    async def _attempt(
        self,
        session: AsyncSession,
        event: PaymentWebhookEvent,
        data: dict[str, object],
    ) -> PaymentAttempt:
        provider_payment_id = data.get("provider_payment_id")
        attempt = (
            await session.scalar(
                select(PaymentAttempt)
                .where(
                    PaymentAttempt.provider == event.provider,
                    PaymentAttempt.provider_environment == event.provider_environment,
                    PaymentAttempt.provider_payment_id == str(provider_payment_id),
                )
                .with_for_update()
            )
            if provider_payment_id
            else None
        )
        if attempt is None:
            raise VavError(
                "WEBHOOK_PAYMENT_UNKNOWN",
                "Webhook payment does not match an internal attempt.",
                status_code=409,
            )
        return attempt

    async def _payment_succeeded(
        self,
        session: AsyncSession,
        event: PaymentWebhookEvent,
        data: dict[str, object],
    ) -> None:
        attempt = await self._attempt(session, event, data)
        order = await session.scalar(
            select(Order).where(Order.id == attempt.order_id).with_for_update()
        )
        if order is None:
            raise VavError("ORDER_NOT_FOUND", "Order was not found.", status_code=404)
        if str(data.get("order_id")) not in {"None", str(order.id)}:
            raise self._mismatch(session, order, "payment.order_mismatch")
        amount = data.get("amount_minor")
        currency = str(data.get("currency", "")).upper()
        if amount != attempt.amount_minor:
            raise self._mismatch(session, order, "payment.amount_mismatch")
        if currency != attempt.currency_code:
            raise self._mismatch(session, order, "payment.currency_mismatch")
        if attempt.status == PaymentStatus.SUCCEEDED:
            return
        if order.status not in {
            OrderStatus.PAYMENT_PROCESSING,
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.PAID,
            OrderStatus.FULFILLING,
            OrderStatus.FULFILLED,
        }:
            raise self._mismatch(session, order, "payment.order_state_mismatch")
        if order.status == OrderStatus.PENDING_PAYMENT:
            _history(session, order, OrderStatus.PAYMENT_PROCESSING, actor_type="provider")
        attempt.status = PaymentStatus.SUCCEEDED
        if order.status == OrderStatus.PAYMENT_PROCESSING:
            _history(session, order, OrderStatus.PAID, actor_type="provider")
            order.paid_at = _now()
        inventory_ids = list(
            (
                await session.scalars(
                    select(InventoryReservation.id).where(InventoryReservation.order_id == order.id)
                )
            ).all()
        )
        for reservation_id in inventory_ids:
            await inventory_service.confirm(session, reservation_id, commit=False)
        coupon_ids = list(
            (
                await session.scalars(
                    select(CouponRedemptionReservation.id).where(
                        CouponRedemptionReservation.order_id == order.id
                    )
                )
            ).all()
        )
        for reservation_id in coupon_ids:
            await coupon_redemption_service.confirm(session, reservation_id, commit=False)
        if order.status == OrderStatus.PAID:
            _history(session, order, OrderStatus.FULFILLING, actor_type="system")
        await entitlement_service.activate_order(session, order)
        if order.status == OrderStatus.FULFILLING:
            _history(session, order, OrderStatus.FULFILLED, actor_type="system")
            order.fulfilled_at = _now()
        await self._create_subscription(session, attempt, order, data, event.provider_event_id)
        session.add(
            PaymentLedgerEntry(
                entry_type="payment_succeeded",
                order_id=order.id,
                payment_attempt_id=attempt.id,
                provider=attempt.provider,
                provider_reference=attempt.provider_payment_id,
                currency_code=order.currency_code,
                amount_minor=order.total_minor,
                effective_at=_now(),
            )
        )
        record_security_event(
            session,
            event_type="payment.succeeded",
            actor_type="provider",
            target_type="payment_attempt",
            target_id=attempt.id,
            metadata={"provider_event_id": event.provider_event_id},
        )

    async def _create_subscription(
        self,
        session: AsyncSession,
        attempt: PaymentAttempt,
        order: Order,
        data: dict[str, object],
        provider_event_id: str,
    ) -> None:
        item = await session.scalar(select(OrderItem).where(OrderItem.order_id == order.id))
        price = await session.get(Price, item.price_id) if item else None
        if item is None or price is None or price.billing_type != "recurring":
            return
        subscription_id = data.get("provider_subscription_id")
        if not subscription_id and attempt.client_action:
            subscription_id = attempt.client_action.get("provider_subscription_id")
        if not subscription_id:
            raise VavError(
                "SUBSCRIPTION_PROVIDER_ID_MISSING",
                "Recurring payment lacks a Provider subscription ID.",
                status_code=409,
            )
        subscription = await session.scalar(
            select(Subscription).where(
                Subscription.provider == attempt.provider,
                Subscription.provider_environment == attempt.provider_environment,
                Subscription.provider_subscription_id == str(subscription_id),
            )
        )
        start = _now()
        end = start + self._billing_delta(
            price.billing_interval or "month", price.billing_interval_count or 1
        )
        if subscription is None:
            subscription = Subscription(
                user_id=order.user_id,
                sku_id=item.sku_id,
                provider=attempt.provider,
                provider_environment=attempt.provider_environment,
                provider_subscription_id=str(subscription_id),
                status=SubscriptionStatus.ACTIVE,
                currency_code=order.currency_code,
                recurring_amount_minor=order.total_minor,
                billing_interval=price.billing_interval or "month",
                billing_interval_count=price.billing_interval_count or 1,
                current_period_start=start,
                current_period_end=end,
                latest_order_id=order.id,
            )
            session.add(subscription)
            await session.flush()
        session.add(
            SubscriptionBillingCycle(
                subscription_id=subscription.id,
                order_id=order.id,
                provider_event_id=provider_event_id,
                status="paid",
                amount_minor=order.total_minor,
                currency_code=order.currency_code,
                period_start=start,
                period_end=end,
            )
        )

    async def _payment_failed(
        self,
        session: AsyncSession,
        event: PaymentWebhookEvent,
        data: dict[str, object],
    ) -> None:
        attempt = await self._attempt(session, event, data)
        if attempt.status in {PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED}:
            return
        order = await session.scalar(
            select(Order).where(Order.id == attempt.order_id).with_for_update()
        )
        if order and order.status == OrderStatus.PAYMENT_PROCESSING:
            _history(session, order, OrderStatus.PAYMENT_FAILED, actor_type="provider")
        attempt.status = PaymentStatus.FAILED
        attempt.failure_code = str(data.get("failure_code", "provider_declined"))

    async def _refund_succeeded(
        self,
        session: AsyncSession,
        event: PaymentWebhookEvent,
        data: dict[str, object],
    ) -> None:
        provider_refund_id = data.get("provider_refund_id")
        refund = await session.scalar(
            select(Refund)
            .where(
                Refund.provider == event.provider,
                Refund.provider_environment == event.provider_environment,
                Refund.provider_refund_id == str(provider_refund_id),
            )
            .with_for_update()
        )
        if refund is None:
            raise VavError("REFUND_NOT_FOUND", "Refund was not found.", status_code=404)
        if refund.status == RefundStatus.SUCCEEDED:
            return
        order = await session.scalar(
            select(Order).where(Order.id == refund.order_id).with_for_update()
        )
        if (
            order is None
            or data.get("amount_minor") != refund.amount_minor
            or str(data.get("currency", "")).upper() != refund.currency_code
        ):
            raise VavError(
                "REFUND_PROVIDER_MISMATCH",
                "Refund amount, currency or order does not match.",
                status_code=409,
            )
        refund.status = RefundStatus.SUCCEEDED
        refund.succeeded_at = _now()
        order.refunded_total_minor += refund.amount_minor
        target = (
            OrderStatus.REFUNDED
            if order.refunded_total_minor == order.total_minor
            else OrderStatus.PARTIALLY_REFUNDED
        )
        if target == OrderStatus.REFUNDED:
            entitlements = list(
                (
                    await session.scalars(
                        select(Entitlement).where(Entitlement.order_id == order.id)
                    )
                ).all()
            )
            has_consumed_entitlement = any(
                entitlement.quantity_consumed for entitlement in entitlements
            )
            if has_consumed_entitlement:
                target = OrderStatus.MANUAL_REVIEW
        _history(session, order, target, actor_type="provider", reason_code="refund_succeeded")
        if order.refunded_total_minor == order.total_minor:
            for entitlement in entitlements:
                if not entitlement.quantity_consumed:
                    entitlement.status = EntitlementStatus.REVOKED
                    entitlement.revoked_at = _now()
                    entitlement.revoke_reason = "full_refund"
                    if str(entitlement.entitlement_type) == "course_access":
                        from vav.modules.courses.service import enrollment_service

                        await enrollment_service.sync_entitlement(session, entitlement)
        session.add(
            PaymentLedgerEntry(
                entry_type="refund_succeeded",
                order_id=order.id,
                refund_id=refund.id,
                provider=refund.provider,
                provider_reference=refund.provider_refund_id,
                currency_code=refund.currency_code,
                amount_minor=-refund.amount_minor,
                effective_at=_now(),
            )
        )

    async def _renewal(
        self,
        session: AsyncSession,
        event: PaymentWebhookEvent,
        data: dict[str, object],
        *,
        succeeded: bool,
    ) -> None:
        provider_id = data.get("provider_subscription_id")
        subscription = await session.scalar(
            select(Subscription)
            .where(
                Subscription.provider == event.provider,
                Subscription.provider_environment == event.provider_environment,
                Subscription.provider_subscription_id == str(provider_id),
            )
            .with_for_update()
        )
        if subscription is None:
            raise VavError("SUBSCRIPTION_NOT_FOUND", "Subscription was not found.", status_code=404)
        if await session.scalar(
            select(SubscriptionBillingCycle.id).where(
                SubscriptionBillingCycle.subscription_id == subscription.id,
                SubscriptionBillingCycle.provider_event_id == event.provider_event_id,
            )
        ):
            return
        start = subscription.current_period_end or _now()
        end = start + self._billing_delta(
            subscription.billing_interval, subscription.billing_interval_count
        )
        subscription.status = (
            SubscriptionStatus.ACTIVE if succeeded else SubscriptionStatus.PAST_DUE
        )
        if succeeded:
            subscription.current_period_start = start
            subscription.current_period_end = end
        session.add(
            SubscriptionBillingCycle(
                subscription_id=subscription.id,
                provider_event_id=event.provider_event_id,
                status="paid" if succeeded else "failed",
                amount_minor=subscription.recurring_amount_minor,
                currency_code=subscription.currency_code,
                period_start=start,
                period_end=end,
            )
        )
        entitlements = list(
            (
                await session.scalars(
                    select(Entitlement).where(
                        Entitlement.user_id == subscription.user_id,
                        Entitlement.order_id == subscription.latest_order_id,
                    )
                )
            ).all()
        )
        for entitlement in entitlements:
            if succeeded:
                entitlement.status = EntitlementStatus.ACTIVE
                entitlement.expires_at = end
            else:
                entitlement.expires_at = _now() + timedelta(
                    days=get_settings().subscription_grace_period_days
                )
            if str(entitlement.entitlement_type) == "course_access":
                from vav.modules.courses.service import enrollment_service

                await enrollment_service.sync_entitlement(session, entitlement)

    @staticmethod
    def _event_kind(provider: str, event_type: str) -> str:
        mapping = {
            "payment.succeeded": "payment_succeeded",
            "checkout.session.completed": "payment_succeeded",
            "PAYMENT.CAPTURE.COMPLETED": "payment_succeeded",
            "payment.failed": "payment_failed",
            "payment_intent.payment_failed": "payment_failed",
            "PAYMENT.CAPTURE.DENIED": "payment_failed",
            "refund.succeeded": "refund_succeeded",
            "charge.refunded": "refund_succeeded",
            "PAYMENT.CAPTURE.REFUNDED": "refund_succeeded",
            "subscription.renewal_succeeded": "renewal_succeeded",
            "invoice.paid": "renewal_succeeded",
            "subscription.renewal_failed": "renewal_failed",
            "invoice.payment_failed": "renewal_failed",
        }
        return mapping.get(event_type, f"ignored:{provider}")

    @staticmethod
    def _mismatch(session: AsyncSession, order: Order, event_type: str) -> VavError:
        if order.status in {
            OrderStatus.PAYMENT_PROCESSING,
            OrderStatus.PAID,
            OrderStatus.FULFILLING,
            OrderStatus.FULFILLED,
        }:
            _history(
                session,
                order,
                OrderStatus.MANUAL_REVIEW,
                actor_type="system",
                reason_code=event_type,
            )
        record_security_event(
            session,
            event_type=event_type,
            severity="error",
            actor_type="provider",
            target_type="order",
            target_id=order.id,
        )
        return VavError(
            "PAYMENT_PROVIDER_MISMATCH",
            "Provider payment does not match the internal order.",
            status_code=409,
        )

    @staticmethod
    def _billing_delta(interval: str, count: int) -> timedelta:
        days = {"day": 1, "week": 7, "month": 30, "year": 365}.get(interval, 30)
        return timedelta(days=days * count)


class RefundService:
    async def request(
        self,
        session: AsyncSession,
        *,
        order: Order,
        amount_minor: int,
        reason_code: str,
        reason: str,
        actor_id: UUID,
        idempotency_key: str,
    ) -> Refund:
        await _advisory_lock(session, f"refund:{order.id}:{idempotency_key}")
        payment = await session.scalar(
            select(PaymentAttempt).where(
                PaymentAttempt.order_id == order.id,
                PaymentAttempt.status.in_(
                    (
                        PaymentStatus.SUCCEEDED,
                        PaymentStatus.PARTIALLY_REFUNDED,
                    )
                ),
            )
        )
        if payment is None:
            raise VavError("ORDER_NOT_REFUNDABLE", "Order has no paid payment.", status_code=409)
        existing = await session.scalar(
            select(Refund).where(
                Refund.provider == payment.provider,
                Refund.provider_environment == payment.provider_environment,
                Refund.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.order_id != order.id or existing.amount_minor != amount_minor:
                raise VavError(
                    "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST",
                    "The refund key was already used for another request.",
                    status_code=409,
                )
            return existing
        pending = int(
            await session.scalar(
                select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
                    Refund.order_id == order.id,
                    Refund.status.not_in((RefundStatus.FAILED, RefundStatus.CANCELLED)),
                )
            )
            or 0
        )
        if amount_minor <= 0 or pending + amount_minor > order.total_minor:
            raise VavError(
                "REFUND_AMOUNT_EXCEEDS_AVAILABLE",
                "Refund exceeds the paid and unrefunded amount.",
                status_code=409,
            )
        refund = Refund(
            refund_number=_refund_number(),
            order_id=order.id,
            payment_attempt_id=payment.id,
            provider=payment.provider,
            provider_environment=payment.provider_environment,
            status=(
                RefundStatus.APPROVAL_REQUIRED
                if get_settings().refund_approval_required
                else RefundStatus.APPROVED
            ),
            amount_minor=amount_minor,
            currency_code=order.currency_code,
            reason_code=reason_code,
            reason=reason,
            idempotency_key=idempotency_key,
            requested_by=actor_id,
        )
        session.add(refund)
        record_security_event(
            session,
            event_type="refund.requested",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="refund",
            target_id=refund.id,
            reason=reason,
        )
        await session.commit()
        return refund

    async def approve(
        self, session: AsyncSession, refund: Refund, actor_id: UUID, reason: str
    ) -> Refund:
        if refund.status != RefundStatus.APPROVAL_REQUIRED:
            raise VavError("REFUND_STATE_INVALID", "Refund cannot be approved.", status_code=409)
        if refund.requested_by == actor_id:
            raise VavError(
                "REFUND_SELF_APPROVAL_FORBIDDEN",
                "The requester cannot approve the same refund.",
                status_code=409,
            )
        refund.status = RefundStatus.APPROVED
        refund.approved_by = actor_id
        record_security_event(
            session,
            event_type="refund.approved",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="refund",
            target_id=refund.id,
            reason=reason,
        )
        await session.commit()
        return refund

    async def submit(
        self, session: AsyncSession, refund: Refund, actor_id: UUID, reason: str
    ) -> Refund:
        if refund.status != RefundStatus.APPROVED:
            raise VavError("REFUND_STATE_INVALID", "Refund is not approved.", status_code=409)
        payment = await session.get(PaymentAttempt, refund.payment_attempt_id)
        if payment is None or not payment.provider_payment_id:
            raise VavError("PAYMENT_NOT_FOUND", "Payment was not found.", status_code=404)
        provider = get_payment_provider(refund.provider)
        result = await provider.create_refund(
            ProviderRefundRequest(
                payment_id=payment.provider_payment_id,
                order_id=refund.order_id,
                amount_minor=refund.amount_minor,
                currency=refund.currency_code,
                idempotency_key=refund.idempotency_key,
            )
        )
        refund.provider_refund_id = result.provider_refund_id
        refund.status = RefundStatus.SUBMITTED
        refund.provider_submitted_at = _now()
        record_security_event(
            session,
            event_type="refund.submitted",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="refund",
            target_id=refund.id,
            reason=reason,
        )
        await session.commit()
        return refund


class ReconciliationService:
    async def scan(self, session: AsyncSession) -> int:
        created = 0
        paid_orders = list(
            (
                await session.scalars(
                    select(Order).where(
                        Order.status.in_(
                            (
                                OrderStatus.PAID,
                                OrderStatus.FULFILLING,
                                OrderStatus.FULFILLED,
                                OrderStatus.PARTIALLY_REFUNDED,
                            )
                        )
                    )
                )
            ).all()
        )
        for order in paid_orders:
            entitlement_count = int(
                await session.scalar(
                    select(func.count(Entitlement.id)).where(Entitlement.order_id == order.id)
                )
                or 0
            )
            if not entitlement_count:
                created += await self._discrepancy(
                    session,
                    kind="paid_order_without_entitlement",
                    reference_type="order",
                    reference_id=order.id,
                    expected={"entitlement_count": ">=1"},
                    actual={"entitlement_count": 0, "order_status": order.status},
                )
        unpaid_entitlements = list(
            (
                await session.execute(
                    select(Entitlement, Order)
                    .join(Order, Order.id == Entitlement.order_id)
                    .where(
                        ~Order.status.in_(
                            (
                                OrderStatus.PAID,
                                OrderStatus.FULFILLING,
                                OrderStatus.FULFILLED,
                                OrderStatus.PARTIALLY_REFUNDED,
                                OrderStatus.REFUNDED,
                            )
                        )
                    )
                )
            ).all()
        )
        for entitlement, order in unpaid_entitlements:
            created += await self._discrepancy(
                session,
                kind="entitlement_without_paid_order",
                reference_type="entitlement",
                reference_id=entitlement.id,
                expected={"paid_order": True},
                actual={"order_status": order.status},
            )
        stale_events = list(
            (
                await session.scalars(
                    select(PaymentWebhookEvent).where(
                        PaymentWebhookEvent.processing_status.in_(
                            (
                                WebhookProcessingStatus.RECEIVED,
                                WebhookProcessingStatus.RETRY_PENDING,
                                WebhookProcessingStatus.FAILED,
                            )
                        ),
                        PaymentWebhookEvent.received_at <= _now() - timedelta(minutes=30),
                    )
                )
            ).all()
        )
        for event in stale_events:
            created += await self._discrepancy(
                session,
                kind="webhook_processing_stalled",
                reference_type="payment_webhook_event",
                reference_id=event.id,
                expected={"processing_status": "processed"},
                actual={"processing_status": event.processing_status},
            )
        await session.commit()
        return created

    async def _discrepancy(
        self,
        session: AsyncSession,
        *,
        kind: str,
        reference_type: str,
        reference_id: UUID,
        expected: dict[str, object],
        actual: dict[str, object],
    ) -> int:
        exists = await session.scalar(
            select(ReconciliationDiscrepancy.id).where(
                ReconciliationDiscrepancy.discrepancy_type == kind,
                ReconciliationDiscrepancy.internal_reference_type == reference_type,
                ReconciliationDiscrepancy.internal_reference_id == reference_id,
                ReconciliationDiscrepancy.status == "open",
            )
        )
        if exists:
            return 0
        discrepancy = ReconciliationDiscrepancy(
            discrepancy_type=kind,
            severity="high",
            internal_reference_type=reference_type,
            internal_reference_id=reference_id,
            expected_snapshot=expected,
            actual_snapshot=actual,
        )
        session.add(discrepancy)
        await session.flush()
        record_security_event(
            session,
            event_type="reconciliation.discrepancy_detected",
            severity="warning",
            actor_type="system",
            target_type="reconciliation_discrepancy",
            target_id=discrepancy.id,
            metadata={"type": kind},
        )
        return 1


cart_service = CartService()
order_service = OrderService()
payment_service = PaymentService()
entitlement_service = EntitlementService()
webhook_service = WebhookService()
refund_service = RefundService()
reconciliation_service = ReconciliationService()
