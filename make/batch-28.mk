.PHONY: regression-migrate regression-seed regression-sync regression-registry-check regression-pyramid-check \
	regression-contract-test regression-integration-test regression-model-test regression-property-test \
	regression-visual-test regression-mutation-test regression-flaky-test regression-isolation-test \
	regression-impact-test regression-critical regression-full regression-admin-e2e regression-evidence-build \
	regression-verify regression-release

regression-migrate:
	uv run --package vav-platform-api python scripts/regression/control.py migrate

regression-seed:
	uv run --package vav-platform-api python scripts/regression/control.py seed

regression-sync:
	uv run --package vav-platform-api python scripts/regression/control.py sync

regression-registry-check:
	uv run --package vav-platform-api python scripts/regression/control.py registry-check

regression-pyramid-check:
	uv run --package vav-platform-api python scripts/regression/control.py pyramid-check

regression-contract-test:
	uv run --package vav-platform-api python scripts/regression/control.py contract-check

regression-integration-test:
	uv run --package vav-platform-api python scripts/regression/control.py integration-test

regression-model-test:
	uv run --package vav-platform-api python scripts/regression/control.py model-test

regression-property-test:
	uv run --package vav-platform-api python scripts/regression/control.py property-test

regression-visual-test:
	uv run --package vav-platform-api python scripts/regression/control.py visual-test

regression-mutation-test:
	uv run --package vav-platform-api python scripts/regression/control.py mutation-test

regression-flaky-test:
	uv run --package vav-platform-api python scripts/regression/control.py flaky-test

regression-isolation-test:
	uv run --package vav-platform-api python scripts/regression/control.py isolation-test

regression-impact-test:
	uv run --package vav-platform-api python scripts/regression/control.py impact-test

regression-critical:
	uv run --package vav-platform-api python scripts/regression/control.py critical

regression-full:
	uv run --package vav-platform-api python scripts/regression/control.py full

regression-admin-e2e:
	uv run --package vav-platform-api python scripts/regression/control.py admin-e2e

regression-evidence-build:
	uv run --package vav-platform-api python scripts/regression/control.py evidence

regression-verify: regression-migrate regression-seed regression-sync regression-registry-check \
	regression-pyramid-check regression-contract-test regression-integration-test regression-model-test \
	regression-property-test regression-visual-test regression-flaky-test regression-isolation-test \
	regression-impact-test regression-critical regression-admin-e2e regression-evidence-build

regression-release: regression-full regression-mutation-test regression-evidence-build
	@:
