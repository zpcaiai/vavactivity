---
name: vav-course-events-notifications
description: Define privacy-minimized VAV course outbox events for enrollment, learning, grading, completion and certificates. Use for course events, jobs or notification integration.
---

# Workflow

Publish stable identifiers and states only. Exclude learner answers, reflections,
files, answer keys, playback URLs, tokens and payment data. Consumers must be
idempotent and notification delivery remains a later-module concern.

