---
schema_version: 1
last_updated: 2026-08-14T13:20:47+08:00
repository: /Users/stephen/Documents/Projects/python/vavactivity
canonical: true
---

# Claude Code / Codex shared task progress

This is the canonical repository-local task ledger. Git state and test output
remain the primary evidence; this document records the latest verified handoff
so another agent can continue without guessing.

## Mandatory workflow

### Before work

1. Read this file completely.
2. Run `git status -sb` and inspect the relevant diff. Reconcile any drift with
   the snapshot below before editing.
3. Preserve changes whose ownership is unclear. Do not reset, rewrite, stage,
   or commit another agent's work merely because it is not yet documented.
4. Set or update the current task's owner, objective, status, scope, and next
   action before making a materially different change.

### During work

- Update this file at meaningful milestones, handoffs, and blockers. Avoid
  writing a line for every command.
- Use only these evidence states where applicable: `NOT_RUN`, `IN_PROGRESS`,
  `BLOCKED`, `PASSED`, `FAILED`, `NOT_PUSHED`, `PUSHED`, and `NOT_CERTIFIED`.
- Record exact validation commands and summarized results. A local test does
  not prove remote CI, browser/device UAT, deployment, customer acceptance, or
  production certification.
- Use ISO 8601 timestamps with timezone. Redact credentials and personal or
  production data.

### Before completion or handoff

1. Re-run the checks appropriate to the changed scope and record the evidence.
2. Record the working-tree state and, when applicable, branch, local commit
   SHA, remote SHA, push state, CI state, and remaining gates.
3. Change the current task to `COMPLETED` only when its requested scope is
   actually complete. Otherwise leave it `IN_PROGRESS` or `BLOCKED` with a
   concrete next action.
4. Append a concise entry to the completion log. Do not erase prior history.
5. Write this document before sending the final response to the user.

## Current task

- ID: `showcase-recommendation-neon-closure`
- Status: `IN_PROGRESS`; PR 13 is merged, but the post-merge Neon showcase seed
  and runtime-image vulnerability gates are `FAILED`
- Owner: Codex
- Objective: make the all-role staging showcase repeatable under real
  recommendation safety rules, merge PR 13 into backend `main`, and close the
  post-merge Neon showcase and runtime-image security gates.
- Branch: backend `main`.
- Snapshot commit: PR 13 head
  `99f6ee2485e4783c9c6cc96a3e9232f34586f5a6`, merged as
  `ca62996dd185b8adf6f36a7d9ae9048574ec2292`.
- Scope: `services/api/src/vav/cli/seed_recommendation_fixtures.py`,
  `services/api/src/vav/cli/seed_test_showcase.py`,
  `services/api/tests/system/test_admin_showcase_seed.py`, and this ledger.
- Validation: corrected PR 13 head `99f6ee2` completed with seven reported
  checks `PASSED`; the conditional Neon job was `SKIPPED` on the PR. On merged
  `main` commit `ca62996`, Backend CI core, Sensitive Domains, and Gitleaks are
  `PASSED`. The post-merge Neon job applied migrations and verified the live
  schema successfully, then `FAILED` while seeding deterministic staging
  showcases with `Three independent ready-recommendation fixture members are
  required.` Both API and worker images built and produced immutable identity
  and SBOM evidence, then `FAILED` Trivy because the runtime images contain the
  dev-only `moto` package and its AWS-key/private-key test fixtures. Local heavy
  suites remain `NOT_RUN` during the ELMOS exclusive disk window.
- Commit/push state: implementation commits `acb0b2f`, `e8e815b`, and static
  contract correction `99f6ee2` are `PUSHED`; PR 13 is `MERGED` as `ca62996`.
  This ledger correction is `PUSHED` directly to `main`; its containing commit
  is intentionally identified by Git history rather than self-recording its
  own SHA.
- Remote CI: PR 13 checks are closed; on merged `main`, the Neon showcase seed
  and both runtime-image Trivy jobs are `FAILED`. The release manifest is
  `SKIPPED` downstream of the image scan failures.
- Remaining gates: repair and rerun the Neon deterministic showcase seed and
  runtime-image vulnerability scans. Production deployment, browser/device
  acceptance, independent security authorization, HA/DR, owner approvals, and
  immutable 24h/7d/30d windows remain `NOT_CERTIFIED`.
- Next action: in a separately validated remediation, provide three independent
  ready-recommendation fixture members and keep dev-only `moto` out of runtime
  images, then rerun the failed GitHub gates.
- Blockers: ELMOS owns the host disk window; local pytest, Docker,
  package-manager builds, generators, pruning, and cleanup are paused until
  `RELEASED`.

## Recent repository history observed

These commits were present on `admin/usability-closure` at the current-task
snapshot. Their presence is not proof that every associated external gate ran.

- `ed4234a` — `test(rbac): add complete role function gates`
- `ee398cf` — `fix(admin): align notification release controls`
- `5392986` — `feat(certification): add external gate intake`
- `7c60e8b` — `style: remove trailing whitespace`
- `9c4c276` — `feat: complete member journeys and production gates`

## Completion log

### 2026-08-14 — GitHub main and shared-ledger synchronization

- Status: `COMPLETED` for the requested direct-`main` publication and `.ai`
  evidence update; the product gates listed in `Current task` remain
  `IN_PROGRESS`.
- Fast-forwarded the backend checkout to GitHub `main` merge `ca62996`, which
  contains PR 13 head `99f6ee2`; no frontend files or repository were changed.
- Replaced the stale “PR open / Neon not run” record with the verified merged
  state and the exact post-merge Neon and Trivy failure boundaries.
- Validation for this ledger-only change: `git diff --check`, staged-path
  inspection, commit creation, direct `main` push, and remote-ref equality.
- External production, browser/device, customer, security-authorization, HA/DR,
  and elapsed-observation certification remain `NOT_CERTIFIED`.

### 2026-08-13 — Backend CI closure and split-repository merge

- Status: `COMPLETED` for the approved branch-publish, CI-observation, and merge
  scope.
- Backend CI closure was integrated by commits `0703bf5`, `31f6aae`, merge
  `1456d9d`, and security follow-up `8967e4f`.
- Backend PR 4 is green: Backend CI, Secret Scan, Integration CI, Docker Build,
  Security Tests, assembly contracts, and migration compatibility all passed.
- Backend PR 5 passed all reported non-conditional checks at `97bfe85` and
  merged as `74785173`. Frontend PR 11 passed dependency installation, lint,
  typecheck, tests, build, and Vercel at `c379b16`, then merged as `bc4840c`.
- Ledger PR 8 and wording-correction PR 9 each passed their reported checks and
  merged; PR 9's Backend CI completed in 10m58s.
- Fetched both remote default branches after merge and verified backend `main`
  contains `97bfe85` and frontend `main` contains `c379b16`.
- Confirmed the long-running VAV admin-web dev server on port 5174 had no
  current browser-acceptance dependency and shut down its pnpm/Vite process
  tree using `TERM` only; no data was removed.
- Local heavy pytest and Gitleaks reruns were deliberately not completed while
  ELMOS held the exclusive low-disk window. The named remote CI gates provide
  current-commit evidence; external deployment/certification remains
  `NOT_CERTIFIED`.

### 2026-08-13 — Profile media storage v2, capacity mode, and split frontend publish

- Status: `COMPLETED` for local implementation, scoped commits, and branch
  pushes; external production certification remains `NOT_CERTIFIED`.
- Backend: committed 74 files as `1f76f217` and pushed
  `admin/usability-closure`; local and remote SHAs matched after push.
- Frontend: split the work into `c539120` and `c379b16`, rebased cleanly onto
  the current remote feature branch, pushed `codex/unify-content-card-layout`,
  and verified local/remote SHA `c379b16acb810b9a9450b19e5ad77d32789b460e`.
- Post-rebase frontend validation: user/admin typecheck passed; affected user
  tests passed `13/13`; affected admin tests passed `17/17`; i18n parity passed
  for user `3 locales / 828 keys` and admin `3 locales / 235 keys`; diff check
  passed. The backend-to-frontend handoff contract passed with 4 Skill
  artifacts, OpenAPI, Skill schema, and 40 route permissions.
- Backend validation: scoped Ruff and strict mypy checks passed; affected
  frontend tests passed `13/13`; attendee-social service tests passed `3/3`;
  user/admin typecheck and lint passed; root contract tests passed `26/26`;
  Compose rendering, project-manifest validation, unique Alembic head 0112,
  and clean/snapshot migration upgrades passed.
- Evidence limitations: local runtime smoke was `BLOCKED` by unavailable API
  port 8000 during PostgreSQL recovery; the full API suite produced no verdict.
  Remote CI failures and their exact causes are recorded in `Current task`.
- Preserved unrelated work: the two backend admin-page indentation changes
  remain unstaged; no default branch was merged and no pull request was created
  by this publish pass.
- Concurrent repository update: after Codex pushed `0d3eb18`, commit
  `cad44497` removed `.ai/`, `CLAUDE.md`, and the coordination additions in
  `AGENTS.md` from Git tracking while preserving the local files. The backend
  branch is verified at that remote SHA; this ledger remains available locally
  for Claude Code/Codex handoff and records the post-commit state.

### 2026-08-13 — Shared Claude Code / Codex task ledger

- Status: `COMPLETED` for the repository-local coordination mechanism.
- Created `.ai/README.md` and this canonical `.ai/TASK_PROGRESS.md` ledger.
- Updated `AGENTS.md` for Codex and created `CLAUDE.md` for Claude Code; both
  require reading the ledger before work and writing results back before task
  completion or handoff.
- Seeded the ledger with the active dirty-worktree snapshot and the most recent
  verified completion evidence without modifying the concurrent feature work.
- Validation: all four coordination files exist, `.ai/` is not ignored by Git,
  and the files contain no trailing whitespace.
- Commit/push state: `NOT_PUSHED`; this coordination change remains uncommitted
  alongside a pre-existing dirty worktree and must be scoped deliberately.

### 2026-08-13 — Member journeys and production-gate implementation

- Status: `COMPLETED` for the requested local implementation and push scope.
- Branch: `admin/usability-closure`.
- Commits: `9c4c276` (member journeys and production gates) and `7c60e8b`
  (trailing-whitespace cleanup).
- Remote verification at completion: local and remote both resolved to
  `7c60e8b1bfa96725b73c4a2e5293fc45727a6f48`.
- Backend validation: full suite `422 passed, 1 skipped`; changed Python Ruff
  checks passed; targeted strict mypy passed; clean database migrated to the
  unique Alembic head `20260813_0110`.
- Frontend validation: user tests `50/50`, admin tests `133/133`, typecheck and
  three-locale key parity passed.
- Runtime/config validation: `docker compose config --quiet`,
  `./scripts/vavctl doctor`, and `./scripts/vavctl smoke` passed.
- Sensitive-pattern and branch-diff whitespace checks passed after cleanup.
- Remote CI: `NOT_RUN` because GitHub reported no workflow runs or commit
  checks for the branch.
- External deployment, provider, browser/device acceptance, and production
  certification: `NOT_CERTIFIED`.

## Template for the next task

Copy this block into `Current task` and replace every placeholder:

```text
- ID: <stable-task-id>
- Status: NOT_RUN | IN_PROGRESS | BLOCKED | COMPLETED
- Owner: Claude Code | Codex | shared | unclaimed
- Objective: <concrete requested outcome>
- Branch: <branch>
- Snapshot commit: <full SHA>
- Scope: <owned files or modules>
- Validation: <commands and results, or NOT_RUN>
- Commit/push state: <SHA and remote verification, or NOT_PUSHED>
- Remaining gates: <explicit evidence gaps>
- Next action: <one concrete continuation step>
- Blockers: <none or exact blocker>
```
