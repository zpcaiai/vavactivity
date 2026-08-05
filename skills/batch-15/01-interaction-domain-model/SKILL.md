---
name: vav-batch-15-interaction-domain-model
description: Define canonical pair identity, directional choices and explicit interaction state machines.
---

# Rules

- Normalize every two-member aggregate to `user_low_id` and `user_high_id`.
- Keep likes/skips directional; keep matches and restrictions pair scoped.
- Declare legal transitions for likes, skips, matches, invitations and contact exchange.
- Terminal outcomes cannot be silently reopened or physically deleted.
- Store version counters and append-only transition history.

# Verify

Test reversed pair inputs, self-pair rejection, transition matrices and database uniqueness.
