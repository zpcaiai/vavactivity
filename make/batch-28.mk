.PHONY: regression-migrate regression-seed regression-sync regression-registry-check regression-pyramid-check \
	regression-contract-test regression-integration-test regression-model-test regression-property-test \
	regression-visual-test regression-mutation-test regression-flaky-test regression-isolation-test \
	regression-impact-test regression-critical regression-full regression-admin-e2e regression-evidence-build \
	regression-verify regression-release batch-28

batch-28: regression-release
	@:

regression-migrate:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py migrate

regression-seed:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py seed

regression-sync:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py sync

regression-registry-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py registry-check

regression-pyramid-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py pyramid-check

regression-contract-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py contract-check

regression-integration-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py integration-test

regression-model-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py model-test

regression-property-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py property-test

regression-visual-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py visual-test

regression-mutation-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py mutation-test

regression-flaky-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py flaky-test

regression-isolation-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py isolation-test

regression-impact-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py impact-test

regression-critical:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py critical

regression-full:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py full

regression-admin-e2e:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py admin-e2e

regression-evidence-build:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/regression/control.py evidence

regression-verify: regression-migrate regression-seed regression-sync regression-registry-check \
	regression-pyramid-check regression-contract-test regression-integration-test regression-model-test \
	regression-property-test regression-visual-test regression-flaky-test regression-isolation-test \
	regression-impact-test regression-critical regression-admin-e2e regression-evidence-build

regression-release: regression-full regression-mutation-test regression-evidence-build
	@:
