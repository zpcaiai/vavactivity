# Deployment platforms

VAV has one supported production deployment topology:

- Backend: Render service `vav-platform-api`, declared by `/render.yaml` in the backend repository.
- Frontend: Vercel project built from the root of the `vavactivityWeb` repository.

## Backend on Render

The Render Blueprint tracks `main` and deploys only after the linked GitHub checks pass. It builds
`infra/docker/backend.Dockerfile` and probes `/api/v1/health/live`.

Secrets marked `sync: false` must be configured in the Render dashboard. At minimum, confirm the
database URL, authentication keys, object-storage credentials, AI provider key, and the actual
admin frontend URL. Never commit those values.

The frontend origins configured in `APP_CORS_ORIGINS`, `AUTH_ALLOWED_ORIGINS`, `USER_WEB_URL`,
`ADMIN_WEB_URL`, and `PUBLIC_WEB_BASE_URL` must match the Vercel production domains. A successful
health probe does not prove authentication works; verify readiness, CORS preflight, and both user
and admin login after every production deployment.

## Frontend on Vercel

Vercel must import the root of `vavactivityWeb`, not either application subdirectory. The root
`vercel.json` runs `scripts/vercel-build.mjs` and publishes `dist/public`:

- `/` serves `apps/user-web`.
- `/admin/*` serves `apps/admin-web`.

Set `VITE_API_BASE_URL` in Vercel Production and Preview environments to the intended Render API.
The Git integration creates production deployments from `main`; no duplicate GitHub Actions deploy
workflow or long-lived Vercel CLI token is required.

The checked-in Kubernetes and Compose resources remain local/self-hosted reference infrastructure.
They are not active production deployment targets.
