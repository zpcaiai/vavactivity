.PHONY: admin-platform-migrate admin-platform-seed admin-platform-sync admin-capability-check \
	admin-masking-test admin-approval-test admin-bulk-test admin-exception-test \
	admin-security-test admin-platform-test admin-platform-e2e admin-evidence-build admin-completeness-verify

admin-platform-migrate:
	@./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

admin-platform-seed:
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_admin_platform

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

admin-platform-test:
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/admin-web test
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/admin-web build

admin-platform-e2e:
	@./scripts/run_if_available.sh corepack pnpm exec playwright test e2e/admin-platform

admin-evidence-build:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/admin/control.py evidence

admin-completeness-verify: admin-platform-sync admin-capability-check admin-masking-test \
	admin-approval-test admin-bulk-test admin-exception-test admin-security-test admin-platform-test admin-evidence-build
