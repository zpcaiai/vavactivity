.PHONY: performance-migrate performance-seed performance-sync performance-workload-check performance-budget-check \
	@./scripts/run_if_available.sh performance-concurrency-test performance-baseline performance-load performance-spike performance-stress \
	@./scripts/run_if_available.sh performance-soak performance-database-test performance-cache-test performance-queue-test performance-scaling-test \
	@./scripts/run_if_available.sh performance-cost-report performance-security-test performance-admin-e2e performance-evidence-build performance-verify \
	@./scripts/run_if_available.sh performance-release batch-29

batch-29: performance-release
	@:

performance-migrate:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py migrate

performance-seed:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py seed

performance-sync:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py sync

performance-workload-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py workload-check

performance-budget-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py budget-check

performance-concurrency-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py concurrency-test

performance-baseline:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py baseline

performance-load:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py load-test

performance-spike:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py spike-test

performance-stress:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py stress-test

performance-soak:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py soak-test

performance-database-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py database-test

performance-cache-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py cache-test

performance-queue-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py queue-test

performance-scaling-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py scaling-test

performance-cost-report:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py cost-report

performance-security-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py security-test

performance-admin-e2e:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py admin-e2e

performance-evidence-build:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/performance/control.py evidence

performance-verify: performance-migrate performance-seed performance-sync performance-workload-check performance-budget-check \
	@./scripts/run_if_available.sh performance-concurrency-test performance-baseline performance-load performance-spike performance-database-test \
	@./scripts/run_if_available.sh performance-cache-test performance-queue-test performance-scaling-test performance-security-test performance-admin-e2e \
	@./scripts/run_if_available.sh performance-cost-report performance-evidence-build

performance-release: performance-verify performance-soak
