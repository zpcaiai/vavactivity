.PHONY: experience-migrate experience-seed experience-sync experience-ia-check experience-route-check \
	@./scripts/run_if_available.sh experience-task-check experience-journey-check experience-handoff-check experience-search-test \
	@./scripts/run_if_available.sh experience-dead-end-scan experience-test experience-security-test experience-user-e2e \
	@./scripts/run_if_available.sh experience-admin-e2e experience-evidence-build experience-frontend-test experience-verify

experience-migrate:
	@./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

experience-seed:
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_experience

experience-sync:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/experience/control.py sync

experience-ia-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/experience/control.py ia-check

experience-route-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/experience/control.py route-check

experience-task-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/experience/control.py task-check

experience-journey-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/experience/control.py journey-check

experience-handoff-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/experience/control.py handoff-check

experience-search-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/experience/integration services/api/tests/experience/security -q

experience-dead-end-scan:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/experience/control.py dead-end-scan

experience-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/experience/unit services/api/tests/experience/integration services/api/tests/experience/concurrency --junitxml=build/experience/backend-junit.xml -q

experience-security-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/experience/security -q

experience-frontend-test:
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/navigation-contracts --filter @vav/journey-contracts --filter @vav/experience-components --filter @vav/search-components --filter @vav/help-components test
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/navigation-contracts --filter @vav/journey-contracts --filter @vav/experience-components --filter @vav/search-components --filter @vav/help-components typecheck
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/user-web --filter @vav/admin-web test
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/user-web --filter @vav/admin-web build

experience-user-e2e:
	@./scripts/run_if_available.sh corepack pnpm exec playwright test e2e/experience/experience.user.spec.ts

experience-admin-e2e:
	@./scripts/run_if_available.sh corepack pnpm exec playwright test e2e/experience/experience.admin.spec.ts

experience-evidence-build:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/experience/control.py evidence

experience-verify: experience-sync experience-ia-check experience-route-check experience-task-check \
	@./scripts/run_if_available.sh experience-journey-check experience-handoff-check experience-dead-end-scan experience-test \
	@./scripts/run_if_available.sh experience-security-test experience-frontend-test experience-evidence-build
