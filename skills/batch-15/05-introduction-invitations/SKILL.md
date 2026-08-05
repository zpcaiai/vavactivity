---
name: vav-batch-15-introduction-invitations
description: Implement introduction send, accept, decline, cancel, expiry and relationship handoff.
---

# Rules

- Only a member of an active mutual match may send one pending invitation.
- Screen free text for contact details, links and payment requests before encryption.
- Only the recipient accepts/declines; only the sender cancels.
- Keep decline reasons private and return only a generic state to the sender.
- Use row locks plus invitation versions for accept/cancel/expiry races.
- Emit one relationship-handoff event on acceptance.

# Verify

Cover every transition, ownership, screening, TTL, cooldown and duplicate handoff.
