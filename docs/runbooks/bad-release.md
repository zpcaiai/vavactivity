# Bad release

## Symptoms and impact

Error, latency, safety, privacy, financial, or resource metrics regress after rollout.

## Detect

Correlate alerts, traces, logs, release digest, schema revision, flag changes, and staged traffic percentage.

## Immediate containment

Stop expansion, disable only optional approved flags, preserve evidence, and never turn off mandatory controls to restore metrics.

## Recovery

Roll back to the previous signed digest if schema-compatible; otherwise constrain traffic and forward-fix. Reconcile delayed queues and transactions.

## Verification and rollback

Run smoke and affected complete E2E/security paths; compare SLOs and ensure the old release can read the current schema.

## Communication and review

Record release identity, impact, mitigation, and next update. Keep the failed artifact/logs and complete a blameless review.
