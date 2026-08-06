# Batch 23 implementation

Batch 23 adds migration 89, the `experience` backend module, five shared frontend packages, user home/task/journey/search/help pages, an administrator experience console, 12 Skills and deterministic gates.

Canonical commands are in `make/batch-23.mk`. `make experience-verify` covers manifest integrity, route/dead-end checks, backend unit/integration/concurrency/security tests, shared-package tests, both frontend suites/builds and evidence generation. Live Docker E2E remains a separate explicit gate.

Seed data activates versioned reference definitions but never creates certification approval. The quality gate is seeded as draft and all production certification remains fail-closed until independent evidence is accepted.
