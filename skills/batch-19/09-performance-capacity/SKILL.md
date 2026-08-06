---
name: vav-performance-capacity
description: Measure VAV smoke, baseline, peak, stress, soak and recovery behavior against approved release and infrastructure identities.
---

Use the k6 scenarios under `tests/performance` with synthetic identities and fake providers outside production. Record release, infrastructure, load, P50/P95/P99, errors, database/lock/queue signals and cost assumptions. Gate regression in core reads, auth, commerce/webhook idempotency, recommendation exposure, interaction concurrency, quotas, async recovery and AI/RAG. Do not run destructive stress in production or remove security/privacy enforcement to improve results.
