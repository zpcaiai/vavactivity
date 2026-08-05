---
name: vav-batch-15-activity-mutual-choice-bridge
description: Merge approved Batch 6 post-event mutual choices into the interaction pair safely.
---

# Rules

- Consume versioned inbox events idempotently.
- Recheck profile, privacy, account and moderation eligibility.
- Merge with an existing match instead of creating a second pair or match.
- Record activity as a source only; never auto-share contact details.
- Dead-letter malformed or unavailable dependencies with safe metadata.

# Verify

Cover duplicate events, existing-match merge, invalid profiles and no-contact leakage.
