---
name: vav-batch-16-relationship-testing-acceptance
description: Verify Batch 16 migrations, state, concurrency, privacy, web journeys and predecessor regression.
---

# Required suites

- Unit: transitions, stage policy, ownership and reminder language.
- Integration: handoff -> mutual stage -> pause/resume -> milestones/check-in -> end cascade.
- Concurrency: replay, duplicate proposal, competing decisions and resume/end races.
- Security/privacy: third-user denial, admin decision absence, encrypted private data, AI consent and block leakage.
- E2E: member journey and redacted administrator diagnostics.
- Regression: Batch 12–15 and repository-wide verification.

# Evidence

Record exact commands/counts/environment in `docs/acceptance/batch-16-report.md`. External production,
provider, customer and certification gates stay `NOT_RUN`/`NOT_CERTIFIED` until actually passed.
