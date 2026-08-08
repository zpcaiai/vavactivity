.PHONY: batch-24 process-migrate process-seed process-sync process-manifest-check process-state-machine-check \
	process-saga-test process-compensation-test process-concurrency-test process-stuck-test \
	process-simulation-test process-security-test process-backend-test process-admin-test process-admin-e2e \
	process-evidence-build process-verify

batch-24: process-verify

process-migrate:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/process/migration-status.json ./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

process-seed:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/process/permissions-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/process/domain-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_process_governance

process-sync:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/process/control.py sync

process-manifest-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/process/control.py manifest-check

process-state-machine-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/process/control.py state-machine-check

process-saga-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/process_governance/unit services/api/tests/process_governance/integration --junitxml=build/process/backend-junit.xml -q

process-compensation-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/process_governance/integration -k 'stuck or step' -q

process-concurrency-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/process_governance/concurrency services/api/tests/process_governance/integration -k 'idempotency or cancellation or event' -q

process-stuck-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/process_governance/integration -k stuck -q

process-simulation-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/process/control.py simulation-check
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/process_governance/unit -k simulation -q

process-security-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/process_governance/security -q

process-backend-test: process-migrate process-seed
	@mkdir -p build/process
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/process/backend-test-status.json ./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/process_governance --junitxml=build/process/backend-junit.xml -q

process-admin-test: shared-admin-web-verify

process-admin-e2e: process-migrate process-seed
	@mkdir -p build/process
	@RUN_IF_TIMEOUT_SECONDS=600 RUN_IF_STATUS_FILE=build/process/admin-e2e-status.json ./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost PLAYWRIGHT_HTML_OUTPUT_DIR=build/process/playwright-report corepack pnpm exec playwright test e2e/process/process.admin.spec.ts --output=build/process/playwright-results

process-evidence-build: process-migrate process-seed process-backend-test process-admin-test process-admin-e2e
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/process/control.py evidence

process-verify: process-migrate process-seed process-sync process-manifest-check process-state-machine-check \
	process-backend-test process-simulation-test \
	process-security-test process-admin-test process-admin-e2e process-evidence-build
