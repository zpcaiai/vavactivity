# Provider inventory

Payment is transactional and fail closed: browser return never grants service; only verified idempotent webhooks do. Email failure must not roll back business transactions; in-app records remain available. AI failure degrades to approved fallback or a safe unavailable response and never skips risk screening. Object-storage uncertainty denies private access and retries processing. Managed database and Redis connections require TLS in staging, production, and DR.

Provider credentials are secret references resolved server-side. Operators see configured/degraded state, not values. Changes require owner review, sandbox verification, rotation and rollback procedures, rate/timeout budgets, and audit evidence.
