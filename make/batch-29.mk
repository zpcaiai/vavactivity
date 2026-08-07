.PHONY: performance-migrate performance-seed performance-sync performance-workload-check performance-budget-check \
	performance-concurrency-test performance-baseline performance-load performance-spike performance-stress \
	performance-soak performance-database-test performance-cache-test performance-queue-test performance-scaling-test \
	performance-cost-report performance-security-test performance-admin-e2e performance-evidence-build performance-verify \
	performance-release

performance-migrate:
	uv run --package vav-platform-api python scripts/performance/control.py migrate

performance-seed:
	uv run --package vav-platform-api python scripts/performance/control.py seed

performance-sync:
	uv run --package vav-platform-api python scripts/performance/control.py sync

performance-workload-check:
	uv run --package vav-platform-api python scripts/performance/control.py workload-check

performance-budget-check:
	uv run --package vav-platform-api python scripts/performance/control.py budget-check

performance-concurrency-test:
	uv run --package vav-platform-api python scripts/performance/control.py concurrency-test

performance-baseline:
	uv run --package vav-platform-api python scripts/performance/control.py baseline

performance-load:
	uv run --package vav-platform-api python scripts/performance/control.py load-test

performance-spike:
	uv run --package vav-platform-api python scripts/performance/control.py spike-test

performance-stress:
	uv run --package vav-platform-api python scripts/performance/control.py stress-test

performance-soak:
	uv run --package vav-platform-api python scripts/performance/control.py soak-test

performance-database-test:
	uv run --package vav-platform-api python scripts/performance/control.py database-test

performance-cache-test:
	uv run --package vav-platform-api python scripts/performance/control.py cache-test

performance-queue-test:
	uv run --package vav-platform-api python scripts/performance/control.py queue-test

performance-scaling-test:
	uv run --package vav-platform-api python scripts/performance/control.py scaling-test

performance-cost-report:
	uv run --package vav-platform-api python scripts/performance/control.py cost-report

performance-security-test:
	uv run --package vav-platform-api python scripts/performance/control.py security-test

performance-admin-e2e:
	uv run --package vav-platform-api python scripts/performance/control.py admin-e2e

performance-evidence-build:
	uv run --package vav-platform-api python scripts/performance/control.py evidence

performance-verify: performance-migrate performance-seed performance-sync performance-workload-check performance-budget-check \
	performance-concurrency-test performance-baseline performance-load performance-spike performance-database-test \
	performance-cache-test performance-queue-test performance-scaling-test performance-security-test performance-admin-e2e \
	performance-cost-report performance-evidence-build

performance-release: performance-verify performance-soak
