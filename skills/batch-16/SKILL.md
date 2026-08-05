---
name: vav-batch-16-relationship-journeys
description: Implement and verify mutual relationship stages, unilateral pause/end, mutual resume, private reflection and redacted operations.
---

# Goal

Deliver the durable journey after Batch 15 handoff without allowing software, staff or one
participant to manufacture the other participant's formal relationship decision.

# Prerequisites

1. Read `project-manifest.yaml`, `docs/implementation/batch-16-plan.md`, the state-machine and
   privacy documents, and every child skill in this directory.
2. Verify Batch 12–15 gates where the environment supports them.
3. Preserve `NOT_RUN`/`NOT_CERTIFIED` for external gates not actually executed.

# Required order

Journey and participants -> idempotent handoff -> stages -> pause/resume -> ending -> milestones ->
check-ins/reflections/actions -> reminders -> safety/integrations -> member/admin web -> tests.

# Non-negotiable invariants

- Shared stage changes, including relationship confirmation, require both participants.
- Either participant may pause or end; resume requires the other participant; no auto-resume.
- An ended journey cannot be restored by a user, administrator or replay.
- Private text stays encrypted and out of history, logs and outbox.
- AI relationship context requires active Batch 12 consent; relationship health scoring is absent.
- Admins can diagnose/freeze/end for safety but cannot make member choices.

# Verification

Run `make relationship-verify`, predecessor regression gates and the repository-wide verify gate.
