---
name: vav-batch-15-invalidation-safety-privacy
description: Fail closed and cascade profile, privacy, account, block, report and erasure changes.
---

# Rules

- Consume source changes through a deduplicated inbox.
- Invalidate active choices, match, invitation and contact grants in one pair transaction.
- Revoke issued reveal tokens with the grant.
- Preserve history while exposing only `no_longer_available` to members.
- Keep internal risk reasons behind sensitive RBAC and audited access.

# Verify

Cover profile pause/suspension, privacy withdrawal, block, safety restriction, erasure and display-time recheck.
