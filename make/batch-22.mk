.PHONY: ui-seed ui-token-build ui-token-check ui-component-test ui-storybook-build ui-storybook-test \
	ui-accessibility-test ui-responsive-test ui-visual-test ui-page-audit ui-admin-e2e \
	ui-evidence-build ui-verify

ui-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_design_system

ui-token-build:
	corepack pnpm --filter @vav/design-tokens build

ui-token-check: ui-token-build
	uv run --package vav-platform-api python scripts/ui/control.py token-check

ui-component-test:
	corepack pnpm --filter @vav/ui-core --filter @vav/ui-user --filter @vav/ui-admin --filter @vav/ui-icons --filter @vav/ui-testing test
	corepack pnpm --filter @vav/ui-core --filter @vav/ui-user --filter @vav/ui-admin --filter @vav/ui-testing typecheck

ui-storybook-build:
	corepack pnpm --filter @vav/design-system storybook:build
	node scripts/ui/write_playwright_evidence.mjs storybook apps/design-system/storybook-static/index.json

ui-storybook-test:
	corepack pnpm --filter @vav/design-system test
	corepack pnpm --filter @vav/design-system build
	NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.storybook.config.ts
	node scripts/ui/write_playwright_evidence.mjs storybook build/ui/storybook-playwright-report/index.html

ui-accessibility-test:
	NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.ui.config.ts accessibility.spec.ts
	node scripts/ui/write_playwright_evidence.mjs accessibility build/ui/playwright-report/index.html

ui-responsive-test:
	NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.ui.config.ts responsive.spec.ts
	node scripts/ui/write_playwright_evidence.mjs responsive build/ui/playwright-report/index.html

ui-visual-test:
	NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.ui.config.ts visual.spec.ts
	node scripts/ui/write_playwright_evidence.mjs visual build/ui/playwright-report/index.html

ui-page-audit:
	uv run --package vav-platform-api python scripts/ui/control.py page-audit

ui-admin-e2e:
	corepack pnpm --filter @vav/admin-web test
	corepack pnpm --filter @vav/admin-web build

ui-evidence-build:
	uv run --package vav-platform-api python scripts/ui/control.py evidence

ui-verify: ui-token-check ui-component-test ui-storybook-build ui-storybook-test ui-accessibility-test ui-responsive-test ui-visual-test ui-page-audit ui-admin-e2e ui-evidence-build
