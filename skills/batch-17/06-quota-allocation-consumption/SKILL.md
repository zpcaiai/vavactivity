---
name: vav-quota-allocation-consumption
description: Allocate, reserve, consume, release, expire and adjust quota atomically.
---

# Rules

- Lock the bucket and use an availability predicate for every reservation.
- Use idempotency keys for reservations, finalization and ledger entries.
- Release failed/expired work and consume only delivered value.
- Never overwrite consumed quantity; adjustments are separate and audited.
