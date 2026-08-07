.PHONY: resilience-migrate resilience-seed resilience-sync slo-check error-budget-test observability-test synthetic-monitor-test \
	api-ha-test database-ha-test redis-worker-ha-test provider-resilience-test degradation-test resilience-security-test resilience-admin-e2e \
	resilience-evidence-build resilience-verify chaos-test backup-restore-test dr-game-day-test incident-management-test resilience-release

resilience-migrate:
	uv run --package vav-platform-api python scripts/resilience/control.py migrate

resilience-seed:
	uv run --package vav-platform-api python scripts/resilience/control.py seed

resilience-sync:
	uv run --package vav-platform-api python scripts/resilience/control.py sync

slo-check:
	uv run --package vav-platform-api python scripts/resilience/control.py slo-check

error-budget-test:
	uv run --package vav-platform-api python scripts/resilience/control.py error-budget-test

observability-test:
	uv run --package vav-platform-api python scripts/resilience/control.py observability-test

synthetic-monitor-test:
	uv run --package vav-platform-api python scripts/resilience/control.py synthetic-monitor-test

api-ha-test:
	uv run --package vav-platform-api python scripts/resilience/control.py api-ha-test

database-ha-test:
	uv run --package vav-platform-api python scripts/resilience/control.py database-ha-test

redis-worker-ha-test:
	uv run --package vav-platform-api python scripts/resilience/control.py redis-worker-ha-test

provider-resilience-test:
	uv run --package vav-platform-api python scripts/resilience/control.py provider-resilience-test

degradation-test:
	uv run --package vav-platform-api python scripts/resilience/control.py degradation-test

resilience-security-test:
	uv run --package vav-platform-api python scripts/resilience/control.py security-test

resilience-admin-e2e:
	uv run --package vav-platform-api python scripts/resilience/control.py admin-e2e

resilience-evidence-build:
	uv run --package vav-platform-api python scripts/resilience/control.py evidence

resilience-verify: resilience-migrate resilience-seed resilience-sync slo-check error-budget-test observability-test \
	synthetic-monitor-test api-ha-test database-ha-test redis-worker-ha-test provider-resilience-test degradation-test resilience-security-test \
	incident-management-test resilience-admin-e2e resilience-evidence-build

chaos-test:
	uv run --package vav-platform-api python scripts/resilience/control.py chaos-test

backup-restore-test:
	uv run --package vav-platform-api python scripts/resilience/control.py backup-restore-test

dr-game-day-test:
	uv run --package vav-platform-api python scripts/resilience/control.py dr-game-day-test

incident-management-test:
	uv run --package vav-platform-api python scripts/resilience/control.py incident-management-test

resilience-release: resilience-verify chaos-test backup-restore-test dr-game-day-test resilience-evidence-build
	@:
