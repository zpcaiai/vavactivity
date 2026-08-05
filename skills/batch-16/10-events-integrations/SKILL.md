---
name: vav-batch-16-events-integrations
description: Publish safe outbox events and integrate relationship state with interaction, recommendation and notifications.
---

# Rules

- Write state and outbox in one transaction; inbox consumers deduplicate by source event.
- Events carry IDs, statuses and recipient IDs only; no private message/reflection/reason text.
- Relationship start excludes the pair; ending revokes Batch 15 grants and applies configured cooldown.
- Notification delivery remains Batch 11-owned and must recheck current journey/safety state.

# Verify

Test duplicate delivery, outbox payload classification, downstream failure retry and pause/end invalidation.
