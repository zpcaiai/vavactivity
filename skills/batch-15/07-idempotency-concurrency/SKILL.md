---
name: vav-batch-15-idempotency-concurrency
description: Enforce request idempotency, uniqueness and race-safe interaction outcomes.
---

# Rules

- Require an idempotency key for every member write.
- Bind each key to actor, operation and canonical request hash.
- Replay the stored response for the same request; reject key reuse with different input.
- Combine application row locks with database partial unique indexes.
- Use optimistic versions for invitation and consent state changes.

# Verify

Cover double click, reciprocal likes, accept/cancel, accept/expire and reveal/revoke races.
