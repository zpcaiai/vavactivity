---
name: vav-batch-15-interaction-testing-acceptance
description: Verify Batch 15 state, concurrency, security, privacy, web journeys and regression gates.
---

# Required suites

- Unit: pair normalization, transition tables, screening and cooldown policy.
- Integration: like -> match -> invitation -> acceptance -> contact grant -> reveal -> revoke.
- Concurrency: reciprocal likes, duplicate operations and competing invitation/token outcomes.
- Security/privacy: cross-user access, no incoming-like API, encrypted reasons, no one-side disclosure, value-hash staleness and block revocation.
- E2E: member journey and redacted administrator diagnostics.
- Regression: Batch 12 privacy, Batch 13 profile and Batch 14 recommendation suites.

# Evidence

Record exact commands, counts, environment and failures in
`docs/acceptance/batch-15-report.md`. Never label external delivery or production certification as passed from local evidence.
