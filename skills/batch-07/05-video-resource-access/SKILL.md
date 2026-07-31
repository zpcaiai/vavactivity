---
name: vav-video-resource-access
description: Implement secure VAV course video providers, processing state, short-lived playback sessions and heartbeat evidence. Use for course video, HLS, playback or watch progress.
---

# Workflow

Keep providers replaceable. Authorize only eligible users and unlocked lessons,
scope sessions to user/enrollment/lesson/video, hash tokens, limit concurrency
and return short-lived URLs without original object keys. Heartbeats are
monotonic evidence, not proof of attention.

