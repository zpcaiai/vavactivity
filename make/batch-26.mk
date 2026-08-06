.PHONY: admin-platform-migrate admin-platform-seed admin-platform-sync admin-capability-check \
	admin-masking-test admin-approval-test admin-bulk-test admin-exception-test \
	admin-security-test admin-platform-test admin-platform-e2e admin-evidence-build admin-completeness-verify

admin-platform-migrate:
	docker compose exec -T api alembic upgrade head

admin-platform-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_admin_platform

admin-platform-sync:
	uv run --package vav-platform-api python scripts/admin/control.py sync

admin-capability-check:
	uv run --package vav-platform-api python scripts/admin/control.py capability-check

admin-masking-test:
	uv run --package vav-platform-api pytest services/api/tests/admin_platform/unit services/api/tests/admin_platform/integration -k 'mask or reveal or entity' -q

admin-approval-test:
	uv run --package vav-platform-api pytest services/api/tests/admin_platform/integration -k 'approval or configuration' -q

admin-bulk-test:
	uv run --package vav-platform-api pytest services/api/tests/admin_platform/integration -k bulk -q

admin-exception-test:
	uv run --package vav-platform-api pytest services/api/tests/admin_platform/integration -k exception -q

admin-security-test:
	uv run --package vav-platform-api pytest services/api/tests/admin_platform/security -q

admin-platform-test:
	corepack pnpm --filter @vav/admin-web test
	corepack pnpm --filter @vav/admin-web build

admin-platform-e2e:
	corepack pnpm exec playwright test e2e/admin-platform

admin-evidence-build:
	uv run --package vav-platform-api python scripts/admin/control.py evidence

admin-completeness-verify: admin-platform-sync admin-capability-check admin-masking-test \
	admin-approval-test admin-bulk-test admin-exception-test admin-security-test admin-platform-test admin-evidence-build
