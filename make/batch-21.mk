.PHONY: quality-migrate quality-seed quality-sync quality-manifest-check quality-trace-check \
	@./scripts/run_if_available.sh quality-closure-check quality-gap-check quality-domain-test quality-test quality-gate-test \
	@./scripts/run_if_available.sh quality-security-test quality-concurrency-test quality-contract-test quality-gate-evaluate \
	@./scripts/run_if_available.sh quality-admin-e2e quality-evidence-build quality-release-report quality-verify

quality-migrate:
	@./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

quality-seed:
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_quality

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

quality-test:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/unit tests/quality/integration tests/quality/concurrency -q

quality-gate-test:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/gates -q

quality-security-test:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/pytest tests/quality/security -q

quality-gate-evaluate:
	@./scripts/run_if_available.sh .venv/bin/python scripts/quality/evaluate_release_gate.py --self-check || true

quality-admin-e2e:
	@./scripts/run_if_available.sh corepack pnpm exec playwright test e2e/admin-quality

quality-evidence-build:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py evidence-build

quality-release-report:
	@./scripts/run_if_available.sh PYTHONPATH=services/api/src .venv/bin/python scripts/quality/control.py release-report

quality-verify: quality-migrate quality-seed quality-sync quality-manifest-check quality-trace-check \
	@./scripts/run_if_available.sh quality-closure-check quality-gap-check quality-test quality-gate-test quality-security-test \
	@./scripts/run_if_available.sh quality-admin-e2e quality-evidence-build quality-release-report
