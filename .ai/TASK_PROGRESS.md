---
schema_version: 1
last_updated: 2026-08-18T12:30:00+08:00
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

- ID: `cend-feature-port-and-hero-background`
- Status: `IN_PROGRESS` — backend is pushed; the frontend half is complete and
  validated locally but is `NOT_COMMITTED`.
- Owner: Claude
- Objective: implement the batch of requirements at code level, then make the
  six resulting C-end features actually reachable by a member and put the
  couple photograph behind the C-end background surfaces.
- Branches: backend `main` at `0149c7c` (clean, in sync with `origin/main`);
  frontend `main` at `3f657ef` with an uncommitted working tree.

### Backend — `PUSHED`

- Business code, migrations and tests landed in `9c4c276`
  (`feat: complete member journeys and production gates`) and `1f76f21`
  (`feat(profile-media): harden storage and capacity release`). The migration
  chain now runs to `20260813_0112`, 112 revisions in total.
- Validation: full suite `1700 passed / 1 failed`. The single failure needs a
  live MinIO endpoint and is environmental, not a code defect. Failure
  attribution for the earlier red run was carried out in full — 22 missing seed
  manifests, 7 missing validator script, 2 cwd-relative paths, 1 MinIO, and 3
  genuinely mine, all three fixed.
- Migrations: `PASSED`. 110 revisions applied from an empty database, the
  re-run proved idempotent, and downgrade-then-re-upgrade was exercised three
  times against deliberately oversold capacity data.
- `20260812_0106` was rewritten after a real run on this machine failed with
  `activity_capacity_counters_check`. The original backfill derived a capacity
  ceiling stricter than the platform's own rule in `catalog/inventory.py`; it
  now honours `inventory_policy` and `overselling_allowed`, and writes an
  `activity_capacity_events` row per genuine oversell instead of silently
  clamping.
- `20260812_0107`'s downgrade recreated `ai_human_escalations` with
  `created_at` where migration 0103 defines `opened_at`, so a partial rollback
  followed by a retry failed on `column e.opened_at does not exist`. The
  downgrade now matches 0103 column for column.
- The `last_four_hmac` backfill was run for real with `--apply`. Running it
  surfaced two defects a unit test would not have: an uncaught `VavError` from
  `decrypt_private` aborted the whole job on one corrupt ciphertext, and
  predicate-only paging re-read unfixable rows every batch. Both fixed; paging
  is now keyset.
- `content_entries.current_version` carried two incompatible meanings and could
  be reproduced into a `UniqueViolation` in three writes. Migration
  `20260813_0110` splits head-of-history from the live revision.

### Frontend — `NOT_COMMITTED`

- Six features existed only in the backend repository's retired `apps/` mirror
  and had never been deployed: `post-event`, `matchmaking-access`,
  `discovery`, `couples`, `assessments`, `member-dashboard`. Their backends are
  live; only the pages were missing. All 32 files plus router, IA and locale
  wiring were ported into `vavactivityWeb`.
- Router, IA and locale files were merged key by key rather than copied.
  `vavactivityWeb` already carried the service-first navigation change from
  `3f657ef` and a `follows` entry the backend mirror does not have; a file-level
  copy would have silently reverted both.
- `apps/README.md` was added to the backend repository declaring `apps/` a
  retired mirror, so the same six features cannot be stranded again.
- The couple photograph now backs `.home-hero-image` at full strength, `body`
  as a masked ambient wash at a tenth opacity, and `.product-card-art` beneath
  the brand gradient. Encoded to WebP: 1.47 MB PNG to 40 KB, 97% smaller, and
  it now loads on every page.
- Two contrast defects were found and fixed while verifying: the hero `h1` sat
  at 1.01:1 and `.journey-section` body copy at 1.12:1. A control build proved
  the hero defect pre-existed the photograph rather than being caused by it.
- Validation: 85 frontend tests passed, i18n parity passed for three locales
  and 1141 keys, `vue-tsc` reported 0 errors, ESLint reported 0, production
  build succeeded. A control test proved the new routes are registered — a
  bogus path renders the 404 page while every ported path renders the login
  gate.
- Commit/push state: `NOT_COMMITTED`. Six modified files and eight new paths
  are sitting in the `vavactivityWeb` working tree.

- Next action: commit and push the `vavactivityWeb` working tree, then run
  browser UAT on the ported routes.
- Blockers: none technical. All external certification gates remain
  `NOT_CERTIFIED`.

### Public marketing shell layout — `NOT_COMMITTED`

- ID: `public-shell-layout-audit-2026-08-18`
- Status: `COMPLETED` for the requested scope; `PUSHED` in both repositories.
- Owner: Claude
- Objective: audit and fix the layout of the marketing home page, the seven
  public navigation tabs and the site footer.
- Branches: backend `main` at `0cc4ea5`, frontend `main` at `d7dee74`; both
  working trees dirty.
- Scope (11 files, identical set in both repositories):
  `apps/user-web/src/assets/main.css`,
  `apps/user-web/src/layouts/PublicLayout.vue`,
  `apps/user-web/src/features/public-site/pages/CmsPage.vue`,
  the three `apps/user-web/src/i18n/locales/*.json`,
  `packages/design-tokens/src/layout/tokens.json` and the four regenerated
  `packages/design-tokens/generated/*` artefacts.
- Defects found, each reproduced in a real browser before being fixed:
  1. `.site-footer > div` (a leftover rule) outranked `.site-footer__groups` on
     specificity, so the four footer link groups rendered as one flex row with
     an 11.2px gap at every breakpoint. Confirmed by computed style, not by
     reading.
  2. `.site-footer` carried three competing definitions across the file that
     resolved only by source order.
  3. `.site-footer p, a` referenced `--vav-color-muted`, which is not a token.
  4. `.site-header` was `width: auto` with `margin-inline: auto`, i.e.
     shrink-to-fit, so the bar changed width per route and per locale
     (measured 1009px against a declared 1408px cap).
  5. Five different content left edges across the eight public routes
     (measured at 1440px: 89 / 126 / 0 / 181, header 215, footer 58).
  6. `/membership` uses `UserPageLayout`, whose gutter comes from
     `.app-shell__content`; under the public shell it had none and rendered at
     `x = 0`.
  7. `.editorial-page` forced `1.1fr 0.9fr` and `min-height: 680px` on three
     routes that never render an `.editorial-art`, leaving a permanently empty
     right half.
  8. `/about` rendered no `h1` in its loading and error states, which also
     defeats the layout's post-navigation focus handler.
  9. The hero stacked four absolutely positioned panels in a fixed-height box;
     the AI card overlapped the member-proof strip, and `member-proof` was
     hidden below 1180px to hide the collision.
  10. Six surface or literal colours were used as text colours, invisible in the
      light theme.
- Fixes: new `layout.site.*` design tokens (`maxWidth`, `gutter`,
  `gutterCompact`, `headerHeight`, `sectionGap`); one page container shared by
  the header bar, all four page-container classes and the footer; footer
  rebuilt as `__inner` / `__meta` with a 4 / 2 / 1 column ladder and a
  `<nav aria-label>` wrapper; hero converted to `grid-template-areas`; all
  colour literals resolved through semantic tokens; the footer year is now
  computed rather than hard-coded.
- Validation (both repositories, 2026-08-18):
  `vue-tsc -b --force` `PASSED` (0 errors);
  `eslint src` `PASSED` (0);
  `vitest run` `PASSED` — backend repo 58/58, deployment repo 97/97;
  `check-design-tokens` `PASSED`; `check-i18n` `PASSED` (3 locales, 1135 and
  1142 keys); `design-tokens` unit tests `PASSED`;
  `vite build` `PASSED`.
- Browser evidence: a Linux container reproduction of the deployment (`pnpm
  install`, `vite build`, `vite preview`, Playwright/Chromium) captured the
  eight public routes at 1440 / 1024 / 768 / 390 before and after, plus dark
  and high-contrast passes. Post-fix measurements: one content left edge
  (`60..1380`) on all eight routes, footer grid `4 / 2 / 2` columns across the
  ladder, zero horizontal overflow at every breakpoint, and no overlapping hero
  panels.
- Not covered: the member-space `AppShell` tabs and `admin-web` were out of the
  agreed scope. Live API data was unavailable in the container, so every route
  was verified in its empty or error state — full-content layouts still need a
  pass against a running backend.
- Commit/push state: `PUSHED`. `fcbd8ef` in this repository (fast-forward from
  `0cc4ea5`) and `97e0d49` in `vavactivityWeb` (fast-forward from `989a2ed`,
  carrying the pre-existing `d7dee74` with it). Both verified by
  `git ls-remote` against GitHub rather than by trusting the local
  remote-tracking refs, which had drifted.
- Next action: re-verify the eight public layouts against a running API. Every
  route was checked in its empty or error state, because the container
  reproduction had no backend.
- Blockers: none.
- Note on tooling, for the next agent. `git push` from the agent's device
  shell prints `fatal: ... Received HTTP code 403 from proxy after CONNECT` and
  looks like a hard failure. It is not: every commit made in this session
  reached `origin/main` anyway, a few minutes later, and a subsequent
  `git push` from the host answered `Everything up-to-date`. The mechanism was
  not identified — there is no `post-commit` hook, no `url.*.insteadOf`
  rewrite, and a `git ls-remote` run immediately after the push still showed
  the old SHA. Two rules follow:
  1. Treat neither the push output nor the local remote-tracking ref as
     evidence. `refs/remotes/origin/main` moves on its own here. The only
     authority is `git ls-remote <url> refs/heads/main` from a networked shell,
     polled until it shows the expected SHA.
  2. Never `amend` or rebase a commit made in this session. Assume it is
     already public, or about to be. Doing otherwise diverged local `main` from
     a published commit once in this session and cost a `reset --soft` to
     unwind.
  The earlier version of this note, and the message on commit `2185193`, both
  gave a confident wrong explanation (an `insteadOf` SSH fallback). They are
  left in history rather than rewritten, for the same reason as rule 2.

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
