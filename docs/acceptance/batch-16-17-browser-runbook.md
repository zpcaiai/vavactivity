# Batch 16-17 browser acceptance runbook

The Batch 16 relationship and Batch 17 membership suites now run against the
real Vue pages and API responses. They assert that seeded domain data is
rendered, not merely that each route returns HTML.

## Existing Docker Compose services

With the API available at `http://localhost:8000`, run:

```bash
corepack pnpm run test:e2e:batch16-17
```

Set `E2E_CAPTURE_ALL=1` to retain screenshots, Trace, and video for passing
tests as well as failures.

Playwright starts the user and admin Vite applications itself. Fixture setup
uses `docker compose exec` by default.

## No Docker image registry

Point `DATABASE_URL`, `REDIS_URL`, and the remaining backend settings at
reachable development dependencies. The schema must already be migrated. Then
run the API, fixtures, and browser tests from the host Python environment:

```bash
E2E_START_LOCAL_API=1 \
VAV_E2E_SEED_MODE=local \
corepack pnpm run test:e2e:batch16-17
```

Use `VAV_E2E_PYTHON=/absolute/path/to/python` when the interpreter is not
`.venv/bin/python`. If the API and both web applications are already running,
set `E2E_EXTERNAL_WEBSERVERS=1` and provide `E2E_API_BASE_URL`,
`E2E_USER_WEB_URL`, and `E2E_ADMIN_WEB_URL` as needed.

## Evidence boundary

The implementation closes the missing executable browser path. Acceptance
reports remain `NOT_RUN` until Chromium completes and the generated report,
trace, screenshots, or video are retained under `artifacts/`.
