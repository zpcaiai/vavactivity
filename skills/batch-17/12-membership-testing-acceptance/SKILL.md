---
name: vav-membership-testing-acceptance
description: Verify state, authority, concurrency, security, reconciliation and web acceptance.
---

# Rules

- Test free/paid lifecycle, entitlement drift, quota races, duplicate events and plan changes.
- Run Ruff, mypy, migrations, full pytest, frontend tests/typecheck/lint and authored E2E.
- Record exact measured counts and remote CI URLs.
- Keep Docker/E2E/live-deployment gates NOT_RUN when the required runtime is unavailable.
