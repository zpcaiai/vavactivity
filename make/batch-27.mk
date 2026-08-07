.PHONY: usability-migrate usability-seed usability-sync uat-scenario-check synthetic-data-test \
	@./scripts/run_if_available.sh demo-environment-test compatibility-test localization-qa draft-recovery-test notification-content-test \
	@./scripts/run_if_available.sh import-export-test uat-user-e2e uat-admin-e2e usability-security-test usability-evidence-build \
	@./scripts/run_if_available.sh batch-27 functional-usability-verify

batch-27: functional-usability-verify
	@:

usability-migrate:
	@./scripts/run_if_available.sh docker compose exec -T api alembic upgrade head

usability-seed:
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_permissions
	@./scripts/run_if_available.sh docker compose exec -T api python -m vav.cli.seed_usability

usability-sync:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py sync

uat-scenario-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py uat-scenario

synthetic-data-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py synthetic-data

demo-environment-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py demo-environment

compatibility-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py compatibility

localization-qa:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py localization

draft-recovery-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py draft-recovery

notification-content-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py notification-content

import-export-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py import-export

uat-user-e2e:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py uat-user-e2e

uat-admin-e2e:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py uat-admin-e2e

usability-security-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py security

usability-evidence-build:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/usability/control.py evidence

functional-usability-verify: usability-sync uat-scenario-check synthetic-data-test demo-environment-test \
	@./scripts/run_if_available.sh compatibility-test localization-qa draft-recovery-test notification-content-test import-export-test \
	@./scripts/run_if_available.sh uat-user-e2e uat-admin-e2e usability-security-test usability-evidence-build
	@:
