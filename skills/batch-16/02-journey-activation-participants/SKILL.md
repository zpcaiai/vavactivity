---
name: vav-batch-16-journey-activation-participants
description: Consume accepted-introduction handoffs idempotently and create exactly two participants.
---

# Rules

- Accept only the Batch 15 handoff event and preserve its pair, match and invitation references.
- Unique source-event and handoff keys make direct materialisation plus replay safe.
- Create two and only two participant rows; no admin/manual journey creation route.
- Exclude an active journey from new recommendation/interaction creation.

# Verify

Replay a handoff and assert one journey, two participants, one initial history event and no duplicate notification.
