.PHONY: quality-migrate quality-seed quality-sync quality-manifest-check quality-trace-check \
	quality-closure-check quality-gap-check quality-domain-test quality-test quality-gate-test \
	quality-security-test quality-concurrency-test quality-contract-test quality-gate-evaluate \
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

quality-domain-test:
	PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/unit -q

quality-contract-test:
	PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/integration -q

quality-concurrency-test:
	PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/concurrency -q

quality-test:
	PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/unit tests/quality/integration tests/quality/concurrency -q

quality-gate-test:
	PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/gates -q

quality-security-test:
	PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/security -q

quality-gate-evaluate:
	.venv/bin/python scripts/quality/evaluate_release_gate.py --self-check || true

quality-admin-e2e:
	corepack pnpm exec playwright test e2e/admin-quality

quality-evidence-build:
	PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py evidence-build

quality-release-report:
	PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py release-report

quality-verify: quality-migrate quality-seed quality-sync quality-manifest-check quality-trace-check \
	quality-closure-check quality-gap-check quality-test quality-gate-test quality-security-test \
	quality-admin-e2e quality-evidence-build quality-release-report
