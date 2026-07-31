---
name: vav-payment-webhooks
description: Implement raw-body payment Webhook signature checks, persistence, deduplication, out-of-order handling, replay and redacted administration views. Use for Stripe or PayPal Webhook work.
---

# Workflow

Read the raw body once, verify it, hash it and persist the verified event before
business processing. Deduplicate by Provider event ID and return 2xx for exact
duplicates without repeated side effects. Lock the payment and order, then
validate ownership, amount, currency and environment. Route conflicts to manual
review. Replay the saved verified event through the same validations and audit
the operator reason.
