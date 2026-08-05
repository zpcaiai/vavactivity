---
name: vav-batch-15-user-interaction-web
description: Build member journeys for choices, matches, invitations and contact consent.
---

# Rules

- Generate an idempotency key for every write.
- Explain that likes/skips/reasons remain private until a mutual match.
- Provide outgoing choices, undo where valid, matches and invitation actions.
- Confirm destructive or consent-changing actions.
- Show verified-channel selection, platform-only, masked contacts and one-time reveal.
- Render neutral unavailable states without leaking who blocked, declined or changed settings.

# Verify

Test buttons, dialogs, routing, copy, errors, keyboard access and member E2E.
