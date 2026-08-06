#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
PYTHONPATH=services/api/src .venv/bin/python scripts/diagnostics/validate_project_manifest.py
.venv/bin/python scripts/check_migration_heads.py

container="vav-migration-gate-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker run -d --name "$container" -p 127.0.0.1::5432 \
  -e POSTGRES_USER=vav_gate -e POSTGRES_PASSWORD=vav_gate_only -e POSTGRES_DB=vav_snapshot \
  pgvector/pgvector:0.8.0-pg16 >/dev/null
for attempt in $(seq 1 60); do
  if docker exec "$container" pg_isready -U vav_gate -d vav_snapshot >/dev/null 2>&1; then break; fi
  if [[ "$attempt" == 60 ]]; then echo "Migration gate database failed to start" >&2; exit 1; fi
  sleep 1
done
port="$(docker inspect -f '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}' "$container")"
snapshot_url="postgresql+asyncpg://vav_gate:vav_gate_only@127.0.0.1:$port/vav_snapshot"
empty_url="postgresql+asyncpg://vav_gate:vav_gate_only@127.0.0.1:$port/vav_empty"

DATABASE_URL="$snapshot_url" .venv/bin/alembic -c services/api/alembic.ini upgrade 20260805_0082
docker exec "$container" createdb -U vav_gate vav_empty
DATABASE_URL="$empty_url" .venv/bin/alembic -c services/api/alembic.ini upgrade head
DATABASE_URL="$snapshot_url" .venv/bin/alembic -c services/api/alembic.ini upgrade head

for database in vav_snapshot vav_empty; do
  revision="$(docker exec "$container" psql -U vav_gate -d "$database" -Atc 'SELECT version_num FROM alembic_version')"
  [[ "$revision" == "20260806_0085" ]] || { echo "$database stopped at $revision" >&2; exit 1; }
  tables="$(docker exec "$container" psql -U vav_gate -d "$database" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
  [[ "$tables" -gt 100 ]] || { echo "$database has incomplete schema: $tables tables" >&2; exit 1; }
done
echo "migration gate PASS: single head, empty database, and revision-0082 snapshot upgrade through Batch 20 execution contracts"
