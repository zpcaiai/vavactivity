---
name: vav-process-idempotency-concurrency-ordering
description: Deduplicate commands and events and preserve aggregate ordering.
---

Reject idempotency key reuse with a different request hash. Buffer future events and never silently advance across a version gap.
