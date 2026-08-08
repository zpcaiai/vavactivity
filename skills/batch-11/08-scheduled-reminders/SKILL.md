---
name: vav-batch-11-08-scheduled-reminders
description: "Implement Scheduled reminders for the VAV platform."
---

# Scheduled reminders

Bind reminder deduplication to subject version and offset. Reschedule by cancelling obsolete plans,
recheck current source state at dispatch, stop stale or expired actions, and allow digesting only for
ordinary categories that explicitly support it.
