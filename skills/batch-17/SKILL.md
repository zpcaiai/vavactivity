---
name: vav-batch-17-membership-entitlements
description: Implement and verify versioned membership plans, authoritative entitlements, atomic quotas and governed lifecycle changes.
---

# Goal

Deliver membership as a fail-closed projection of Catalog, Commerce and Entitlement authority.

# Required order

Domain and migrations -> benefit registry -> SKU projection -> accounts/cycles -> access decisions ->
quotas -> changes -> renewal/expiry -> trials/grants -> events -> web -> acceptance.

# Non-negotiable invariants

- Never duplicate product, price, order, subscription or payment truth.
- Paid access requires an active Entitlement and an active bound plan version.
- Membership never bypasses safety, privacy, blocks, hard matching criteria or module eligibility.
- Quota writes are atomic, idempotent, append a ledger row and never make history negative.
- Downgrades/cancellation preserve the already-paid period; grants use separate creator/approver.
- External runtime and production certification remain `NOT_RUN` until measured.

# Verification

Run `make membership-verify`, predecessor regressions, migration head checks and both frontend gates.
