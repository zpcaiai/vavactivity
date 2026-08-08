---
name: vav-batch-11-02-event-subscription-router
description: "Implement Event subscription router for the VAV platform."
---

# Event subscription router

Consume explicit event type/version pairs through an Inbox. Resolve recipients from current
authorized domain state, create deterministic intents, ignore duplicates and dead-letter unknown
versions or unsafe recipient resolution failures without guessing Payload fields.
