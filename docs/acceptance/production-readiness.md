# Production readiness

Architecture readiness validates manifests, environment contracts, production Compose, container hardening, Kubernetes rendering, and secret boundaries. Its successful result intentionally says `production_certification: NOT_CERTIFIED`.

Production mode additionally requires individually identified PASS evidence for staging smoke, complete E2E, migration dry-run, backup, restore drill, vulnerability scan, image signature, red team, privacy E2E, payment E2E, block propagation, production approval, and production smoke. Every evidence file includes completion time, artifact SHA-256, release version, and Git commit. Evidence from another release is rejected.

Run architecture validation with `make production-readiness`. Run production evaluation only with `PRODUCTION_READINESS_MODE=production READINESS_EVIDENCE_DIR=<approved-directory> PRODUCTION_RELEASE_VERSION=<version> PRODUCTION_RELEASE_COMMIT=<full-sha> make production-readiness`. Missing, malformed, stale, or cross-release evidence fails closed.
