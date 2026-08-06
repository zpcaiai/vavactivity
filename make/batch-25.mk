.PHONY: data-migrate data-seed data-sync data-contract-check data-lineage-check \
	data-event-contract-test data-quality-test data-reconciliation-test data-backfill-test \
	data-erasure-test data-security-test data-admin-test data-admin-e2e data-evidence-build \
	data-integrity-verify

data-migrate:
	docker compose exec -T api alembic upgrade head

data-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_data_governance

data-sync:
	uv run --package vav-platform-api python scripts/data/control.py sync

data-contract-check:
	uv run --package vav-platform-api python scripts/data/control.py contract-check

data-lineage-check:
	uv run --package vav-platform-api python scripts/data/control.py lineage-check

data-event-contract-test:
	uv run --package vav-platform-api pytest services/api/tests/data_governance/unit services/api/tests/data_governance/integration -k 'contract or event or inbox or outbox' --junitxml=build/data/backend-junit.xml -q

data-quality-test:
	uv run --package vav-platform-api python scripts/data/control.py quality-check
	uv run --package vav-platform-api pytest services/api/tests/data_governance/unit -k quality -q

data-reconciliation-test:
	uv run --package vav-platform-api pytest services/api/tests/data_governance/integration -k reconciliation -q

data-backfill-test:
	uv run --package vav-platform-api pytest services/api/tests/data_governance/integration services/api/tests/data_governance/concurrency -k backfill -q

data-erasure-test:
	uv run --package vav-platform-api pytest services/api/tests/data_governance/integration -k erasure -q

data-security-test:
	uv run --package vav-platform-api pytest services/api/tests/data_governance/security -q

data-admin-test:
	corepack pnpm --filter @vav/admin-web test
	corepack pnpm --filter @vav/admin-web build

data-admin-e2e:
	corepack pnpm exec playwright test e2e/data/data-governance.admin.spec.ts

data-evidence-build:
	uv run --package vav-platform-api python scripts/data/control.py evidence

data-integrity-verify: data-sync data-contract-check data-lineage-check data-event-contract-test \
	data-quality-test data-reconciliation-test data-backfill-test data-erasure-test \
	data-security-test data-admin-test data-evidence-build
