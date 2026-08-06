# Email provider failure

## Symptoms and impact

Email deliveries retry or dead-letter; transactions and durable in-app notifications remain committed.

## Detect

Check provider status, delivery latency/errors, suppression events, notification queue age, and dead letters.

## Immediate containment

Pause campaigns, prioritize security/transactional mail, prevent retry storms, and never log message bodies or credentials.

## Recovery

Restore or switch to an approved provider configuration, honor suppressions/consent, and replay idempotently within expiry windows.

## Verification and rollback

Use synthetic recipients, verify provider events and in-app state, and roll back the provider configuration if bounce/security metrics regress.

## Communication and review

Report delayed categories and alternative in-app access. Review quotas, authentication, templates, and retry policy.
