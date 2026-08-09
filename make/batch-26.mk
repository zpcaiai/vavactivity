.PHONY: batch-26 admin-platform-migrate admin-platform-seed admin-platform-sync admin-capability-check \
	admin-masking-test admin-approval-test admin-bulk-test admin-exception-test \
	admin-security-test admin-backend-test admin-platform-test admin-platform-e2e admin-evidence-build admin-completeness-verify

batch-26: admin-completeness-verify

admin-platform-migrate:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/admin/migration-status.json ./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

admin-platform-seed:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/admin/permissions-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/admin/domain-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_admin_platform

admin-platform-sync:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/admin/control.py sync

admin-capability-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/admin/control.py capability-check

admin-masking-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/admin_platform/unit services/api/tests/admin_platform/integration -k 'mask or reveal or entity' -q

admin-approval-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/admin_platform/integration -k 'approval or configuration' -q

admin-bulk-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/admin_platform/integration -k bulk -q

admin-exception-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/admin_platform/integration -k exception -q

admin-security-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/admin_platform/security -q

admin-backend-test: admin-platform-migrate admin-platform-seed
	@mkdir -p build/admin
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/admin/backend-test-status.json ./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/admin_platform --junitxml=build/admin/backend-junit.xml -q

admin-platform-test: shared-admin-web-verify

admin-platform-e2e: admin-platform-migrate admin-platform-seed
	@mkdir -p build/admin
	@RUN_IF_TIMEOUT_SECONDS=600 RUN_IF_STATUS_FILE=build/admin/browser-e2e-status.json ./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost PLAYWRIGHT_HTML_OUTPUT_DIR=build/admin/playwright-report ./scripts/web-pnpm exec playwright test e2e/admin-platform --output=build/admin/playwright-results

admin-evidence-build: admin-platform-migrate admin-platform-seed admin-backend-test admin-platform-test admin-platform-e2e
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/admin/control.py evidence

admin-completeness-verify: admin-platform-migrate admin-platform-seed admin-platform-sync admin-capability-check \
	admin-backend-test admin-security-test admin-platform-test admin-platform-e2e admin-evidence-build
