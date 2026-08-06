# Cross-module handoff contracts

`config/experience/handoffs.yaml` defines ten governed handoffs. Context schemas allow bounded identifiers only. Runtime context is encrypted at rest and checksum-bound; raw contact details, evidence, messages, prices, credentials and tokens are rejected.

Acceptance is user-bound and rechecks identity, permission, privacy, safety, expiry and target-route eligibility. Cross-user lookup returns the same result as a missing handoff. Failures return to the registered source/fallback route and are audited without copying sensitive context.

Handoffs coordinate navigation only. Target modules remain responsible for domain commands and completion truth.
