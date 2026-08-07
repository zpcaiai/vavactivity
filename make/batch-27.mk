.PHONY: usability-migrate usability-seed usability-sync uat-scenario-check synthetic-data-test \
	demo-environment-test compatibility-test localization-qa draft-recovery-test notification-content-test \
	import-export-test uat-user-e2e uat-admin-e2e usability-security-test usability-evidence-build \
	functional-usability-verify

usability-migrate:
	docker compose exec -T api alembic upgrade head

usability-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_usability

usability-sync:
	uv run --package vav-platform-api python scripts/usability/control.py sync

uat-scenario-check:
	uv run --package vav-platform-api python scripts/usability/control.py uat-scenario

synthetic-data-test:
	uv run --package vav-platform-api python scripts/usability/control.py synthetic-data

demo-environment-test:
	uv run --package vav-platform-api python scripts/usability/control.py demo-environment

compatibility-test:
	uv run --package vav-platform-api python scripts/usability/control.py compatibility

localization-qa:
	uv run --package vav-platform-api python scripts/usability/control.py localization

draft-recovery-test:
	uv run --package vav-platform-api python scripts/usability/control.py draft-recovery

notification-content-test:
	uv run --package vav-platform-api python scripts/usability/control.py notification-content

import-export-test:
	uv run --package vav-platform-api python scripts/usability/control.py import-export

uat-user-e2e:
	uv run --package vav-platform-api python scripts/usability/control.py uat-user-e2e

uat-admin-e2e:
	uv run --package vav-platform-api python scripts/usability/control.py uat-admin-e2e

usability-security-test:
	uv run --package vav-platform-api python scripts/usability/control.py security

usability-evidence-build:
	uv run --package vav-platform-api python scripts/usability/control.py evidence

functional-usability-verify: usability-sync uat-scenario-check synthetic-data-test demo-environment-test \
	compatibility-test localization-qa draft-recovery-test notification-content-test import-export-test \
	uat-user-e2e uat-admin-e2e usability-security-test usability-evidence-build
	@:
