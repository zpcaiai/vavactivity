.PHONY: batch-23 experience-migrate experience-seed experience-sync experience-ia-check experience-route-check \
	experience-task-check experience-journey-check experience-handoff-check experience-search-test \
	experience-dead-end-scan experience-test experience-security-test experience-user-e2e \
	experience-admin-e2e experience-evidence-build experience-frontend-test experience-verify

batch-23: experience-verify

experience-migrate:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/experience/migration-status.json ./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

experience-seed:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/experience/permissions-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/experience/domain-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_experience

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

experience-test: experience-migrate experience-seed
	@mkdir -p build/experience
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/experience/backend-test-status.json ./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/experience/unit services/api/tests/experience/integration services/api/tests/experience/concurrency --junitxml=build/experience/backend-junit.xml -q

experience-security-test: experience-migrate experience-seed
	@mkdir -p build/experience
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/experience/security-test-status.json ./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/experience/security --junitxml=build/experience/security-junit.xml -q

experience-frontend-test:
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/experience/packages-test-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/navigation-contracts --filter @vav/journey-contracts --filter @vav/experience-components --filter @vav/search-components --filter @vav/help-components test
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/experience/packages-typecheck-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/navigation-contracts --filter @vav/journey-contracts --filter @vav/experience-components --filter @vav/search-components --filter @vav/help-components typecheck
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/experience/apps-test-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/user-web --filter @vav/admin-web test
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/experience/apps-build-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/user-web --filter @vav/admin-web build

experience-user-e2e: experience-migrate experience-seed
	@mkdir -p build/experience
	@RUN_IF_TIMEOUT_SECONDS=600 RUN_IF_STATUS_FILE=build/experience/user-e2e-status.json ./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost PLAYWRIGHT_HTML_OUTPUT_DIR=build/experience/user-playwright-report corepack pnpm exec playwright test e2e/experience/experience.user.spec.ts --output=build/experience/user-playwright-results

experience-admin-e2e: experience-migrate experience-seed
	@mkdir -p build/experience
	@RUN_IF_TIMEOUT_SECONDS=600 RUN_IF_STATUS_FILE=build/experience/admin-e2e-status.json ./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost PLAYWRIGHT_HTML_OUTPUT_DIR=build/experience/admin-playwright-report corepack pnpm exec playwright test e2e/experience/experience.admin.spec.ts --output=build/experience/admin-playwright-results

experience-evidence-build: experience-migrate experience-seed experience-test experience-security-test experience-frontend-test experience-user-e2e experience-admin-e2e
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/experience/control.py evidence

experience-verify: experience-migrate experience-seed experience-sync experience-ia-check experience-route-check experience-task-check \
	experience-journey-check experience-handoff-check experience-dead-end-scan experience-test \
	experience-security-test experience-frontend-test experience-user-e2e experience-admin-e2e experience-evidence-build
