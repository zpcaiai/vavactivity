---
name: vav-batch-11-10-provider-webhooks-suppression
description: "Implement Provider Webhooks and suppression for the VAV platform."
---

# Provider Webhooks and suppression

Verify raw webhook bodies before persistence, deduplicate provider event IDs, map delivery states
idempotently and create hard-bounce, repeated-soft-bounce, complaint, unsubscribe or administrative
suppressions. Lifting requires permission, reason and audit.
