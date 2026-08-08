.PHONY: batch-22 shared-admin-web-verify ui-migrate ui-seed ui-token-build ui-token-check ui-component-test ui-storybook-build ui-storybook-test \
	ui-accessibility-test ui-responsive-test ui-visual-test ui-page-audit ui-admin-e2e \
	ui-evidence-build ui-verify

batch-22: ui-verify

ui-migrate:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/ui/migration-status.json ./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

ui-seed:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/ui/permissions-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/ui/domain-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_design_system

ui-token-build:
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/design-tokens build

ui-token-check: ui-token-build
	@RUN_IF_STATUS_FILE=build/ui/token-check-status.json ./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/ui/control.py token-check

ui-component-test:
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/ui/component-test-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/ui-core --filter @vav/ui-user --filter @vav/ui-admin --filter @vav/ui-icons --filter @vav/ui-testing test
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/ui/component-typecheck-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/ui-core --filter @vav/ui-user --filter @vav/ui-admin --filter @vav/ui-testing typecheck

ui-storybook-build:
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/ui/storybook-build-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/design-system storybook:build
	@./scripts/run_if_available.sh node scripts/ui/write_playwright_evidence.mjs storybook apps/design-system/storybook-static/index.json build/ui/storybook-build-status.json

ui-storybook-test:
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/ui/storybook-test-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/design-system test
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/ui/storybook-app-build-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/design-system build
	@RUN_IF_TIMEOUT_SECONDS=600 RUN_IF_STATUS_FILE=build/ui/storybook-browser-status.json ./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.storybook.config.ts
	@./scripts/run_if_available.sh node scripts/ui/write_playwright_evidence.mjs storybook build/ui/storybook-playwright-report/index.html build/ui/storybook-browser-status.json

ui-accessibility-test:
	@RUN_IF_TIMEOUT_SECONDS=600 RUN_IF_STATUS_FILE=build/ui/accessibility-test-status.json ./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.ui.config.ts accessibility.spec.ts
	@./scripts/run_if_available.sh node scripts/ui/write_playwright_evidence.mjs accessibility build/ui/playwright-report/index.html build/ui/accessibility-test-status.json

ui-responsive-test:
	@RUN_IF_TIMEOUT_SECONDS=600 RUN_IF_STATUS_FILE=build/ui/responsive-test-status.json ./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.ui.config.ts responsive.spec.ts
	@./scripts/run_if_available.sh node scripts/ui/write_playwright_evidence.mjs responsive build/ui/playwright-report/index.html build/ui/responsive-test-status.json

ui-visual-test:
	@RUN_IF_TIMEOUT_SECONDS=600 RUN_IF_STATUS_FILE=build/ui/visual-test-status.json ./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.ui.config.ts visual.spec.ts
	@./scripts/run_if_available.sh node scripts/ui/write_playwright_evidence.mjs visual build/ui/playwright-report/index.html build/ui/visual-test-status.json

ui-page-audit:
	@RUN_IF_STATUS_FILE=build/ui/page-audit-status.json ./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/ui/control.py page-audit

shared-admin-web-verify:
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/shared/admin-web-test-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/admin-web test
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/shared/admin-web-build-status.json ./scripts/run_if_available.sh corepack pnpm --filter @vav/admin-web build

ui-admin-e2e: shared-admin-web-verify

ui-evidence-build: ui-migrate ui-seed ui-token-check ui-component-test ui-storybook-build ui-storybook-test ui-accessibility-test ui-responsive-test ui-visual-test ui-page-audit ui-admin-e2e
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/ui/control.py evidence

ui-verify: ui-migrate ui-seed ui-token-check ui-component-test ui-storybook-build ui-storybook-test ui-accessibility-test ui-responsive-test ui-visual-test ui-page-audit ui-admin-e2e ui-evidence-build
