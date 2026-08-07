.PHONY: process-migrate process-seed process-sync process-manifest-check process-state-machine-check \
	@./scripts/run_if_available.sh process-saga-test process-compensation-test process-concurrency-test process-stuck-test \
	@./scripts/run_if_available.sh process-simulation-test process-security-test process-admin-test process-admin-e2e \
	@./scripts/run_if_available.sh process-evidence-build process-verify

process-migrate:
	@./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

process-seed:
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_process_governance

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

process-admin-test:
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/admin-web test
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/admin-web build

process-admin-e2e:
	@./scripts/run_if_available.sh corepack pnpm exec playwright test e2e/process/process.admin.spec.ts

process-evidence-build:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/process/control.py evidence

process-verify: process-sync process-manifest-check process-state-machine-check process-saga-test \
	@./scripts/run_if_available.sh process-compensation-test process-concurrency-test process-stuck-test process-simulation-test \
	@./scripts/run_if_available.sh process-security-test process-admin-test process-evidence-build
