---
name: vav-membership-domain-model
description: Define versioned plans, accounts, cycles and terminal membership states.
---

# Rules

- Bind every account to an immutable plan version.
- Retain one free fallback and at most one effective paid, trial or grant account.
- Enforce state, time-window and uniqueness invariants in PostgreSQL.
- Keep terminal expired, cancelled and revoked history immutable.
