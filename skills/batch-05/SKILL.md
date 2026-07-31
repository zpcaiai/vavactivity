---
name: vav-batch-05-commerce-payments-entitlements
description: Implement or review VAV carts, checkout, immutable orders, Stripe or PayPal payment adapters, signed Webhooks, subscriptions, refunds, reconciliation and entitlement activation. Use this skill whenever work touches the VAV payment or post-purchase lifecycle.
---

# Goal

Build the VAV commerce workflow without allowing browsers, return URLs or
unverified Provider data to prove payment.

## Required reading

1. Read `project-manifest.yaml` and `docs/product/decision-register.md`.
2. Read every child `SKILL.md` in this directory.
3. Inspect Catalog pricing, inventory, coupon reservations, Identity RBAC,
   append-only audit events and the outbox before changing Commerce.
4. Keep unresolved commercial and legal policy configurable and fail closed.

## Execution order

1. Cart and checkout.
2. Orders and atomic reservations.
3. Provider abstraction, Stripe and PayPal.
4. Webhook verification and payment-success processing.
5. Subscriptions, refunds, entitlements and reconciliation.
6. User and administration interfaces.
7. Unit, integration, Webhook, concurrency, security and browser acceptance.

## Invariants

- Recalculate every amount on the backend.
- Snapshot product, SKU, price, discount, fulfillment and refund policy data.
- Make order, payment, refund, reservation and entitlement operations
  idempotent.
- Confirm payment only from verified Webhooks or verified Provider
  reconciliation.
- Validate Provider order ownership, amount, currency and environment.
- Persist verified Webhook events before processing and deduplicate by Provider
  event ID.
- Keep card and wallet credentials outside VAV storage and logs.
- Never reverse a successful payment because entitlement activation is
  temporarily unavailable.
- Preserve original internal and Provider states when reconciliation differs.

## Completion gate

Run `make commerce-verify`. It must include Batch 1–4 regression. If Provider
credentials are absent, exercise only the explicit development/test fake and
report real Stripe/PayPal sandbox execution as `CONFIGURATION_REQUIRED`.
