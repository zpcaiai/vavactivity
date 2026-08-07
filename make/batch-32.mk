.PHONY: final-migrate final-seed final-sync final-release-manifest-check final-score-test final-go-no-go-test final-approval-test final-launch-test \
	final-observation-policy-test final-evidence-test final-security-test final-admin-e2e final-evidence-build \
	final-preproduction-verify production-observation-24h-evaluate production-observation-7d-evaluate production-observation-30d-evaluate \
	final-release-candidate

batch-32: final-release-candidate
	@:

final-migrate:
	uv run --package vav-platform-api python scripts/final/control.py migrate

final-seed:
	uv run --package vav-platform-api python scripts/final/control.py seed

final-sync:
	uv run --package vav-platform-api python scripts/final/control.py sync

final-release-manifest-check:
	uv run --package vav-platform-api python scripts/final/control.py release-manifest-check

final-score-test:
	uv run --package vav-platform-api python scripts/final/control.py score-test

final-go-no-go-test:
	uv run --package vav-platform-api python scripts/final/control.py go-no-go-test

final-approval-test:
	uv run --package vav-platform-api python scripts/final/control.py approval-test

final-launch-test:
	uv run --package vav-platform-api python scripts/final/control.py launch-test

final-observation-policy-test:
	uv run --package vav-platform-api python scripts/final/control.py observation-policy-test

final-evidence-test:
	uv run --package vav-platform-api python scripts/final/control.py evidence-test

final-security-test:
	uv run --package vav-platform-api python scripts/final/control.py security-test

final-admin-e2e:
	uv run --package vav-platform-api python scripts/final/control.py admin-e2e

final-evidence-build:
	uv run --package vav-platform-api python scripts/final/control.py evidence

production-observation-24h-evaluate:
	uv run --package vav-platform-api python scripts/final/control.py observe-24h

production-observation-7d-evaluate:
	uv run --package vav-platform-api python scripts/final/control.py observe-7d

production-observation-30d-evaluate:
	uv run --package vav-platform-api python scripts/final/control.py observe-30d

final-preproduction-verify: final-migrate final-seed final-sync final-release-manifest-check final-score-test final-go-no-go-test \
	final-approval-test final-launch-test final-observation-policy-test final-evidence-test final-security-test final-admin-e2e \
	final-evidence-build

final-release-candidate: quality-verify ui-verify experience-verify process-verify data-integrity-verify admin-completeness-verify functional-usability-verify \
	regression-release performance-release security-release resilience-release final-preproduction-verify
	@:
