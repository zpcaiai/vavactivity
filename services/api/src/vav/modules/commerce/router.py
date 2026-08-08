# ruff: noqa: B008

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.models.catalog import CouponRedemptionReservation, InventoryReservation, ProductSku
from vav.models.commerce import (
    Cart,
    CartItem,
    Entitlement,
    Order,
    OrderItem,
    PaymentAttempt,
    PaymentWebhookEvent,
    ReconciliationDiscrepancy,
    Refund,
    Subscription,
)
from vav.modules.catalog.inventory import inventory_service
from vav.modules.catalog.promotions import coupon_redemption_service
from vav.modules.commerce.domain import (
    CartStatus,
    EntitlementStatus,
    OrderStatus,
)
from vav.modules.commerce.schemas import (
    CartItemCreateRequest,
    CartItemUpdateRequest,
    CartOwnerRequest,
    CheckoutOrderRequest,
    CheckoutPreviewRequest,
    EntitlementActionRequest,
    EntitlementConsumeRequest,
    OrderCancelRequest,
    PaymentCreateRequest,
    ReconciliationResolveRequest,
    RefundActionRequest,
    RefundRequestCreate,
    SubscriptionCancelRequest,
)
from vav.modules.commerce.service import (
    cart_service,
    entitlement_service,
    order_payload,
    order_service,
    payment_service,
    reconciliation_service,
    refund_service,
    webhook_service,
)
from vav.modules.identity.audit import record_security_event
from vav.modules.identity.dependencies import (
    AuthenticatedPrincipal,
    bearer,
    require_authenticated_user,
)
from vav.modules.identity.permissions import require_permission

router = APIRouter()


def _page_payload(
    items: list[dict[str, object]], *, page: int, page_size: int, total: int
) -> dict[str, object]:
    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        },
    }


async def optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_database_session),
) -> AuthenticatedPrincipal | None:
    if credentials is None:
        return None
    return await require_authenticated_user(credentials=credentials, session=session)


async def _cart(
    session: AsyncSession,
    cart_id: UUID,
    principal: AuthenticatedPrincipal | None,
    anonymous_session_id: UUID | None,
    *,
    lock: bool = False,
) -> Cart:
    query = select(Cart).where(Cart.id == cart_id)
    if lock:
        query = query.with_for_update()
    cart = await session.scalar(query)
    if cart is None:
        raise VavError("CART_NOT_FOUND", "Cart was not found.", status_code=404)
    cart_service.ensure_owner(
        cart,
        principal.user.id if principal else None,
        anonymous_session_id,
    )
    return cart


@router.get("/cart")
async def get_cart(
    request: Request,
    anonymous_session_id: UUID | None = None,
    currency_code: str = "USD",
    principal: AuthenticatedPrincipal | None = Depends(optional_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    cart = await cart_service.get_or_create(
        session,
        user_id=principal.user.id if principal else None,
        anonymous_session_id=anonymous_session_id,
        currency=currency_code,
    )
    return success(await cart_service.payload(session, cart), request_id_from_request(request))


@router.post("/cart/items", status_code=201)
async def add_cart_item(
    payload: CartItemCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal | None = Depends(optional_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if await session.get(ProductSku, payload.sku_id) is None:
        raise VavError("CATALOG_SKU_NOT_FOUND", "SKU was not found.", status_code=404)
    cart = await cart_service.get_or_create(
        session,
        user_id=principal.user.id if principal else None,
        anonymous_session_id=payload.anonymous_session_id,
        currency=payload.currency_code,
    )
    item = await session.scalar(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.sku_id == payload.sku_id)
    )
    if item is None:
        item = CartItem(
            cart_id=cart.id,
            sku_id=payload.sku_id,
            quantity=payload.quantity,
            coupon_code=payload.coupon_code,
        )
        session.add(item)
    else:
        item.quantity += payload.quantity
        item.coupon_code = payload.coupon_code
        item.last_quote_id = None
    cart.status = CartStatus.ACTIVE
    cart.version += 1
    record_security_event(
        session,
        event_type="cart.item.added",
        actor_type="user" if principal else "anonymous",
        actor_user_id=principal.user.id if principal else None,
        target_type="cart",
        target_id=cart.id,
        metadata={"sku_id": str(payload.sku_id), "quantity": payload.quantity},
    )
    await session.commit()
    return success(await cart_service.payload(session, cart), request_id_from_request(request))


@router.patch("/cart/items/{item_id}")
async def update_cart_item(
    item_id: UUID,
    payload: CartItemUpdateRequest,
    request: Request,
    anonymous_session_id: UUID | None = None,
    principal: AuthenticatedPrincipal | None = Depends(optional_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await session.scalar(select(CartItem).where(CartItem.id == item_id).with_for_update())
    if item is None:
        raise VavError("CART_ITEM_NOT_FOUND", "Cart item was not found.", status_code=404)
    cart = await _cart(session, item.cart_id, principal, anonymous_session_id, lock=True)
    if cart.version != payload.expected_version:
        raise VavError(
            "CART_VERSION_CONFLICT", "Cart changed since it was loaded.", status_code=409
        )
    item.quantity = payload.quantity
    item.coupon_code = payload.coupon_code
    item.last_quote_id = None
    cart.status = CartStatus.ACTIVE
    cart.version += 1
    await session.commit()
    return success(await cart_service.payload(session, cart), request_id_from_request(request))


@router.delete("/cart/items/{item_id}")
async def delete_cart_item(
    item_id: UUID,
    request: Request,
    anonymous_session_id: UUID | None = None,
    principal: AuthenticatedPrincipal | None = Depends(optional_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await session.get(CartItem, item_id)
    if item is None:
        raise VavError("CART_ITEM_NOT_FOUND", "Cart item was not found.", status_code=404)
    cart = await _cart(session, item.cart_id, principal, anonymous_session_id, lock=True)
    await session.delete(item)
    cart.version += 1
    await session.commit()
    return success(await cart_service.payload(session, cart), request_id_from_request(request))


@router.delete("/cart")
async def clear_cart(
    payload: CartOwnerRequest,
    request: Request,
    principal: AuthenticatedPrincipal | None = Depends(optional_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    cart = await cart_service.get_or_create(
        session,
        user_id=principal.user.id if principal else None,
        anonymous_session_id=payload.anonymous_session_id,
        currency=payload.currency_code,
    )
    await session.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
    cart.status = CartStatus.ABANDONED
    cart.version += 1
    await session.commit()
    return success({"status": cart.status}, request_id_from_request(request))


@router.post("/checkout/preview")
async def checkout_preview(
    payload: CheckoutPreviewRequest,
    request: Request,
    principal: AuthenticatedPrincipal | None = Depends(optional_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    cart = await _cart(session, payload.cart_id, principal, payload.anonymous_session_id)
    result = await cart_service.preview(
        session,
        cart=cart,
        request=payload,
        user_id=principal.user.id if principal else None,
    )
    return success(result, request_id_from_request(request))


@router.post("/checkout/orders", status_code=201)
async def create_order(
    payload: CheckoutOrderRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=255),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    order = await order_service.create(
        session,
        user=principal.user,
        request=payload,
        idempotency_key=idempotency_key,
    )
    items = list(
        (
            await session.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
            )
        ).all()
    )
    return success(order_payload(order, items=items), request_id_from_request(request))


@router.get("/orders")
async def user_orders(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    criteria = Order.user_id == principal.user.id
    total = int(await session.scalar(select(func.count(Order.id)).where(criteria)) or 0)
    orders = list(
        (
            await session.scalars(
                select(Order)
                .where(criteria)
                .order_by(Order.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        _page_payload(
            [order_payload(order) for order in orders],
            page=page,
            page_size=page_size,
            total=total,
        ),
        request_id_from_request(request),
    )


@router.get("/orders/{order_number}")
async def user_order(
    order_number: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    order = await session.scalar(
        select(Order).where(Order.order_number == order_number, Order.user_id == principal.user.id)
    )
    if order is None:
        raise VavError("ORDER_NOT_FOUND", "Order was not found.", status_code=404)
    items = list(
        (
            await session.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
            )
        ).all()
    )
    attempts = list(
        (
            await session.scalars(
                select(PaymentAttempt)
                .where(PaymentAttempt.order_id == order.id)
                .order_by(PaymentAttempt.created_at)
            )
        ).all()
    )
    entitlements = list(
        (await session.scalars(select(Entitlement).where(Entitlement.order_id == order.id))).all()
    )
    data = order_payload(order, items=items)
    data["payments"] = [payment_service.payload(item) for item in attempts]
    data["entitlements"] = [_entitlement_payload(item) for item in entitlements]
    return success(data, request_id_from_request(request))


@router.post("/orders/{order_number}/payments", status_code=201)
async def create_payment(
    order_number: str,
    payload: PaymentCreateRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=255),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    order = await session.scalar(select(Order).where(Order.order_number == order_number))
    if order is None:
        raise VavError("ORDER_NOT_FOUND", "Order was not found.", status_code=404)
    attempt = await payment_service.create(
        session,
        order=order,
        provider_name=payload.provider,
        user_id=principal.user.id,
        idempotency_key=idempotency_key,
    )
    return success(payment_service.payload(attempt), request_id_from_request(request))


@router.post("/orders/{order_number}/cancel")
async def cancel_order(
    order_number: str,
    payload: OrderCancelRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    order = await session.scalar(
        select(Order)
        .where(Order.order_number == order_number, Order.user_id == principal.user.id)
        .with_for_update()
    )
    if order is None:
        raise VavError("ORDER_NOT_FOUND", "Order was not found.", status_code=404)
    if order.status not in {
        OrderStatus.DRAFT,
        OrderStatus.PENDING_PAYMENT,
        OrderStatus.PAYMENT_FAILED,
    }:
        raise VavError("ORDER_NOT_CANCELLABLE", "Paid orders cannot be cancelled.", status_code=409)
    inventory_ids = list(
        (
            await session.scalars(
                select(InventoryReservation.id).where(InventoryReservation.order_id == order.id)
            )
        ).all()
    )
    for reservation_id in inventory_ids:
        await inventory_service.release(
            session, reservation_id, reason=payload.reason, commit=False
        )
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
        await coupon_redemption_service.release(session, reservation_id, commit=False)
    from vav.modules.commerce.service import _history

    _history(
        session,
        order,
        OrderStatus.CANCELLED,
        actor_type="user",
        actor_id=principal.user.id,
        reason=payload.reason,
    )
    order.cancelled_at = datetime.now(UTC)
    await session.commit()
    return success(order_payload(order), request_id_from_request(request))


@router.post("/webhooks/{provider_name}")
async def payment_webhook(
    provider_name: str,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    raw_body = await request.body()
    event = await webhook_service.ingest(
        session,
        provider_name=provider_name,
        headers={key.casefold(): value for key, value in request.headers.items()},
        raw_body=raw_body,
    )
    return success(
        {"accepted": True, "event_id": str(event.id), "status": event.processing_status},
        request_id_from_request(request),
    )


def _entitlement_payload(item: Entitlement) -> dict[str, object]:
    return {
        "id": str(item.id),
        "order_id": str(item.order_id),
        "type": item.entitlement_type,
        "status": item.status,
        "quantity_granted": item.quantity_granted,
        "quantity_consumed": item.quantity_consumed,
        "starts_at": item.starts_at.isoformat() if item.starts_at else None,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "version": item.version,
    }


@router.get("/entitlements")
async def user_entitlements(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    criteria = Entitlement.user_id == principal.user.id
    total = int(await session.scalar(select(func.count(Entitlement.id)).where(criteria)) or 0)
    items = list(
        (
            await session.scalars(
                select(Entitlement)
                .where(criteria)
                .order_by(Entitlement.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        _page_payload(
            [_entitlement_payload(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        ),
        request_id_from_request(request),
    )


@router.post("/internal/entitlements/{entitlement_id}/consume")
async def consume_entitlement(
    entitlement_id: UUID,
    payload: EntitlementConsumeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await entitlement_service.consume(
        session,
        entitlement_id=entitlement_id,
        user_id=principal.user.id,
        quantity=payload.quantity,
        expected_version=payload.expected_version,
        idempotency_key=payload.idempotency_key,
    )
    return success(_entitlement_payload(item), request_id_from_request(request))


@router.get("/subscriptions")
async def user_subscriptions(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    criteria = Subscription.user_id == principal.user.id
    total = int(await session.scalar(select(func.count(Subscription.id)).where(criteria)) or 0)
    items = list(
        (
            await session.scalars(
                select(Subscription)
                .where(criteria)
                .order_by(Subscription.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        _page_payload(
            [_subscription_payload(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        ),
        request_id_from_request(request),
    )


def _subscription_payload(item: Subscription) -> dict[str, object]:
    return {
        "id": str(item.id),
        "status": item.status,
        "provider": item.provider,
        "currency": item.currency_code,
        "amount_minor": item.recurring_amount_minor,
        "billing_interval": item.billing_interval,
        "billing_interval_count": item.billing_interval_count,
        "current_period_end": (
            item.current_period_end.isoformat() if item.current_period_end else None
        ),
        "cancel_at_period_end": item.cancel_at_period_end,
    }


@router.post("/subscriptions/{subscription_id}/cancel")
async def cancel_subscription(
    subscription_id: UUID,
    payload: SubscriptionCancelRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    from vav.core.config import get_settings

    item = await session.scalar(
        select(Subscription)
        .where(
            Subscription.id == subscription_id,
            Subscription.user_id == principal.user.id,
        )
        .with_for_update()
    )
    if item is None:
        raise VavError("SUBSCRIPTION_NOT_FOUND", "Subscription was not found.", status_code=404)
    if payload.immediate and not get_settings().subscription_immediate_cancellation_enabled:
        raise VavError(
            "SUBSCRIPTION_IMMEDIATE_CANCELLATION_DISABLED",
            "Immediate cancellation is disabled by policy.",
            status_code=409,
        )
    if payload.immediate:
        item.status = "cancelled"
        item.cancelled_at = datetime.now(UTC)
    else:
        item.status = "cancel_at_period_end"
        item.cancel_at_period_end = True
    record_security_event(
        session,
        event_type="subscription.cancel_scheduled"
        if not payload.immediate
        else "subscription.cancelled",
        actor_type="user",
        actor_user_id=principal.user.id,
        target_type="subscription",
        target_id=item.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(_subscription_payload(item), request_id_from_request(request))


@router.get("/admin/commerce/orders")
async def admin_orders(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedPrincipal = Depends(require_permission("commerce.orders.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    total = int(await session.scalar(select(func.count(Order.id))) or 0)
    items = list(
        (
            await session.scalars(
                select(Order)
                .order_by(Order.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        _page_payload(
            [order_payload(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        ),
        request_id_from_request(request),
    )


@router.get("/admin/commerce/payments")
async def admin_payments(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedPrincipal = Depends(require_permission("commerce.payments.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    total = int(await session.scalar(select(func.count(PaymentAttempt.id))) or 0)
    items = list(
        (
            await session.scalars(
                select(PaymentAttempt)
                .order_by(PaymentAttempt.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        _page_payload(
            [payment_service.payload(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        ),
        request_id_from_request(request),
    )


@router.get("/admin/commerce/subscriptions")
async def admin_subscriptions(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedPrincipal = Depends(require_permission("commerce.subscriptions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    total = int(await session.scalar(select(func.count(Subscription.id))) or 0)
    items = list(
        (
            await session.scalars(
                select(Subscription)
                .order_by(Subscription.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        _page_payload(
            [_subscription_payload(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        ),
        request_id_from_request(request),
    )


@router.get("/admin/commerce/refunds")
async def admin_refunds(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedPrincipal = Depends(require_permission("commerce.refunds.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    total = int(await session.scalar(select(func.count(Refund.id))) or 0)
    items = list(
        (
            await session.scalars(
                select(Refund)
                .order_by(Refund.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        _page_payload(
            [_refund_payload(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        ),
        request_id_from_request(request),
    )


def _refund_payload(item: Refund) -> dict[str, object]:
    return {
        "id": str(item.id),
        "refund_number": item.refund_number,
        "order_id": str(item.order_id),
        "status": item.status,
        "provider": item.provider,
        "provider_refund_id": item.provider_refund_id,
        "amount_minor": item.amount_minor,
        "currency": item.currency_code,
        "reason_code": item.reason_code,
    }


@router.post("/admin/commerce/refunds", status_code=201)
async def request_refund(
    payload: RefundRequestCreate,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=255),
    principal: AuthenticatedPrincipal = Depends(require_permission("commerce.refunds.request")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    order = await session.get(Order, payload.order_id)
    if order is None:
        raise VavError("ORDER_NOT_FOUND", "Order was not found.", status_code=404)
    item = await refund_service.request(
        session,
        order=order,
        amount_minor=payload.amount_minor,
        reason_code=payload.reason_code,
        reason=payload.reason,
        actor_id=principal.user.id,
        idempotency_key=idempotency_key,
    )
    return success(_refund_payload(item), request_id_from_request(request))


@router.post("/admin/commerce/refunds/{refund_id}/approve")
async def approve_refund(
    refund_id: UUID,
    payload: RefundActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("commerce.refunds.approve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await session.scalar(select(Refund).where(Refund.id == refund_id).with_for_update())
    if item is None:
        raise VavError("REFUND_NOT_FOUND", "Refund was not found.", status_code=404)
    item = await refund_service.approve(session, item, principal.user.id, payload.reason)
    return success(_refund_payload(item), request_id_from_request(request))


@router.post("/admin/commerce/refunds/{refund_id}/submit")
async def submit_refund(
    refund_id: UUID,
    payload: RefundActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("commerce.refunds.submit")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await session.scalar(select(Refund).where(Refund.id == refund_id).with_for_update())
    if item is None:
        raise VavError("REFUND_NOT_FOUND", "Refund was not found.", status_code=404)
    item = await refund_service.submit(session, item, principal.user.id, payload.reason)
    return success(_refund_payload(item), request_id_from_request(request))


@router.get("/admin/commerce/webhooks")
async def admin_webhooks(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedPrincipal = Depends(require_permission("commerce.webhooks.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    total = int(await session.scalar(select(func.count(PaymentWebhookEvent.id))) or 0)
    items = list(
        (
            await session.scalars(
                select(PaymentWebhookEvent)
                .order_by(PaymentWebhookEvent.received_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        _page_payload(
            [
                {
                    "id": str(item.id),
                    "provider": item.provider,
                    "provider_event_id": item.provider_event_id,
                    "event_type": item.event_type,
                    "signature_verified": item.signature_verified,
                    "processing_status": item.processing_status,
                    "processing_attempts": item.processing_attempts,
                    "last_error_code": item.last_error_code,
                    "payload": {"redacted": True},
                }
                for item in items
            ],
            page=page,
            page_size=page_size,
            total=total,
        ),
        request_id_from_request(request),
    )


@router.post("/admin/commerce/webhooks/{event_id}/replay")
async def replay_webhook(
    event_id: UUID,
    payload: RefundActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("commerce.webhooks.replay")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await session.scalar(
        select(PaymentWebhookEvent).where(PaymentWebhookEvent.id == event_id).with_for_update()
    )
    if item is None or not item.signature_verified:
        raise VavError("WEBHOOK_EVENT_NOT_FOUND", "Verified event was not found.", status_code=404)
    record_security_event(
        session,
        event_type="webhook.replayed",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="payment_webhook_event",
        target_id=item.id,
        reason=payload.reason,
    )
    item = await webhook_service.ingest(
        session,
        provider_name=item.provider,
        headers={},
        raw_body=b"",
        replay_event=item,
    )
    return success(
        {"id": str(item.id), "status": item.processing_status},
        request_id_from_request(request),
    )


@router.get("/admin/commerce/reconciliation")
async def admin_reconciliation(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedPrincipal = Depends(require_permission("commerce.reconciliation.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    total = int(await session.scalar(select(func.count(ReconciliationDiscrepancy.id))) or 0)
    items = list(
        (
            await session.scalars(
                select(ReconciliationDiscrepancy)
                .order_by(ReconciliationDiscrepancy.detected_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        _page_payload(
            [
                {
                    "id": str(item.id),
                    "type": item.discrepancy_type,
                    "severity": item.severity,
                    "status": item.status,
                    "expected": item.expected_snapshot,
                    "actual": item.actual_snapshot,
                }
                for item in items
            ],
            page=page,
            page_size=page_size,
            total=total,
        ),
        request_id_from_request(request),
    )


@router.post("/admin/commerce/reconciliation/scan")
async def scan_reconciliation(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("commerce.payments.reconcile")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    count = await reconciliation_service.scan(session)
    return success({"discrepancies_created": count}, request_id_from_request(request))


@router.post("/admin/commerce/reconciliation/{discrepancy_id}/resolve")
async def resolve_reconciliation(
    discrepancy_id: UUID,
    payload: ReconciliationResolveRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("commerce.reconciliation.resolve")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await session.scalar(
        select(ReconciliationDiscrepancy)
        .where(ReconciliationDiscrepancy.id == discrepancy_id)
        .with_for_update()
    )
    if item is None:
        raise VavError(
            "RECONCILIATION_DISCREPANCY_NOT_FOUND",
            "Reconciliation discrepancy was not found.",
            status_code=404,
        )
    item.status = "resolved"
    item.resolved_at = datetime.now(UTC)
    item.resolution_reason = payload.reason
    record_security_event(
        session,
        event_type="reconciliation.discrepancy_resolved",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="reconciliation_discrepancy",
        target_id=item.id,
        reason=payload.reason,
    )
    await session.commit()
    return success({"status": item.status}, request_id_from_request(request))


@router.get("/admin/commerce/entitlements")
async def admin_entitlements(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedPrincipal = Depends(require_permission("commerce.entitlements.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    total = int(await session.scalar(select(func.count(Entitlement.id))) or 0)
    items = list(
        (
            await session.scalars(
                select(Entitlement)
                .order_by(Entitlement.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        _page_payload(
            [_entitlement_payload(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        ),
        request_id_from_request(request),
    )


@router.post("/admin/commerce/entitlements/{entitlement_id}/revoke")
async def revoke_entitlement(
    entitlement_id: UUID,
    payload: EntitlementActionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("commerce.entitlements.revoke")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await session.scalar(
        select(Entitlement).where(Entitlement.id == entitlement_id).with_for_update()
    )
    if item is None:
        raise VavError("ENTITLEMENT_NOT_FOUND", "Entitlement was not found.", status_code=404)
    item.status = EntitlementStatus.REVOKED
    item.revoked_at = datetime.now(UTC)
    item.revoke_reason = payload.reason[:128]
    item.version += 1
    if str(item.entitlement_type) == "course_access":
        from vav.modules.courses.service import enrollment_service

        await enrollment_service.sync_entitlement(session, item)
    record_security_event(
        session,
        event_type="entitlement.revoked",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="entitlement",
        target_id=item.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(_entitlement_payload(item), request_id_from_request(request))
