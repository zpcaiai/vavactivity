.PHONY: security-migrate security-seed security-sync security-threat-model-check security-attack-surface-check \
	security-sast security-sca security-secret-scan security-iac-scan security-container-scan security-api-dast security-api-fuzz \
	security-auth-test security-authorization-test security-injection-test security-ssrf-test security-upload-test \
	security-webhook-test security-privacy-test security-ai-test security-skill-test security-pentest-regression \
	security-admin-e2e security-evidence-build security-verify security-release

security-migrate:
	uv run --package vav-platform-api python scripts/security/control.py migrate

security-seed:
	uv run --package vav-platform-api python scripts/security/control.py seed

security-sync:
	uv run --package vav-platform-api python scripts/security/control.py sync

security-threat-model-check:
	uv run --package vav-platform-api python scripts/security/control.py threat-model-check

security-attack-surface-check:
	uv run --package vav-platform-api python scripts/security/control.py attack-surface-check

security-sast:
	uv run --package vav-platform-api python scripts/security/control.py sast

security-sca:
	uv run --package vav-platform-api python scripts/security/control.py sca

security-secret-scan:
	uv run --package vav-platform-api python scripts/security/control.py secret-scan

security-iac-scan:
	uv run --package vav-platform-api python scripts/security/control.py iac-scan

security-container-scan:
	uv run --package vav-platform-api python scripts/security/control.py container-scan

security-api-dast:
	uv run --package vav-platform-api python scripts/security/control.py api-dast

security-api-fuzz:
	uv run --package vav-platform-api python scripts/security/control.py api-fuzz

security-auth-test:
	uv run --package vav-platform-api python scripts/security/control.py auth-test

security-authorization-test:
	uv run --package vav-platform-api python scripts/security/control.py authorization-test

security-injection-test:
	uv run --package vav-platform-api python scripts/security/control.py injection-test

security-ssrf-test:
	uv run --package vav-platform-api python scripts/security/control.py ssrf-test

security-upload-test:
	uv run --package vav-platform-api python scripts/security/control.py upload-test

security-webhook-test:
	uv run --package vav-platform-api python scripts/security/control.py webhook-test

security-privacy-test:
	uv run --package vav-platform-api python scripts/security/control.py privacy-test

security-ai-test:
	uv run --package vav-platform-api python scripts/security/control.py ai-test

security-skill-test:
	uv run --package vav-platform-api python scripts/security/control.py skill-test

security-pentest-regression:
	uv run --package vav-platform-api python scripts/security/control.py pen-test

security-admin-e2e:
	uv run --package vav-platform-api python scripts/security/control.py admin-e2e

security-evidence-build:
	uv run --package vav-platform-api python scripts/security/control.py evidence

security-verify: security-migrate security-seed security-sync security-threat-model-check security-attack-surface-check \
	security-sast security-sca security-secret-scan security-iac-scan security-container-scan security-api-dast \
	security-api-fuzz security-auth-test security-authorization-test security-injection-test security-ssrf-test \
	security-upload-test security-webhook-test security-privacy-test security-ai-test security-skill-test \
	security-pentest-regression security-admin-e2e security-evidence-build

security-release: security-verify
	uv run --package vav-platform-api python scripts/security/control.py pen-test
