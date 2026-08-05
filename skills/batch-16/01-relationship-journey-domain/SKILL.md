---
name: vav-batch-16-relationship-journey-domain
description: Define canonical participant identity, journey status and append-only safe history.
---

# Rules

- Canonicalize participants as low/high IDs and reject self-pairs.
- Keep journey, stage proposal, pause and ending states separate.
- Terminal endings are immutable; history is append-only and contains controlled codes only.
- Use version fields and database checks/unique indexes as final concurrency boundaries.

# Verify

Test transition enums, canonical ownership, terminal states and migration constraints.
