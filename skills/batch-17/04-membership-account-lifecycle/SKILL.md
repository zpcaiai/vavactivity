---
name: vav-membership-account-lifecycle
description: Provision free membership and operate active, grace, cancelled and expired accounts.
---

# Rules

- Provision the free fallback idempotently on registration/verification.
- Prefer Commerce-confirmed cycle dates over local calendar calculations.
- Close paid grants/quotas on expiry while retaining history and separately purchased rights.
- Never activate two conflicting paid accounts.
