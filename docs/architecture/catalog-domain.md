# Catalog domain

The catalog separates the business offering (`Product`) from the exact purchasable
unit (`ProductSku`). Products own public, localized presentation. SKUs own billing,
validated fulfillment, purchase limits and inventory policy.

Supported product types cover activity admission, courses and bundles, human
counseling, AI credit packages and subscriptions, memberships and extensible digital
services. `validate_fulfillment()` selects a strict schema by product type before a
SKU is persisted or activated.

Publication fails closed unless a product has a ready localization and at least one
active SKU. Paid SKUs require an active explicit price; finite and service-capacity
SKUs require an inventory item. Public DTOs omit internal names, fulfillment
configuration, audit data and stock history.

The catalog ends at quotes and reservations. Neither object proves payment or grants
an entitlement; Batch 5 owns orders, payment provider confirmation, refunds and
entitlement activation.
