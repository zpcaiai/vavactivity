# Data integrity recovery runbook

1. Identify the canonical owner and contract version.
2. Quarantine an unsafe derived projection if needed.
3. Inspect event gaps, dead letters and reconciliation fingerprints.
4. Rebuild projections or invoke the registered domain repair command.
5. Resume Backfill from its durable cursor.
6. Rerun quality and reconciliation checks.
7. Close evidence only after authoritative postconditions pass.
