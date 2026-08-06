---
name: vav-docker-compose-local-runtime
description: Bootstrap and operate the deterministic full VAV local runtime with scoped profiles and synthetic data.
---

Run `./scripts/vavctl doctor`, then `bootstrap`, `up`, and `smoke`. Base services are PostgreSQL/pgvector, Redis and MinIO; development adds Mailpit, API, specialized workers, scheduler, both SPAs and optional proxy/observability profiles. Use locked builds and ignored generated secrets. Demo seeds require explicit opt-in and are forbidden in production/DR. Destructive reset requires the exact confirmation token and only targets VAV local volumes.
