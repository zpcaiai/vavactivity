# Testing and acceptance

Ship unit, integration, concurrency, security and fairness suites under
`services/api/tests/recommendations`, plus member and operator e2e specs. The suites must prove
the invariants, not just the happy path: bidirectional eligibility, unknown handling,
relaxation permission, prohibited signals, deterministic ranking, diversification that never
admits, explanation non-disclosure, idempotent exposure and feedback, one active batch and one
active strategy, safety fail-closed, and fairness measured within the qualified pool. The
offline evaluation must run against a synthetic dataset; a non-synthetic dataset requires
privacy approval first, and any zero-tolerance guardrail failure blocks the release.
