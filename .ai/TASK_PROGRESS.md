---
schema_version: 1
last_updated: 2026-08-18T17:20:00+08:00
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

- ID: `requirement-audit-and-executable-release-gates`
- Status: `IN_PROGRESS` — G1 and G2 now have executed evidence; G3, G4 and G5
  remain open for reasons recorded per gate below.
- Owner: Claude
- Objective: check the 42 catalogued requirements against both repositories,
  implement whatever is genuinely missing, then run every release gate that can
  be run and state plainly which ones cannot.
- Branches: backend `main` at `d21b47c`; frontend `main` at `f6f4b7d`. Both
  are one commit ahead of `origin/main` and both working trees are clean.

### Requirement coverage — `PASSED` at `E0`

- All 42 requirements in the skill package's `requirement_catalog.json` now
  resolve to concrete artefacts. The probe list lives in the session record,
  not in the repository; regenerating it is cheap and it is deliberately not
  a committed gate, because it proves presence and nothing more.
- The first pass reported four gaps. Three were probe errors, not absences:
  the login page is `AuthPage.vue`, the admin activity endpoints are 17 routes
  inside `activities/router.py` rather than an `admin_router.py`, and the role
  gates are `test_permission_policy.py` and `test_design_permissions.py`.
- `PAY-003` was the one real gap and is closed by `c4f2680`. Scope was
  deliberately limited to stubs, contracts and flags, because the blocker is
  `DEC-005` — the Chinese collection entity and merchant accounts — and not
  engineering. WeChat Pay and Alipay implement the payment protocol, refuse
  every money-moving method with a 503 naming the decision, are never
  substituted by the local fake, and cannot be listed in
  `PAYMENT_ENABLED_PROVIDERS` without failing startup.
- This is `E0` evidence. It says every requirement has an implementation; it
  says nothing about whether that implementation is accepted.

### Gate G1 — build and static quality — `PASSED` at `E1`

- `ruff check`, `ruff format --check`, `mypy services/api/src services/worker/src`
  and `scripts/check_migration_heads.py` all pass.

### Gate G2 — integration on real backing services — `PASSED` at `E2`

- Executed against PostgreSQL 16 with pgvector, citext and pgcrypto, Redis 7,
  and a real S3-compatible endpoint. Object storage was `moto` rather than
  MinIO: it is a real S3 implementation over HTTP, not a mocked client, so the
  presigned-POST and size-ceiling paths are genuinely exercised.
- 112 migrations applied to head `20260813_0112` from an empty database,
  producing 558 tables. `alembic current` reports `(head)` and the single-head
  check passes.
- 18 seeds applied, then applied again; `permissions` stayed at 808 rows. That
  second run is what actually evidences `DATA-002`'s idempotency requirement.
- Full suite: **1772 tests, 1 skipped, 446s**, zero failures after the defect
  below was fixed.
- Reproduce with `scripts/release/run_local_gates.sh`, added in `d21b47c`. It
  reported `passed=10 failed=0` when executed end to end.

#### Two defects the run surfaced

- The first full run failed one registration test with `429`. The cause was
  `rate:register:ip:*` counters surviving from the previous run in the same
  Redis; CI never sees it because each job gets a fresh container. The runner
  now flushes Redis first, so a local run and a CI run mean the same thing.
- The `PAY-003` test committed in `c4f2680` was passing for the wrong reason.
  `payment_enabled_providers` carries a `validation_alias` and the model does
  not set `populate_by_name`, so passing the field name was silently ignored
  and the assertion ran against the default provider list. It passed under a
  newer `pydantic-settings` and failed under the pinned one. The test now uses
  the alias, and a new test pins the alias-only behaviour. The guard itself was
  never wrong: removing it still fails the test.

### Gate G3 — full local runtime — `PARTIAL`

- The API half is covered: the suite above runs against real PostgreSQL, Redis
  and object storage.
- The browser half is not. Actual login, admin publish and My Events need both
  frontends running under `playwright.complete.config.ts`. `NOT_RUN`.

### Gate G4 — external UAT — `NOT_RUN`, tooling ready

- `e2e/external-uat/deployed-smoke.spec.ts` (frontend `f6f4b7d`) targets the
  deployment and asserts what only a deployment can show: the application's own
  `X-Request-ID` on liveness, `postgresql: ok` in readiness, an exact CORS
  origin echo with credentials, and `/assets/` responses that are real files
  rather than the SPA shell.
- It refuses to run without `E2E_USER_WEB_URL`, `E2E_ADMIN_WEB_URL` and
  `E2E_API_BASE_URL`, and refuses localhost outright. Both refusals were
  verified by running them. Gathering E4 evidence from a dev server is the
  "mock/sandbox evidence presented as live" blocker.
- It is a smoke suite. Passing it would show the deployment is reachable and
  coherent; `UAT_READY` still needs a person to work through
  `references/UAT_CHECKLIST.md`.

### Gate G5 — production certification — `NOT_CERTIFIED`

- Not automatable, and deliberately not attempted. Live merchant certification,
  privacy and compliance approval, content licences, on-call and real-user
  acceptance are attested by accountable people through
  `scripts/certification/external_gate_intake.py`, which is fail-closed.
- `DEC-005` is an open P0-adjacent decision and is now surfaced in the release
  manifest's `pending_decisions`, so the absence is visible in the release
  report rather than only in the code that refuses.

- Next action: push both commits, then run the G4 suite against the deployment
  and attach its report.
- Blockers: `DEC-005` for the Chinese channels; a human tester for G4; the G5
  attestations.

## Open follow-ups

- `showcase-recommendation-neon-closure` remains `IN_PROGRESS`: PR 13 is merged
  as `ca62996`, but the post-merge deterministic showcase seed failed because
  three independent ready-recommendation fixture members were unavailable. That
  failure requires a separate remediation and rerun; all external certification
  gates remain `NOT_CERTIFIED`.

- The runtime-image Trivy failure's recorded cause is wrong and the entry above
  no longer states it. `moto[s3]` is declared in `[dependency-groups] dev`, and
  the `production` stage of `infra/docker/backend.Dockerfile` runs
  `uv sync --frozen --all-packages --no-dev`. Replaying both stages of that
  Dockerfile against the repository's own `pyproject.toml` and `uv.lock`
  confirmed `--all-groups` installs `moto` in the `base` layer and `--no-dev`
  prunes it back out, so it is not in the production venv. What the production
  stage does still carry is `/app/pyproject.toml` and `/app/uv.lock`, inherited
  from `base` — a manifest Trivy parses as a language-specific lockfile and
  which lists every dev dependency whether or not it is installed. That is the
  most probable mechanism and it has NOT been confirmed: Trivy could not be
  fetched in this environment, so no scan was run. Next check: scan the built
  production image, and if the lockfile is the source, stop shipping build
  manifests in the runtime stage rather than suppressing the finding.

- The visual-regression baselines were checked and are `NOT_AFFECTED` by the
  background work. `tests/ui/visual.spec.ts` is run by
  `playwright.ui.config.ts`, whose `webServer` serves `@vav/design-system` on
  port 4178 — not `user-web`. That app's `main.ts` imports only
  `@vav/design-tokens`, `@vav/ui-core` and its own `catalog.css`, none of which
  were touched, and opening `desktop-light-chromium-darwin.png` confirms the
  baseline is the design-system catalogue page. No `--update-snapshots` run is
  needed. An earlier claim in conversation that all four baselines would fail
  was wrong.

- `RESOLVED` 2026-08-18 — the 768px dark-theme collision between
  `.ai-prompt-card` and the "开始认识" button is gone. The hero no longer stacks
  absolutely positioned panels, so the class of defect is gone with it.
  Re-measured at 768px in the dark theme in both repositories: no pair of hero
  panels intersects.

## Recent repository history observed

These commits were present on `admin/usability-closure` at the current-task
snapshot. Their presence is not proof that every associated external gate ran.

- `ed4234a` — `test(rbac): add complete role function gates`
- `ee398cf` — `fix(admin): align notification release controls`
- `5392986` — `feat(certification): add external gate intake`
- `7c60e8b` — `style: remove trailing whitespace`
- `9c4c276` — `feat: complete member journeys and production gates`

## Completion log

### 2026-08-18 — Requirement audit and executable release gates

- Status: `IN_PROGRESS`. Coverage and the two automatable gates are evidenced;
  the remaining gates are recorded with the specific reason each is open.
- All 42 catalogued requirements resolve to artefacts. `PAY-003` was the only
  real gap and is closed as stubs-and-refusal, matching its stated scope.
- G1 and G2 were executed rather than asserted: 112 migrations, 558 tables, 18
  idempotent seeds and 1772 tests against real PostgreSQL, Redis and S3.
- Two defects surfaced by running rather than reading: a non-hermetic Redis
  that makes a local re-run fail where CI passes, and a test of my own that
  asserted against a default value because the field only populates by alias.
- The release manifest's migration target had drifted 26 revisions behind and
  is now derived from the chain; writing that resolver exposed a second bug in
  which 26 of 112 files were invisible to it.
- G3 is partial, G4 has tooling but no run, G5 is unchanged and unchangeable by
  automation. All three are emitted as explicit `NOT_RUN` rows by the runner,
  because an unmentioned gate reads as a passing one.

### 2026-08-18 — Public marketing shell layout audit and rebuild

- Status: `COMPLETED` and `PUSHED` — `fcbd8ef` here, `97e0d49` in
  `vavactivityWeb`.
- Ten layout and contrast defects on the home page, the seven public tabs and
  the footer were reproduced in a real browser, fixed, and re-verified at four
  breakpoints in three themes. The footer group grid, the shrink-to-fit header
  bar and the five competing page gutters were the structural ones.
- The same 11-file change set was applied to both repositories, but the
  deployment repository's own versions were patched in place rather than
  overwritten: it had already diverged (hero photograph, payment locale keys,
  a flex-column hero below 980px) and a file-level copy would have reverted
  that work. Two of the ten defects were already fixed there.
- Validation: see the current-task entry above. All local gates passed in both
  repositories; remote CI, browser/device UAT and production certification
  remain `NOT_RUN` / `NOT_CERTIFIED`.

### 2026-08-14 — C-end feature port, hero background and backend closure

- Status: `IN_PROGRESS`. The backend half is complete and pushed; the frontend
  half is complete and locally validated but `NOT_COMMITTED`.
- Six previously-undeployed C-end features were ported into the deployed
  frontend repository, so live backends stopped being unreachable.
- The couple photograph was applied to three C-end background surfaces with a
  different treatment for each, because the page runs the light token set and
  the photograph is a dark dusk shot; two contrast defects found along the way
  were fixed.
- Backend evidence: full suite `1700 passed / 1 failed` (MinIO-dependent), 110
  migrations applied from empty, idempotent re-run, and three
  downgrade/re-upgrade cycles on oversold data.
- Three defects were found only by executing rather than by reading: the
  capacity backfill's ceiling, the `0107` downgrade's column name, and the two
  `last_four_hmac` backfill bugs. Each is recorded under `Current task`.
- Two claims made earlier in conversation were checked and retracted here: the
  visual baselines are not affected, and the Trivy failure is not explained by
  `moto` being installed in the production image.
- Browser/device UAT, deployment and external certification remain `NOT_RUN` or
  `NOT_CERTIFIED`.

### 2026-08-14 — C-end service-first primary navigation

- Status: `COMPLETED` for local implementation and focused validation.
- `PublicLayout` now renders the existing `publicIa` product navigation as the
  C-end header authority, so Activities, Courses, Human Counseling, and
  Services are the first four destinations and the legacy CMS seed menu cannot
  replace them.
- About VAV was removed from `publicIa`; About VAV and Partnership Contact now
  appear in the footer company group only and route to `/about` and `/contact`.
- Added a regression test for exact simplified-Chinese order and the
  `/zh-CN/activities`, `/zh-CN/courses`, `/zh-CN/counseling`, and
  `/zh-CN/services` hrefs; it also verifies that `main_navigation` is not
  requested for the product header.
- Focused Vitest passed `2/2`, changed-file ESLint passed, direct Vue TypeScript
  checking passed, i18n parity passed for three locales and 829 keys, and both
  repository diff checks passed.
- Commit `3f657ef027e83866e81f8eba30b1ada551c74bbf` is `PUSHED` to frontend
  `main`, with local, tracking, and live remote refs verified equal. This
  ledger follow-up is pushed separately to backend `main`.
- Full suite/build and browser/deployment evidence remain deferred or
  `NOT_CERTIFIED`.

### 2026-08-14 — Notification controls main-integration verification

- Status: `COMPLETED` for the requested functionality and main-integration
  scope; no second merge was necessary.
- Notification release-control fix `ee398cf` is an ancestor of current
  `origin/main` through merged PR 4 (`bee990d`). The four owned files are
  unchanged between `ee398cf` and the current `main` implementation.
- Exact-code validation at `ee398cf`: targeted notification and Element Plus
  tests passed `10/10`; the full admin suite passed `137/137`; ESLint,
  typecheck, build, and diff checks passed. Browser UAT confirmed the drawer
  rendered all 14 versions and lifecycle actions matched active and superseded
  states. A new local package-manager rerun is `NOT_RUN` because the ELMOS
  exclusive disk window is still active.
- PR 4's Backend CI, Docker Build, Integration CI, Secret Scan, Security Tests,
  assembly contracts, and migration compatibility all passed before merge.
- `admin/usability-closure` now has one later unique commit, `9e250ec`, whose
  meaningful difference is an outdated coordination ledger; merging it would
  conflict with and regress the current task record, so it was intentionally
  not merged.
- Local `main` was fast-forwarded to the remote tip. No business-code commit
  was needed in this verification pass; this ledger entry is pushed directly
  to `main`, with its containing commit identified by Git history rather than
  self-recording its own SHA.
- Current post-merge Neon and runtime-image scan failures belong to later
  showcase and image work, not the unchanged notification fix. Production
  deployment and certification remain `NOT_CERTIFIED`.

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
