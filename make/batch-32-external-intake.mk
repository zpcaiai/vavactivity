CERTIFICATION_INTAKE ?= config/certification/external-gate-intake.template.yaml
CERTIFICATION_PREFLIGHT_REPORT ?= build/certification/external-gate-preflight.json
CERTIFICATION_TARGET_LOCK ?= build/certification/certification-target-lock.json

.PHONY: external-certification-init external-certification-lock external-certification-preflight

external-certification-init:
	.venv/bin/python scripts/certification/external_gate_intake.py init \
		--output config/certification/external-gate-intake.yaml

external-certification-lock:
	.venv/bin/python scripts/certification/external_gate_intake.py lock-target \
		--input "$(CERTIFICATION_INTAKE)" \
		--output "$(CERTIFICATION_TARGET_LOCK)"

external-certification-preflight:
	.venv/bin/python scripts/certification/external_gate_intake.py preflight \
		--input "$(CERTIFICATION_INTAKE)" \
		--output "$(CERTIFICATION_PREFLIGHT_REPORT)"
