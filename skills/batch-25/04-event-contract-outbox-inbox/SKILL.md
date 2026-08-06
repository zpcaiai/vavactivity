---
name: vav-event-contract-outbox-inbox
description: Commit canonical Outbox envelopes atomically and deduplicate consumers through Inbox.
---

Producers deliver at least once; consumer effects remain at most once through event IDs, checksums and aggregate versions.
