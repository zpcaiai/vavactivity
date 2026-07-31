---
name: vav-payment-testing-acceptance
description: Verify VAV Commerce with order, payment, Webhook, subscription, refund, entitlement, reconciliation, concurrency, security and browser tests. Use before declaring Batch 5 complete.
---

# Acceptance

Test invalid state transitions, stale or cross-user quotes, body-hash
idempotency conflicts, duplicate payment/refund/Webhook concurrency, forged
signatures, amount/currency mismatch, return-URL tampering, cross-user reads,
secret redaction, reservation confirmation, subscription renewal, refund
limits, entitlement uniqueness and reconciliation mismatches. Run
`make commerce-verify`; retain `CONFIGURATION_REQUIRED` for remote Provider
tests that lack explicit sandbox credentials.
