# Remaining Batches — 15 to 32

This file fixes the order, scope and boundary of every batch still to be built, so that any
future session can resume without guessing. It is derived from `ChatGPT-Codex 实现项目方案.md`
in the repository root; the line numbers below point at the full specification for each batch
in that document.

## Verified status

Batch 14 was committed as `feat(recommendations): complete Batch 14 bidirectional
recommendation engine` after a clean-environment reproduction of the backend CI job
(PostgreSQL 16 + pgvector + Redis, migrate to `20260804_0059`, then the eleven CI seed
commands):

| Gate | Result |
| --- | --- |
| Backend pytest | 543 passed, 0 failed (195 in `recommendations`) |
| Ruff check + format | clean over `services` |
| mypy strict | clean, 190 source files |
| Frontend vitest | user-web 17, admin-web 9 |
| ESLint + vue-tsc | clean for both apps |
| Manifest | 21 modules, 2 phases, 56 fail-closed decisions |
| Migration heads | single head `20260804_0059` |
| E2E | 17 recommendation specs authored, not executed (needs the Docker stack) |

**543 is the real backend baseline.** Any future report that claims a larger number without a
matching test count is wrong.

Batches 1–13 are committed. Batches 15–32 are not started — no code, no migrations, no plans.

## The roadmap is 32 batches, not 33

Batches 1–20 are the product plan. Batches 21–32 are the appended quality-assurance and
certification programme (`ChatGPT-Codex 实现项目方案.md:62275`). There is no Batch 33.

Batch 20 is **Skill SDK / Skill Runtime / Marketplace and final release**, not in-app
messaging. There is no 站内沟通 batch and no 红娘工作台 batch anywhere in the plan.

## Order and scope

### Product batches

| Batch | Scope | Spec |
| --- | --- | --- |
| 15 | Like, skip, withdraw, mutual match, introduction invitation, accept / decline, contact-exchange confirmation, duplicate-action protection, admin interaction centre | `:41295` |
| 16 | Getting-to-know relationship state machine, stage confirmation, pause, end, milestones, two-sided state sync, reminders, private review, relationship archive, admin relationship centre | `:44138` |
| 17 | Membership tiers, entitlement packages, access control, subscriptions, quotas, entitlement consumption, upgrade / downgrade, expiry, renewal, admin membership centre | `:47330` |
| 18 | Reporting, blocking, content moderation, account restriction, anti-harassment, anti-fraud, safety incidents, risk rules, manual disposition, appeals, Trust & Safety centre, red-team acceptance | `:50807` |
| 19 | Full project assembly, environment config, Docker Compose, production deploy, CI/CD, observability, backup and restore, load testing, disaster recovery, full E2E, one-command startup acceptance | `:54458` |
| 20 | Skill SDK, Skill Runtime, Skill Registry, I/O schemas, dependency graph, permissions, signing, version compatibility, plugin mechanism, install / upgrade, CLI, API, IDE, web console, marketplace governance, final release | `:58090` |

### Quality-assurance batches

| Batch | Scope | Spec |
| --- | --- | --- |
| 21 | Quality charter, requirement traceability, feature-completeness matrix, release gates | `:63213` |
| 22 | Unified design system, layout, responsiveness, accessibility, Storybook, interaction states, visual regression | `:66209` |
| 23 | Information architecture, site navigation, user journeys, task centre, cross-module handoff, global search, help system, dead-end detection | `:69665` |
| 24 | Business-process registry, domain state-machine verification, cross-module sagas, exception paths, timeout cancellation, compensating transactions, stuck-state detection | `:73606` |
| 25 | Data contracts, data lineage, event consistency, outbox / inbox, data quality, cross-module reconciliation, backfill repair, privacy-deletion propagation | `:77724` |
| 26 | Admin capability registry, unified workbench, entity 360° views, list filtering, bulk operations, approval separation, exception handling, config centre, field masking | `:81795` |
| 27 | Role-based UAT, synthetic test data, demo environment, browser and device compatibility, localisation QA, draft recovery, notification-content verification, import / export usability, support knowledge base | `:85435` |
| 28 | Automated regression platform, test pyramid, contract tests, model-based tests, property tests, visual regression, mutation testing, flaky-test governance, test-data isolation, impact analysis | `:89577` |
| 29 | Production load model, API performance budgets, concurrency hotspots, race tests, spike / stress / soak, database and cache tuning, queue backpressure, rate limiting, autoscaling, capacity cost model | `:93669` |
| 30 | Threat modelling, attack surface, SAST / SCA / secret scanning, DAST and fuzzing, authn/authz security, injection and SSRF, file upload, payment webhooks, privacy leakage, AI prompt injection, skill sandbox supply chain, penetration testing | `:97199` |
| 31 | SLOs, error budgets, end-to-end observability, synthetic business monitoring, HA for API / database / Redis / worker, provider circuit breaking, chaos engineering, backup-restore game days, disaster recovery, incident command | `:101485` |
| 32 | Final product certification, quality scoring, Go/No-Go, release approval, production observation window, 24h / 7d / 30d stability certification, evidence archival, `PRODUCTION_STABLE` | `:106763` |

## Boundaries that must not drift

- Batch 15 owns like / skip / withdraw / mutual match / invitation / contact exchange. Batch 14
  never creates any of these.
- Mutual like **does not** auto-publish contact details. The chain is mutual match → invitation
  → acceptance → both sides separately confirm exchange → only verified contacts the member
  explicitly chose. This stays configurable; the final product policy is undecided.
- Batch 16 owns relationship stages. A formal stage change needs both sides; either side can
  pause or end unilaterally; an administrator can never confirm a stage, restore a relationship
  or declare a relationship formed on a member's behalf.
- Batch 17 does not re-implement products, prices, orders or payment. It sits on Batch 4 and
  Batch 5: membership plan → catalog SKU → subscription → `MEMBERSHIP_ACCESS` entitlement.
  Tier names, prices and quotas stay versioned and configurable — never hardcoded.
- Batch 18 is the Trust & Safety control plane for every other module, including a block that
  propagates into recommendations, interactions, relationships and notifications.

## Per-batch working standard

Each batch runs the same sequence, and no step is skipped:

1. Plan and architecture document under `docs/implementation/` and `docs/architecture/`
2. Migrations that enforce invariants at the database layer
3. Module implementation under `services/api/src/vav/modules/`
4. RBAC permissions and roles
5. Four test suites: unit, integration, concurrency, security (plus fairness where relevant)
6. Backend and frontend, both apps
7. E2E specs
8. Acceptance report under `docs/acceptance/`
9. Full regression across the whole backend suite, not just the new module

## Process rules learned the hard way

- **Commit to the user's repository after every batch.** Work done in an ephemeral cloud
  sandbox and delivered only as a tarball is lost when the session ends. A batch is not
  finished until `git log` on the user's machine shows it.
- **Report only measured numbers.** Every figure in an acceptance report must come from a
  command run in that session, with the command recorded.
- The connected-folder mount cannot delete files. `git` leaves a stale `.git/index.lock` and
  `.git/objects/tmp_obj_*` after each write; move the lock aside before the next git command.
- Reproducing CI locally needs: PostgreSQL 16 with `pgvector`, Redis, `AI_ENABLED=true`, the
  dev auth keys, `alembic upgrade head`, and the eleven seed commands from
  `.github/workflows/backend-ci.yml`. Without the seeds, 25 tests fail on missing fixtures —
  those failures are environmental, not regressions.
