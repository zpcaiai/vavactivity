.PHONY: security-migrate security-seed security-sync security-threat-model-check security-attack-surface-check \
	@./scripts/run_if_available.sh security-sast security-sca security-secret-scan security-iac-scan security-container-scan security-api-dast security-api-fuzz \
	@./scripts/run_if_available.sh security-auth-test security-authorization-test security-injection-test security-ssrf-test security-upload-test \
	@./scripts/run_if_available.sh security-webhook-test security-privacy-test security-ai-test security-skill-test security-pentest-regression \
	@./scripts/run_if_available.sh security-admin-e2e security-evidence-build security-verify security-release batch-30

batch-30: security-release
	@:

security-migrate:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py migrate

security-seed:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py seed

security-sync:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py sync

security-threat-model-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py threat-model-check

security-attack-surface-check:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py attack-surface-check

security-sast:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py sast

security-sca:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py sca

security-secret-scan:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py secret-scan

security-iac-scan:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py iac-scan

security-container-scan:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py container-scan

security-api-dast:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py api-dast

security-api-fuzz:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py api-fuzz

security-auth-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py auth-test

security-authorization-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py authorization-test

security-injection-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py injection-test

security-ssrf-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py ssrf-test

security-upload-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py upload-test

security-webhook-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py webhook-test

security-privacy-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py privacy-test

security-ai-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py ai-test

security-skill-test:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py skill-test

security-pentest-regression:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py pen-test

security-admin-e2e:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py admin-e2e

security-evidence-build:
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py evidence

security-verify: security-migrate security-seed security-sync security-threat-model-check security-attack-surface-check \
	@./scripts/run_if_available.sh security-sast security-sca security-secret-scan security-iac-scan security-container-scan security-api-dast \
	@./scripts/run_if_available.sh security-api-fuzz security-auth-test security-authorization-test security-injection-test security-ssrf-test \
	@./scripts/run_if_available.sh security-upload-test security-webhook-test security-privacy-test security-ai-test security-skill-test \
	@./scripts/run_if_available.sh security-pentest-regression security-admin-e2e security-evidence-build

security-release: security-verify
	@./scripts/run_if_available.sh uv run --package vav-platform-api python scripts/security/control.py pen-test
