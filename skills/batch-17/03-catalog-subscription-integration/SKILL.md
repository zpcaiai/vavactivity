---
name: vav-catalog-subscription-integration
description: Project Catalog SKU, Commerce Subscription and Entitlement events idempotently.
---

# Rules

- Verify source IDs against authoritative tables; never trust event payload status alone.
- Require active Subscription plus active MEMBERSHIP_ACCESS Entitlement.
- Keep incomplete projections pending and reconcile them asynchronously.
- Deduplicate every source event through the membership inbox.
