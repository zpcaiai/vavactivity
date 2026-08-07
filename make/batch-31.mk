.PHONY: resilience-migrate resilience-seed resilience-sync slo-check error-budget-test observability-test synthetic-monitor-test \
	api-ha-test database-ha-test redis-worker-ha-test provider-resilience-test degradation-test resilience-security-test resilience-admin-e2e \
	resilience-evidence-build resilience-verify batch-31 chaos-test backup-restore-test dr-game-day-test incident-management-test resilience-release

batch-31: resilience-verify
	@:

resilience-migrate:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py migrate

resilience-seed:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py seed

resilience-sync:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py sync

slo-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py slo-check

error-budget-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py error-budget-test

observability-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py observability-test

synthetic-monitor-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py synthetic-monitor-test

api-ha-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py api-ha-test

database-ha-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py database-ha-test

redis-worker-ha-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py redis-worker-ha-test

provider-resilience-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py provider-resilience-test

degradation-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py degradation-test

resilience-security-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py security-test

resilience-admin-e2e:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py admin-e2e

resilience-evidence-build:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py evidence

resilience-verify: resilience-migrate resilience-seed resilience-sync slo-check error-budget-test observability-test \
	synthetic-monitor-test api-ha-test database-ha-test redis-worker-ha-test provider-resilience-test degradation-test resilience-security-test \
	incident-management-test resilience-admin-e2e resilience-evidence-build

chaos-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py chaos-test

backup-restore-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py backup-restore-test

dr-game-day-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py dr-game-day-test

incident-management-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/resilience/control.py incident-management-test

resilience-release: resilience-verify chaos-test backup-restore-test dr-game-day-test resilience-evidence-build
	@:
