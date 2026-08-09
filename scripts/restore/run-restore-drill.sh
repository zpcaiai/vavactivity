#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
backup_root="${BACKUP_DESTINATION:-$repo_root/backups}"
key_file="${BACKUP_ENCRYPTION_KEY_FILE:-$repo_root/.dev-secrets/backup-encryption-key}"
target="${BACKUP_SET:-$(find "$backup_root" -mindepth 1 -maxdepth 1 -type d ! -name '.work-*' -print | sort | tail -1)}"
test -n "$target" && test -d "$target" || { echo "No backup set found" >&2; exit 2; }
case "$(cd "$target" && pwd)" in "$backup_root"/*) ;; *) echo "Backup set escapes destination" >&2; exit 2 ;; esac

BACKUP_SET="$target" scripts/backup/verify-backups.sh
temporary="$(mktemp -d "${TMPDIR:-/tmp}/vav-restore-drill.XXXXXX")"
container="vav-restore-drill-$$"
report_root="${RESTORE_REPORT_DESTINATION:-$repo_root/restore-reports}"
mkdir -p "$report_root"
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf -- "$temporary"
}
trap cleanup EXIT

scripts/backup/run-python.sh scripts/backup/backup_crypto.py decrypt \
  "$target/postgres.dump.vavenc" "$temporary/postgres.dump" --key-file "$key_file"
scripts/backup/run-python.sh scripts/backup/backup_crypto.py decrypt \
  "$target/objects.tar.vavenc" "$temporary/objects.tar" --key-file "$key_file"

docker run -d --name "$container" -e POSTGRES_DB=vav_restore \
  -e POSTGRES_USER=vav_restore -e POSTGRES_PASSWORD=restore_drill_only \
  pgvector/pgvector:0.8.0-pg16 >/dev/null
for attempt in $(seq 1 60); do
  if docker exec "$container" pg_isready -U vav_restore -d vav_restore >/dev/null 2>&1; then break; fi
  if [[ "$attempt" == 60 ]]; then echo "Restore database did not become ready" >&2; exit 1; fi
  sleep 1
done
docker cp "$temporary/postgres.dump" "$container:/tmp/postgres.dump"
docker exec "$container" pg_restore -U vav_restore -d vav_restore --no-owner --no-privileges /tmp/postgres.dump
revision="$(docker exec "$container" psql -U vav_restore -d vav_restore -Atc 'SELECT version_num FROM alembic_version')"
table_count="$(docker exec "$container" psql -U vav_restore -d vav_restore -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
test "$table_count" -gt 100 || { echo "Restored table inventory is incomplete" >&2; exit 1; }
tar -tf "$temporary/objects.tar" >/dev/null

report="$report_root/restore-drill-$(date -u +%Y%m%dT%H%M%SZ).json"
scripts/backup/run-python.sh - "$report" "$target" "$revision" "$table_count" <<'PY'
import json, sys
from datetime import UTC, datetime
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
  "status": "PASS", "completed_at": datetime.now(UTC).isoformat(),
  "backup_set": str(Path(sys.argv[2]).name), "database_revision": sys.argv[3],
  "public_table_count": int(sys.argv[4]), "object_archive_verified": True,
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
printf 'restore drill PASS: %s\n' "$report"
