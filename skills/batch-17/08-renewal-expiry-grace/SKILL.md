---
name: vav-renewal-expiry-grace
description: Project renewal, payment failure, grace, expiry and free fallback.
---

# Rules

- Renewal creates one new authoritative cycle and one quota allocation.
- Payment failure enters configured limited grace without deleting data.
- Recovery is idempotent; expiry closes paid grants/quotas and restores free effectiveness.
- Scheduled cancellation keeps current access through the effective date.
