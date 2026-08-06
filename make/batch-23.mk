.PHONY: experience-migrate experience-seed experience-sync experience-ia-check experience-route-check \
	experience-task-check experience-journey-check experience-handoff-check experience-search-test \
	experience-dead-end-scan experience-test experience-security-test experience-user-e2e \
	experience-admin-e2e experience-evidence-build experience-frontend-test experience-verify

experience-migrate:
	docker compose exec -T api alembic upgrade head

experience-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_experience

experience-sync:
	uv run --package vav-platform-api python scripts/experience/control.py sync

experience-ia-check:
	uv run --package vav-platform-api python scripts/experience/control.py ia-check

experience-route-check:
	uv run --package vav-platform-api python scripts/experience/control.py route-check

experience-task-check:
	uv run --package vav-platform-api python scripts/experience/control.py task-check

experience-journey-check:
	uv run --package vav-platform-api python scripts/experience/control.py journey-check

experience-handoff-check:
	uv run --package vav-platform-api python scripts/experience/control.py handoff-check

experience-search-test:
	uv run --package vav-platform-api pytest services/api/tests/experience/integration services/api/tests/experience/security -q

experience-dead-end-scan:
	uv run --package vav-platform-api python scripts/experience/control.py dead-end-scan

experience-test:
	uv run --package vav-platform-api pytest services/api/tests/experience/unit services/api/tests/experience/integration services/api/tests/experience/concurrency --junitxml=build/experience/backend-junit.xml -q

experience-security-test:
	uv run --package vav-platform-api pytest services/api/tests/experience/security -q

experience-frontend-test:
	corepack pnpm --filter @vav/navigation-contracts --filter @vav/journey-contracts --filter @vav/experience-components --filter @vav/search-components --filter @vav/help-components test
	corepack pnpm --filter @vav/navigation-contracts --filter @vav/journey-contracts --filter @vav/experience-components --filter @vav/search-components --filter @vav/help-components typecheck
	corepack pnpm --filter @vav/user-web --filter @vav/admin-web test
	corepack pnpm --filter @vav/user-web --filter @vav/admin-web build

experience-user-e2e:
	corepack pnpm exec playwright test e2e/experience/experience.user.spec.ts

experience-admin-e2e:
	corepack pnpm exec playwright test e2e/experience/experience.admin.spec.ts

experience-evidence-build:
	uv run --package vav-platform-api python scripts/experience/control.py evidence

experience-verify: experience-sync experience-ia-check experience-route-check experience-task-check \
	experience-journey-check experience-handoff-check experience-dead-end-scan experience-test \
	experience-security-test experience-frontend-test experience-evidence-build
