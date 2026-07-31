from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.catalog import (
    InventoryItem,
    InventoryMovement,
    InventoryReservation,
    ProductSku,
)
from vav.modules.catalog.domain import InventoryPolicy, ReservationStatus
from vav.modules.identity.audit import record_security_event


def available_quantity(item: InventoryItem) -> int | None:
    if item.inventory_policy == InventoryPolicy.UNLIMITED:
        return None
    capacity = item.total_capacity or 0
    if item.overselling_allowed:
        capacity += item.oversell_limit
    return capacity - item.reserved_quantity - item.sold_quantity - item.safety_stock


def availability_payload(item: InventoryItem | None) -> dict[str, object]:
    if item is None or item.inventory_policy == InventoryPolicy.UNLIMITED:
        return {
            "status": "available",
            "inventory_policy": InventoryPolicy.UNLIMITED,
            "available_quantity": None,
        }
    available = max(0, available_quantity(item) or 0)
    if available == 0:
        status = "sold_out"
    elif available <= get_settings().inventory_low_stock_threshold:
        status = "low_stock"
    else:
        status = "available"
    return {
        "status": status,
        "inventory_policy": item.inventory_policy,
        "available_quantity": available,
        "inventory_version": item.version,
    }


class InventoryService:
    async def configure(
        self,
        session: AsyncSession,
        *,
        sku: ProductSku,
        total_capacity: int | None,
        safety_stock: int,
        overselling_allowed: bool,
        oversell_limit: int,
        reason: str,
        actor_id: UUID,
    ) -> InventoryItem:
        if sku.inventory_policy == InventoryPolicy.UNLIMITED:
            total_capacity = None
        elif total_capacity is None:
            raise VavError(
                "INVENTORY_CAPACITY_REQUIRED",
                "Finite and service capacity inventory require a total capacity.",
                status_code=422,
            )
        item = await session.scalar(
            select(InventoryItem).where(InventoryItem.sku_id == sku.id).with_for_update()
        )
        if item is None:
            item = InventoryItem(
                sku_id=sku.id,
                inventory_policy=sku.inventory_policy,
                total_capacity=total_capacity,
                safety_stock=safety_stock,
                overselling_allowed=overselling_allowed,
                oversell_limit=oversell_limit,
            )
            session.add(item)
            await session.flush()
            before = 0
        else:
            before = item.total_capacity or 0
            minimum = item.sold_quantity + item.reserved_quantity + safety_stock
            maximum_capacity = (total_capacity or 0) + (
                oversell_limit if overselling_allowed else 0
            )
            if sku.inventory_policy != InventoryPolicy.UNLIMITED and maximum_capacity < minimum:
                raise VavError(
                    "INVENTORY_CAPACITY_BELOW_COMMITTED",
                    "Capacity cannot be lower than sold and reserved quantity plus safety stock.",
                    status_code=409,
                )
            item.inventory_policy = sku.inventory_policy
            item.total_capacity = total_capacity
            item.safety_stock = safety_stock
            item.overselling_allowed = overselling_allowed
            item.oversell_limit = oversell_limit
            item.version += 1
        after = item.total_capacity or 0
        session.add(
            InventoryMovement(
                inventory_item_id=item.id,
                movement_type="manual_adjustment",
                quantity_delta=after - before,
                before_quantity=before,
                after_quantity=after,
                reason=reason,
                actor_user_id=actor_id,
            )
        )
        record_security_event(
            session,
            event_type="catalog.inventory.adjusted",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="inventory_item",
            target_id=item.id,
            reason=reason,
            before_state={"total_capacity": before},
            after_state={"total_capacity": after},
        )
        await session.commit()
        return item

    async def adjust(
        self,
        session: AsyncSession,
        *,
        sku_id: UUID,
        quantity_delta: int,
        reason: str,
        expected_version: int,
        actor_id: UUID,
    ) -> InventoryItem:
        item = await session.scalar(
            select(InventoryItem).where(InventoryItem.sku_id == sku_id).with_for_update()
        )
        if item is None:
            raise VavError(
                "INVENTORY_NOT_CONFIGURED", "Inventory is not configured.", status_code=404
            )
        if item.version != expected_version:
            raise VavError(
                "INVENTORY_VERSION_CONFLICT",
                "Inventory changed since it was loaded.",
                status_code=409,
            )
        if item.inventory_policy == InventoryPolicy.UNLIMITED:
            raise VavError(
                "INVENTORY_UNLIMITED",
                "Unlimited inventory does not accept capacity adjustments.",
                status_code=409,
            )
        before = item.total_capacity or 0
        after = before + quantity_delta
        maximum_capacity = after + (item.oversell_limit if item.overselling_allowed else 0)
        if after < 0 or maximum_capacity < (
            item.sold_quantity + item.reserved_quantity + item.safety_stock
        ):
            raise VavError(
                "INVENTORY_CAPACITY_BELOW_COMMITTED",
                "Capacity cannot be lower than sold and reserved quantity plus safety stock.",
                status_code=409,
            )
        item.total_capacity = after
        item.version += 1
        session.add(
            InventoryMovement(
                inventory_item_id=item.id,
                movement_type=("capacity_increase" if quantity_delta > 0 else "capacity_decrease"),
                quantity_delta=quantity_delta,
                before_quantity=before,
                after_quantity=after,
                reason=reason,
                actor_user_id=actor_id,
            )
        )
        record_security_event(
            session,
            event_type="catalog.inventory.adjusted",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="inventory_item",
            target_id=item.id,
            reason=reason,
            before_state={"total_capacity": before, "version": expected_version},
            after_state={"total_capacity": after, "version": item.version},
        )
        await session.commit()
        return item

    async def reserve(
        self,
        session: AsyncSession,
        *,
        sku_id: UUID,
        quantity: int,
        user_id: UUID | None,
        anonymous_session_id: UUID | None,
        pricing_quote_id: UUID | None,
        order_id: UUID | None = None,
        commit: bool = True,
    ) -> InventoryReservation | None:
        item = await session.scalar(
            select(InventoryItem).where(InventoryItem.sku_id == sku_id).with_for_update()
        )
        if item is None:
            sku = await session.get(ProductSku, sku_id)
            if sku is not None and sku.inventory_policy == InventoryPolicy.UNLIMITED:
                return None
            raise VavError(
                "INVENTORY_NOT_CONFIGURED", "Inventory is not configured.", status_code=409
            )
        if item.inventory_policy == InventoryPolicy.UNLIMITED:
            return None
        before = available_quantity(item) or 0
        if before < quantity:
            record_security_event(
                session,
                event_type="catalog.inventory.oversell_prevented",
                severity="warning",
                actor_type="system",
                target_type="inventory_item",
                target_id=item.id,
                metadata={"requested_quantity": quantity, "available_quantity": before},
            )
            if commit:
                await session.commit()
            raise VavError(
                "INVENTORY_NOT_AVAILABLE",
                "The requested quantity is not available.",
                status_code=409,
            )
        reservation = InventoryReservation(
            inventory_item_id=item.id,
            sku_id=sku_id,
            user_id=user_id,
            anonymous_session_id=anonymous_session_id,
            pricing_quote_id=pricing_quote_id,
            order_id=order_id,
            quantity=quantity,
            status=ReservationStatus.ACTIVE,
            expires_at=datetime.now(UTC)
            + timedelta(minutes=get_settings().inventory_reservation_ttl_minutes),
        )
        session.add(reservation)
        item.reserved_quantity += quantity
        item.version += 1
        await session.flush()
        after = available_quantity(item) or 0
        self._movement(
            session,
            item,
            reservation,
            "reservation_created",
            -quantity,
            before,
            after,
            "Inventory reserved for checkout.",
        )
        record_security_event(
            session,
            event_type="catalog.inventory.reservation.created",
            actor_type="system",
            target_type="inventory_reservation",
            target_id=reservation.id,
            metadata={"quantity": quantity, "sku_id": str(sku_id)},
        )
        if commit:
            await session.commit()
        return reservation

    async def confirm(
        self, session: AsyncSession, reservation_id: UUID, *, commit: bool = True
    ) -> InventoryReservation:
        reservation = await session.scalar(
            select(InventoryReservation)
            .where(InventoryReservation.id == reservation_id)
            .with_for_update()
        )
        if reservation is None:
            raise VavError(
                "INVENTORY_RESERVATION_NOT_FOUND",
                "Inventory reservation was not found.",
                status_code=404,
            )
        if reservation.status == ReservationStatus.CONFIRMED:
            return reservation
        if reservation.status != ReservationStatus.ACTIVE or reservation.expires_at <= datetime.now(
            UTC
        ):
            raise VavError(
                "INVENTORY_RESERVATION_NOT_CONFIRMABLE",
                "Only active, unexpired reservations can be confirmed.",
                status_code=409,
            )
        item = await session.scalar(
            select(InventoryItem)
            .where(InventoryItem.id == reservation.inventory_item_id)
            .with_for_update()
        )
        if item is None:
            raise VavError(
                "INVENTORY_NOT_CONFIGURED", "Inventory is not configured.", status_code=409
            )
        before = available_quantity(item) or 0
        item.reserved_quantity -= reservation.quantity
        item.sold_quantity += reservation.quantity
        item.version += 1
        reservation.status = ReservationStatus.CONFIRMED
        reservation.confirmed_at = datetime.now(UTC)
        self._movement(
            session,
            item,
            reservation,
            "reservation_confirmed",
            0,
            before,
            available_quantity(item) or 0,
            "Reservation confirmed after authoritative payment workflow.",
        )
        record_security_event(
            session,
            event_type="catalog.inventory.reservation.confirmed",
            actor_type="system",
            target_type="inventory_reservation",
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
        reason: str,
        expired: bool = False,
        commit: bool = True,
    ) -> InventoryReservation:
        reservation = await session.scalar(
            select(InventoryReservation)
            .where(InventoryReservation.id == reservation_id)
            .with_for_update()
        )
        if reservation is None:
            raise VavError(
                "INVENTORY_RESERVATION_NOT_FOUND",
                "Inventory reservation was not found.",
                status_code=404,
            )
        if reservation.status in {ReservationStatus.RELEASED, ReservationStatus.EXPIRED}:
            return reservation
        if reservation.status == ReservationStatus.CONFIRMED:
            raise VavError(
                "INVENTORY_RESERVATION_CONFIRMED",
                "Confirmed reservations require the cancellation-return workflow.",
                status_code=409,
            )
        item = await session.scalar(
            select(InventoryItem)
            .where(InventoryItem.id == reservation.inventory_item_id)
            .with_for_update()
        )
        if item is None:
            raise VavError(
                "INVENTORY_NOT_CONFIGURED", "Inventory is not configured.", status_code=409
            )
        before = available_quantity(item) or 0
        item.reserved_quantity -= reservation.quantity
        item.version += 1
        reservation.status = ReservationStatus.EXPIRED if expired else ReservationStatus.RELEASED
        reservation.released_at = datetime.now(UTC)
        reservation.release_reason = reason
        self._movement(
            session,
            item,
            reservation,
            "reservation_released",
            reservation.quantity,
            before,
            available_quantity(item) or 0,
            reason,
        )
        record_security_event(
            session,
            event_type=(
                "catalog.inventory.reservation.expired"
                if expired
                else "catalog.inventory.reservation.released"
            ),
            actor_type="system",
            target_type="inventory_reservation",
            target_id=reservation.id,
            reason=reason,
        )
        if commit:
            await session.commit()
        return reservation

    async def expire_due(self, session: AsyncSession, limit: int = 500) -> int:
        reservation_ids = list(
            (
                await session.scalars(
                    select(InventoryReservation.id)
                    .where(
                        InventoryReservation.status == ReservationStatus.ACTIVE,
                        InventoryReservation.expires_at <= datetime.now(UTC),
                    )
                    .order_by(InventoryReservation.expires_at)
                    .limit(limit)
                )
            ).all()
        )
        expired = 0
        for reservation_id in reservation_ids:
            await self.release(
                session,
                reservation_id,
                reason="Reservation TTL elapsed.",
                expired=True,
            )
            expired += 1
        return expired

    @staticmethod
    def _movement(
        session: AsyncSession,
        item: InventoryItem,
        reservation: InventoryReservation,
        movement_type: str,
        quantity_delta: int,
        before: int,
        after: int,
        reason: str,
    ) -> None:
        session.add(
            InventoryMovement(
                inventory_item_id=item.id,
                movement_type=movement_type,
                quantity_delta=quantity_delta,
                before_quantity=before,
                after_quantity=after,
                reference_type="inventory_reservation",
                reference_id=reservation.id,
                reason=reason,
            )
        )


inventory_service = InventoryService()
