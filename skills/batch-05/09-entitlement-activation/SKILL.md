---
name: vav-entitlement-activation
description: Map paid VAV order items into deterministic activity, course, counseling, AI or membership entitlements with retryable activation and idempotent consumption.
---

# Workflow

Use order-item ID as the idempotency boundary. Preserve the fulfillment snapshot
and create no duplicate credits or access periods during Webhook replay, worker
retry or manual retry. Validate active state, validity window, quantity and
optimistic version on consumption. Keep paid orders paid while activation
retries; escalate exhausted retries to manual review.
