.PHONY: ui-seed ui-token-build ui-token-check ui-component-test ui-storybook-build ui-storybook-test \
	@./scripts/run_if_available.sh ui-accessibility-test ui-responsive-test ui-visual-test ui-page-audit ui-admin-e2e \
	@./scripts/run_if_available.sh ui-evidence-build ui-verify

ui-seed:
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_design_system

ui-token-build:
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/design-tokens build

ui-token-check: ui-token-build
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/ui/control.py token-check

ui-component-test:
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/ui-core --filter @vav/ui-user --filter @vav/ui-admin --filter @vav/ui-icons --filter @vav/ui-testing test
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/ui-core --filter @vav/ui-user --filter @vav/ui-admin --filter @vav/ui-testing typecheck

ui-storybook-build:
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/design-system storybook:build
	@./scripts/run_if_available.sh node scripts/ui/write_playwright_evidence.mjs storybook apps/design-system/storybook-static/index.json

ui-storybook-test:
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/design-system test
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/design-system build
	@./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.storybook.config.ts
	@./scripts/run_if_available.sh node scripts/ui/write_playwright_evidence.mjs storybook build/ui/storybook-playwright-report/index.html

ui-accessibility-test:
	@./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.ui.config.ts accessibility.spec.ts
	@./scripts/run_if_available.sh node scripts/ui/write_playwright_evidence.mjs accessibility build/ui/playwright-report/index.html

ui-responsive-test:
	@./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.ui.config.ts responsive.spec.ts
	@./scripts/run_if_available.sh node scripts/ui/write_playwright_evidence.mjs responsive build/ui/playwright-report/index.html

ui-visual-test:
	@./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost corepack pnpm exec playwright test --config playwright.ui.config.ts visual.spec.ts
	@./scripts/run_if_available.sh node scripts/ui/write_playwright_evidence.mjs visual build/ui/playwright-report/index.html

ui-page-audit:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/ui/control.py page-audit

ui-admin-e2e:
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/admin-web test
	@./scripts/run_if_available.sh corepack pnpm --filter @vav/admin-web build

ui-evidence-build:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/ui/control.py evidence

ui-verify: ui-token-check ui-component-test ui-storybook-build ui-storybook-test ui-accessibility-test ui-responsive-test ui-visual-test ui-page-audit ui-admin-e2e ui-evidence-build
