#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
run_id="$(date -u +%Y%m%dT%H%M%SZ)"
result_dir="${RESILIENCE_RESULT_DIR:-$repo_root/build/resilience/local-$run_id}"
mkdir -p "$result_dir"

BACKUP_DESTINATION="${BACKUP_DESTINATION:-$repo_root/backups}" scripts/backup/backup-all.sh \
  | tee "$result_dir/backup.log"
scripts/backup/verify-backups.sh | tee "$result_dir/backup-verify.log"
RESTORE_REPORT_DESTINATION="$result_dir" scripts/restore/run-restore-drill.sh \
  | tee "$result_dir/restore-drill.log"

HA_CONFIRM=local-vav-compose-only \
  RESILIENCE_HA_REPORT="$result_dir/api-ha.json" \
  scripts/resilience/run-local-api-ha-drill.sh \
  | tee "$result_dir/api-ha.log"

for service in api redis worker minio scheduler; do
  SERVICE="$service" CHAOS_CONFIRM=local-vav-compose-only \
    scripts/disaster-recovery/inject-compose-failure.sh \
    | tee "$result_dir/chaos-$service.json"
done

.venv/bin/python scripts/resilience/summarize_local_suite.py "$result_dir"
