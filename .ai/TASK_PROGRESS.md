---
schema_version: 1
last_updated: 2026-08-13T17:04:31+08:00
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

- ID: `profile-media-storage-v2-capacity-mode`
- Status: `COMPLETED` for the requested local implementation and scoped
  branch-publish checkpoint
- Owner: shared feature implementation; Codex completed the validation and
  split-repository publish pass
- Objective: finish the explicit capacity-mode and profile-media storage-v2
  hardening/release work, including client contracts, privacy/export handling,
  worker routing, migrations, deployment configuration, and release gates.
- Branch: `admin/usability-closure`
- Implementation commit:
  `1f76f217bb714e8fb51c3d44bbdbe954fa66855b` on
  `admin/usability-closure`; the matching remote branch was verified after
  push.
- Frontend commits: `c539120` (admin workflows) and `c379b16` (user attendee
  social and private media flows) on `codex/unify-content-card-layout` in the
  sibling `vavactivityWeb` repository. The branch was rebased onto remote
  `ef2ce34`, pushed, and local/remote were both verified at
  `c379b16acb810b9a9450b19e5ad77d32789b460e`.
- Working tree after the scoped backend implementation commit: only two
  pre-existing, unstaged indentation-only changes remain in
  `apps/admin-web/src/pages/SkillManagementPage.vue` and
  `apps/admin-web/src/pages/SystemOperationsPage.vue`; they are not part of
  this task and were deliberately left unstaged. The frontend worktree is
  clean after push.
- Observed scope: profile-media upload/grants/storage inspection, attendee
  social contract handling, privacy export, explicit capacity mode, migrations
  `0111` and `0112`, API/worker routing, deployment templates, release gate,
  documentation, and targeted tests.
- Key rollout document: `docs/deployment/profile-media-storage-v2.md`
  describes a feature-disabled expand migration and digest/evidence-gated
  activation. It was untracked at the snapshot and is not yet certified.
- Validation recorded here: `PASSED` for the scoped static, contract, frontend,
  and migration gates. Ruff passed; strict mypy passed for 16 affected API
  source files and 2 worker source files; affected frontend tests passed
  `13/13`; attendee-social service tests passed `3/3`; user/admin typecheck
  passed; user i18n parity passed for 3 locales and 1134 keys; user lint passed;
  admin lint passed with 0 errors and 1 pre-existing warning; root contract
  tests passed `26/26`; development and production Compose configuration
  rendered successfully with explicit safe production placeholders; the
  project manifest validates 40 modules and 112 migrations; Alembic reports the
  single head `20260813_0112`; and the isolated migration gate passed for both
  an empty database and a revision-0082 snapshot upgrade through 0112.
- Validation limitations: the first root contract invocation failed collection
  until the repository root was added to `PYTHONPATH`, then passed. The first
  production Compose invocation intentionally failed closed without required
  digest/secret variables, then rendered with explicit non-secret placeholders.
  The full API suite did not produce a verdict because the shared local
  PostgreSQL entered recovery and the test database was later cleaned up by a
  concurrent validation process. A first attendee-social retry was likewise
  blocked by database recovery; its CI-isolated retry passed `3/3`.
- Runtime smoke: `BLOCKED`; `./scripts/vavctl doctor` passed, but
  `./scripts/vavctl smoke` could not connect to port 8000 while the local API
  service was unavailable during PostgreSQL recovery. This is not recorded as
  a product pass or failure.
- Commit/push state: `PUSHED` for backend implementation commit `1f76f217` and
  frontend commit `c379b16`; both remote SHAs were verified.
- Remote CI for backend `1f76f217`: `PASSED` for Docker Build, Security Tests,
  and PR Production Gates; `FAILED` for Backend CI because the branch has 15
  full-service Ruff findings outside this scoped implementation, and `FAILED`
  for Secret Scan because full-history scanning flags two test fixture strings
  introduced by historical commits `9c4c276` and `a84299b`. Integration CI is
  `FAILED` because it checks the frontend repository's default `main` branch,
  which lacks seven route permissions; the pushed frontend feature branch
  contains them and the same handoff contract passes locally. Frontend CI for
  final SHA `c379b16` is `NOT_RUN` at this checkpoint.
- Production state: `NOT_CERTIFIED`.
- Next action: integrate `codex/unify-content-card-layout` into the frontend
  default branch through an authorized review/merge, then rerun backend
  Integration CI; separately resolve the branch-wide Ruff and historical
  Gitleaks findings and rerun those workflows.
- Blockers: the frontend default-branch merge requires separate authorization;
  local runtime smoke and the full API suite require a stable local
  API/PostgreSQL runtime. These do not invalidate the published, locally
  validated implementation checkpoint.

## Recent repository history observed

These commits were present on `admin/usability-closure` at the current-task
snapshot. Their presence is not proof that every associated external gate ran.

- `ed4234a` — `test(rbac): add complete role function gates`
- `ee398cf` — `fix(admin): align notification release controls`
- `5392986` — `feat(certification): add external gate intake`
- `7c60e8b` — `style: remove trailing whitespace`
- `9c4c276` — `feat: complete member journeys and production gates`

## Completion log

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
