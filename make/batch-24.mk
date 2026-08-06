.PHONY: process-migrate process-seed process-sync process-manifest-check process-state-machine-check \
	process-saga-test process-compensation-test process-concurrency-test process-stuck-test \
	process-simulation-test process-security-test process-admin-test process-admin-e2e \
	process-evidence-build process-verify

process-migrate:
	docker compose exec -T api alembic upgrade head

process-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_process_governance

process-sync:
	uv run --package vav-platform-api python scripts/process/control.py sync

process-manifest-check:
	uv run --package vav-platform-api python scripts/process/control.py manifest-check

process-state-machine-check:
	uv run --package vav-platform-api python scripts/process/control.py state-machine-check

process-saga-test:
	uv run --package vav-platform-api pytest services/api/tests/process_governance/unit services/api/tests/process_governance/integration --junitxml=build/process/backend-junit.xml -q

process-compensation-test:
	uv run --package vav-platform-api pytest services/api/tests/process_governance/integration -k 'stuck or step' -q

process-concurrency-test:
	uv run --package vav-platform-api pytest services/api/tests/process_governance/concurrency services/api/tests/process_governance/integration -k 'idempotency or cancellation or event' -q

process-stuck-test:
	uv run --package vav-platform-api pytest services/api/tests/process_governance/integration -k stuck -q

process-simulation-test:
	uv run --package vav-platform-api python scripts/process/control.py simulation-check
	uv run --package vav-platform-api pytest services/api/tests/process_governance/unit -k simulation -q

process-security-test:
	uv run --package vav-platform-api pytest services/api/tests/process_governance/security -q

process-admin-test:
	corepack pnpm --filter @vav/admin-web test
	corepack pnpm --filter @vav/admin-web build

process-admin-e2e:
	corepack pnpm exec playwright test e2e/process/process.admin.spec.ts

process-evidence-build:
	uv run --package vav-platform-api python scripts/process/control.py evidence

process-verify: process-sync process-manifest-check process-state-machine-check process-saga-test \
	process-compensation-test process-concurrency-test process-stuck-test process-simulation-test \
	process-security-test process-admin-test process-evidence-build
