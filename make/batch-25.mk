.PHONY: data-migrate data-seed data-sync data-contract-check data-lineage-check \
	@./scripts/run_if_available.sh data-event-contract-test data-quality-test data-reconciliation-test data-backfill-test \
	@./scripts/run_if_available.sh data-erasure-test data-security-test data-admin-test data-admin-e2e data-evidence-build \
	@./scripts/run_if_available.sh data-integrity-verify

data-migrate:
	@./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

data-seed:
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_data_governance

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

data-admin-test:
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/admin-web test
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/admin-web build

data-admin-e2e:
	@./scripts/run_if_available.sh corepack pnpm exec playwright test e2e/data/data-governance.admin.spec.ts

data-evidence-build:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/data/control.py evidence

data-integrity-verify: data-sync data-contract-check data-lineage-check data-event-contract-test \
	@./scripts/run_if_available.sh data-quality-test data-reconciliation-test data-backfill-test data-erasure-test \
	@./scripts/run_if_available.sh data-security-test data-admin-test data-evidence-build
