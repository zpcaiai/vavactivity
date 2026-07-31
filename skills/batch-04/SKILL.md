---
name: vav-batch-04-catalog-pricing-inventory-promotions
description: Implement the unified VAV product catalog, SKU model, multi-currency pricing, capacity control, inventory reservations, promotion engine and administration product center.
---

# Goal

Build the catalog, pricing, inventory and promotion foundation shared by activities,
courses, counseling, AI coaching and memberships.

# Required order

1. Read the manifest, decision register and `docs/implementation/batch-04-plan.md`.
2. Run `make cms-verify`.
3. Implement the skills in numeric order.
4. Use integer minor units and explicit CNY, USD, TWD and HKD prices.
5. Lock inventory and redemption rows for every concurrent transition.
6. Keep quotes and reservations separate from orders, payment and entitlements.
7. Finish with `make catalog-verify`.

# Invariants

- Products describe offerings; SKUs are exact purchasable units.
- Fulfillment JSON is validated by product-type schema.
- Activated price identity and amount are immutable.
- Price selection and promotion ordering are deterministic and fail closed.
- Finite inventory cannot oversell.
- Discounts cannot cross currencies or reduce totals below zero.
- Quotes explicitly state that they are not payment proof.
