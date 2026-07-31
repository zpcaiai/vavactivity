---
name: vav-refunds-and-cancellations
description: Implement VAV unpaid-order cancellation, approval-separated partial or full refunds, Provider confirmation and policy-driven entitlement effects. Use for refund or cancellation workflows.
---

# Workflow

Prevent refunds above the unrefunded paid amount. Separate request, approval and
Provider submission permissions and require reasons. A database-only refund is
forbidden: mark success only from verified Provider evidence. Snapshot the
refund policy and route consumed or exceptional entitlements to manual review.
