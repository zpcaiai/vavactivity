---
name: vav-batch-16-privacy-safety-invalidation
description: Enforce relationship privacy and fail-closed block, restriction, erasure and account signals.
---

# Rules

- Recheck participant/account/safety state on writes and sensitive reads.
- A block or high-risk restriction freezes or ends the journey, cancels reminders and revokes access.
- Tell members only that the journey/action is unavailable; never reveal a reporter/block actor.
- Keep separate sensitive permissions, stated purpose and immutable audit for investigations.

# Verify

Test cross-user denial, block leakage zero, contact revocation, moderation outage and erasure/hold behavior.
