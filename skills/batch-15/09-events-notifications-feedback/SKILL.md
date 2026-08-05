---
name: vav-batch-15-events-notifications-feedback
description: Publish versioned interaction events to notification, recommendation and relationship consumers.
---

# Rules

- Use the transactional outbox and consumer inbox deduplication.
- Never publish a target recipient for a one-sided like or skip.
- Emit mutual match, invitation and contact state notifications with safe payloads.
- Send typed liked/skipped/withdrawn/matched/invitation feedback to Batch 14.
- Keep private reasons, messages and contact values out of events and logs.

# Verify

Assert topics, recipient scope, one-event semantics, deduplication and dead-letter audit.
