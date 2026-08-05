---
name: vav-batch-16-stage-registry-confirmation
description: Govern versioned stage definitions and mutual stage proposal confirmation.
---

# Rules

- Seed a versioned registry; never hard-delete an activated version.
- One participant proposes and the other accepts/declines; shared state changes only on acceptance.
- Refuse forward skips unless the active policy permits them and invalidate stale-from-stage proposals.
- `relationship_confirmed` uses the same two-person path; admin and AI confirmation routes do not exist.

# Verify

Test proposal ownership, decline/cancel/expiry, stale versions, one-pending uniqueness and a competing-accept race.
