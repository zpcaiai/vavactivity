.PHONY: batch-21 quality-migrate quality-seed quality-sync quality-manifest-check quality-trace-check \
	quality-closure-check quality-gap-check quality-domain-test quality-test quality-gate-test \
	quality-security-test quality-concurrency-test quality-contract-test quality-gate-evaluate \
	quality-admin-e2e quality-evidence-build quality-release-report quality-verify

batch-21: quality-verify

quality-migrate:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/quality/migration-status.json ./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

quality-seed:
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/quality/permissions-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/quality/domain-seed-status.json ./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_quality

quality-sync:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py sync

quality-manifest-check:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py manifest-check

quality-trace-check:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py trace-check

quality-closure-check:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py closure-check

quality-gap-check:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py gap-check

quality-domain-test:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/unit -q

quality-contract-test:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/integration -q

quality-concurrency-test:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/concurrency -q

quality-test: quality-migrate quality-seed
	@mkdir -p build/quality
	@RUN_IF_TIMEOUT_SECONDS=300 RUN_IF_STATUS_FILE=build/quality/backend-test-status.json ./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/unit tests/quality/integration tests/quality/concurrency --junitxml=build/quality/backend-junit.xml -q

quality-gate-test:
	@mkdir -p build/quality
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/quality/gate-test-status.json ./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/gates --junitxml=build/quality/gate-junit.xml -q

quality-security-test:
	@mkdir -p build/quality
	@RUN_IF_TIMEOUT_SECONDS=180 RUN_IF_STATUS_FILE=build/quality/security-test-status.json ./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/security --junitxml=build/quality/security-junit.xml -q

quality-gate-evaluate:
	@./scripts/run_if_available.sh .venv/bin/python scripts/quality/evaluate_release_gate.py --self-check --expect-decision no_go

quality-admin-e2e: quality-migrate quality-seed
	@mkdir -p build/quality
	@RUN_IF_TIMEOUT_SECONDS=600 RUN_IF_STATUS_FILE=build/quality/admin-e2e-status.json ./scripts/run_if_available.sh NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost PLAYWRIGHT_HTML_OUTPUT_DIR=build/quality/playwright-report corepack pnpm exec playwright test e2e/admin-quality --output=build/quality/playwright-results

quality-evidence-build: quality-migrate quality-seed quality-test quality-gate-test quality-security-test quality-admin-e2e
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py evidence-build

quality-release-report: quality-evidence-build
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py release-report

quality-verify: quality-migrate quality-seed quality-sync quality-manifest-check quality-trace-check \
	quality-closure-check quality-gap-check quality-test quality-gate-test quality-security-test quality-gate-evaluate \
	quality-admin-e2e quality-evidence-build quality-release-report
