---
name: vav-reconciliation-and-ledger
description: Implement append-only VAV payment ledgers, Provider reconciliation, stale-flow detection and auditable discrepancy resolution. Use for financial reporting or payment repair work.
---

# Workflow

Store original, paid, settlement, fee and refund currencies separately. Detect
missing Provider payments, state/amount/currency differences, duplicate
payments or refunds, stalled Webhooks and payment-entitlement mismatches. Never
silently overwrite either source. Persist a discrepancy, require an authorized
reason to resolve it and preserve both snapshots.
