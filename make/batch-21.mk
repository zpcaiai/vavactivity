.PHONY: quality-migrate quality-seed quality-sync quality-manifest-check quality-trace-check \
	quality-closure-check quality-gap-check quality-test quality-gate-test quality-security-test \
	quality-admin-e2e quality-evidence-build quality-release-report quality-verify

quality-migrate:
	docker compose exec -T api alembic upgrade head

quality-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_quality

quality-sync:
	PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py sync

quality-manifest-check:
	PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py manifest-check

quality-trace-check:
	PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py trace-check

quality-closure-check:
	PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py closure-check

quality-gap-check:
	PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py gap-check

quality-test:
	docker compose exec -T api pytest tests/quality/unit tests/quality/integration tests/quality/concurrency -q

quality-gate-test:
	docker compose exec -T api pytest tests/quality/gates -q

quality-security-test:
	docker compose exec -T api pytest tests/quality/security -q

quality-admin-e2e:
	corepack pnpm exec playwright test e2e/admin-quality

quality-evidence-build:
	PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py evidence-build

quality-release-report:
	PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py release-report

quality-verify: quality-migrate quality-seed quality-sync quality-manifest-check quality-trace-check \
	quality-closure-check quality-gap-check quality-test quality-gate-test quality-security-test \
	quality-admin-e2e quality-evidence-build quality-release-report
