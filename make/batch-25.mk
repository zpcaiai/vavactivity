.PHONY: batch-25 data-migrate data-seed data-sync data-contract-check data-lineage-check \
	data-event-contract-test data-quality-test data-reconciliation-test data-backfill-test \
	data-erasure-test data-security-test data-backend-test data-admin-test data-admin-e2e data-evidence-build \
	data-integrity-verify

batch-25: data-integrity-verify

data-migrate:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/data/migration-status.json ./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

data-seed:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/data/permissions-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/data/domain-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_data_governance

data-sync:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/data/control.py sync

data-contract-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/data/control.py contract-check

data-lineage-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/data/control.py lineage-check

data-event-contract-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/data_governance/unit services/api/tests/data_governance/integration -k 'contract or event or inbox or outbox' --junitxml=build/data/backend-junit.xml -q

data-quality-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/data/control.py quality-check
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/data_governance/unit -k quality -q

data-reconciliation-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/data_governance/integration -k reconciliation -q

data-backfill-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/data_governance/integration services/api/tests/data_governance/concurrency -k backfill -q

data-erasure-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/data_governance/integration -k erasure -q

data-security-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/data_governance/security -q

data-backend-test: data-migrate data-seed
	@mkdir -p build/data
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/data/backend-test-status.json ./scripts/run_if_available.sh uv run --package vav-platform-api pytest services/api/tests/data_governance --junitxml=build/data/backend-junit.xml -q

data-admin-test: shared-admin-web-verify

data-admin-e2e: data-migrate data-seed
	@mkdir -p build/data
	@RUN_IF_TIMEOUT_SECONDS=600 RUN_IF_STATUS_FILE=build/data/admin-e2e-status.json ./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost PLAYWRIGHT_HTML_OUTPUT_DIR=build/data/playwright-report ./scripts/web-pnpm exec playwright test e2e/data/data-governance.admin.spec.ts --output=build/data/playwright-results

data-evidence-build: data-migrate data-seed data-backend-test data-admin-test data-admin-e2e
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/data/control.py evidence

data-integrity-verify: data-migrate data-seed data-sync data-contract-check data-lineage-check \
	data-quality-test data-backend-test \
	data-security-test data-admin-test data-admin-e2e data-evidence-build
