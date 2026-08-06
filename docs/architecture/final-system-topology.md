# VAV production system topology

## Runtime boundaries

Traffic enters a TLS reverse proxy and is routed to the stateless user web, admin web, and API workloads. The API is the sole synchronous authority for PostgreSQL writes. Queue workers consume durable jobs for default domain work, AI/knowledge/recommendations, notifications, privacy, safety, and media. The scheduler may enqueue work but never owns business truth.

PostgreSQL/pgvector is authoritative for transactional and retrieval metadata. Redis is disposable coordination, rate-limit, cache, and broker state; recovery must not rely on Redis as business truth. Object storage contains public and private objects behind API-issued access decisions. Production and DR use managed external PostgreSQL, Redis, and object storage; the local Compose profile is not a production topology.

## Control and evidence planes

- `project-manifest.yaml` and the 19 module manifests define the closed-world assembly.
- Alembic revision `20260806_0083` is the single schema head.
- `release-manifest.yaml` binds commits, immutable image digests, contract checksums, configuration fingerprint, schema revision, quality evidence, and approval.
- `/api/v1/admin/system/*` exposes redacted operational state under dedicated RBAC.
- OpenTelemetry emits structured logs, low-cardinality metrics, and traces; Prometheus, Grafana, Loki, and Tempo are the local reference stack.
- Backups are encrypted before retention and restore drills run in isolated disposable databases.

## Trust boundaries

The public and admin SPAs never receive provider, encryption, signing, or database credentials. Secret providers resolve references only inside server workloads. Admin visibility remains permission-scoped and audited. Feature flags cannot disable authorization, payment confirmation, privacy consent, encryption, or trust-and-safety gates. Production maintenance and deployment require independent approval.

## Availability model

Production API and worker pools run as non-root, read-only containers with dropped capabilities, network policies, disruption budgets, and autoscaling. Readiness removes a workload that cannot serve safely; liveness only proves the process is alive. AI, email, and cache failures degrade without bypassing safety. Payment uncertainty remains pending and cannot activate entitlements.
