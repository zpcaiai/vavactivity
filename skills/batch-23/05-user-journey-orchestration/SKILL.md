---
name: vav-experience-user-journey-orchestration
description: Govern versioned, resumable user journey definitions, projections and next-step resolution.
---

Run `make experience-journey-check experience-test`. Require a newer authoritative state version before changing a projected step. Never use a journey projection to execute domain transitions or make user decisions.
