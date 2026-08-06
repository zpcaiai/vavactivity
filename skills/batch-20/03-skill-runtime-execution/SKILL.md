---
name: vav-skill-runtime-execution
description: Implement or diagnose Skill discovery, execution planning, adapters, validation, timeout, cancellation, retry, idempotency, output validation, tracing, or runtime failure handling.
---

Resolve one concrete installed version, authorize before input validation, create an execution record, propagate deadline/cancellation, validate output, and persist only safe errors. Run untrusted Skills only in isolated runtimes. Never retry side effects without idempotency. Run `make skill-runtime-test`.
