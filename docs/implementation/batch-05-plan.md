# Batch 5 implementation plan

Authority: the supplied Batch 5 commerce, payments, subscriptions, refunds,
reconciliation and entitlement specification.

1. Extend the catalog reservation boundary so Commerce can reserve, confirm and
   release inventory and coupons inside one database transaction.
2. Add server-side carts, checkout previews, immutable order snapshots,
   idempotency records and explicit state histories.
3. Add provider-neutral payments with Stripe and PayPal adapters. Real adapters
   stay disabled without test/sandbox credentials; an explicit local fake is
   allowed only in development and automated tests.
4. Persist and verify raw Webhooks before applying idempotent payment,
   reservation and entitlement transitions.
5. Add subscription billing records, approval-separated refunds, deterministic
   entitlements, ledger entries and non-destructive reconciliation findings.
6. Add user checkout/account pages and permission-gated administration
   operations.
7. Verify unit, integration, Webhook, concurrency, security and browser flows,
   followed by the complete Batch 1–4 regression.

Production collection remains blocked while the payment legal entity, launch
regions, tax treatment, consumer terms and Provider credentials are undecided.
