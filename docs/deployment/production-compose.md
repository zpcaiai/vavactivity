# Production Compose reference

`deploy/compose/docker-compose.prod.yml` is a production-shaped reference for controlled single-host installations. It requires immutable signed `@sha256` images and external database, Redis, object storage, certificate, and key providers. It intentionally contains no PostgreSQL, Redis, MinIO, Mailpit, plaintext secret service, or empty secret fallback. Required secret environment values fail before container creation when the deployment secret manager has not injected them.

Validate without deploying:

```bash
# DATABASE_URL, REDIS_URL, peppers, provider credentials, and webhook secrets
# must already be exported by the deployment secret manager.
BACKEND_IMAGE=vav/api@sha256:<digest> \
USER_WEB_IMAGE=vav/user@sha256:<digest> \
ADMIN_WEB_IMAGE=vav/admin@sha256:<digest> \
REVERSE_PROXY_IMAGE=nginx@sha256:<digest> \
docker compose -f deploy/compose/docker-compose.prod.yml config --quiet
```

The migration service must complete before API traffic. Containers run read-only, drop all capabilities, use `no-new-privileges`, and separate edge/internal networks; only the API joins both networks, while migration and workers remain internal. Production activation still requires the readiness evidence and approval gates.
