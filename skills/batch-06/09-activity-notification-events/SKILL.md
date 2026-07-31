---
name: vav-activity-notification-events
description: Define minimal VAV activity outbox events for publication, registration, waitlists, attendance and mutual choice. Use when adding activity notifications or asynchronous consumers.
---

# Workflow

Emit stable IDs and state facts, not complete forms, profiles or secrets.
Address registration events only to their user and mutual-choice events only to
both matched users. Never emit an event to the target of a one-sided choice.
Leave delivery channels and preferences to the notification batch.
