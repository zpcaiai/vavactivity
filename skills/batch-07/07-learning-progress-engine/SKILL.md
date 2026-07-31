---
name: vav-learning-progress-engine
description: Implement VAV lesson, module and course progress with multi-device synchronization and idempotent learning events. Use for progress, completion state or device conflicts.
---

# Workflow

Use idempotency keys and event sequence uniqueness. Completion and maximum
trusted position never decrease through stale client updates. Derive progress
from required lessons in the enrollment's pinned version and preserve resets as
audited events.

