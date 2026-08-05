---
name: vav-batch-15-matchmaking-interactions
description: Implement and verify VAV likes, skips, mutual matches, invitations, mutually confirmed contact exchange, idempotency and interaction administration.
---

# Goal

Deliver recommendation-scoped private choices, concurrency-safe mutual matching,
explicit introduction invitations, separately consented contact exchange and an
auditable operator experience without allowing administrators to manufacture a
member choice or consent.

# Prerequisites

1. Read `project-manifest.yaml` and every child skill in this directory.
2. Run `make recommendation-verify`, `make dating-profile-verify` and
   `make privacy-verify` where the environment supports browser execution.
3. Inspect the Batch 11 notification, Batch 12 privacy, Batch 13 profile,
   Batch 14 recommendation and Batch 6 activity contracts.

# Required order

Canonical pair -> likes/skips -> mutual match -> activity bridge -> invitation
-> contact consent/grants -> idempotency -> invalidation/events -> user/admin web
-> unit/integration/concurrency/security/privacy/E2E verification.

# Non-negotiable invariants

- One-sided likes, skips and reasons are private and never notify the target.
- A reciprocal race creates one pair, one match and one mutual notification.
- Invitation acceptance and contact exchange are distinct member decisions.
- One member's contact consent reveals nothing until the other consents.
- Grants bind viewer, owner, verified contact IDs and value-hash snapshots.
- Blocks, safety restrictions, erasure and stale contact values fail closed.
- Reveal tokens are short lived, viewer scoped, single use and revocable.
- No administrator endpoint may create a like, match, invitation acceptance or consent.

# Verification

Run `make interaction-verify`, then preserve honest `NOT_RUN` or
`NOT_CERTIFIED` states for browser, provider, production and external gates that
were not actually executed.
