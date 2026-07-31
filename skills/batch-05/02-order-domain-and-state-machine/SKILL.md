---
name: vav-order-domain-and-state-machine
description: Implement immutable VAV orders, order-item snapshots, explicit order transitions, status history and idempotent atomic creation. Use whenever order creation or order status changes.
---

# Workflow

Create the order, snapshots, inventory and coupon reservations, history,
idempotency result and outbox event in one transaction. Lock and consume fresh,
owned quotes. Permit only declared state transitions. Once payment is pending,
do not mutate user, currency, SKU, quantity, amount, discount or fulfillment
fields. Record every transition with actor, reason and metadata.
