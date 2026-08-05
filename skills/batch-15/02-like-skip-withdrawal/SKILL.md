---
name: vav-batch-15-like-skip-withdrawal
description: Implement private recommendation-scoped likes, skips, cooldowns and withdrawal.
---

# Rules

- Recheck item ownership, freshness, profile, privacy and safety at write time.
- Do not expose incoming likes or send a single-like notification.
- Encrypt skip details; emit only approved reason codes to recommendations.
- Treat skip as a cooldown, never an automatic block or hard preference.
- Allow withdrawal only where the state machine permits it.

# Verify

Cover foreign/stale items, duplicate clicks, encrypted reasons, cooldowns and matched-like withdrawal refusal.
