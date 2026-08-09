#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

backup_root="${BACKUP_DESTINATION:-$repo_root/backups}"
key_file="${BACKUP_ENCRYPTION_KEY_FILE:-$repo_root/.dev-secrets/backup-encryption-key}"
case "$backup_root" in
  /|"$repo_root") echo "Refusing unsafe backup destination: $backup_root" >&2; exit 2 ;;
esac
test -f "$key_file" || { echo "Missing backup encryption key file: $key_file" >&2; exit 2; }
mkdir -p "$backup_root"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$backup_root/$timestamp"
work="$backup_root/.work-$timestamp-$$"
mkdir -p "$destination" "$work"
cleanup() { rm -rf -- "$work"; }
trap cleanup EXIT

postgres_user="${POSTGRES_USER:-vav}"
postgres_db="${POSTGRES_DB:-vav}"
docker compose exec -T postgres pg_dump -U "$postgres_user" -d "$postgres_db" \
  --format=custom --no-owner --no-privileges > "$work/postgres.dump"

container_destination="/app/backups/$(basename "$work")/objects.tar"
docker compose exec -T api python /app/scripts/backup/object_snapshot.py "$container_destination"

tar -C "$repo_root" -cf "$work/configuration.tar" \
  project-manifest.yaml release-manifest.yaml config deploy docs/runbooks docs/disaster-recovery

for artifact in postgres.dump objects.tar configuration.tar; do
  scripts/backup/run-python.sh scripts/backup/backup_crypto.py encrypt \
    "$work/$artifact" "$destination/$artifact.vavenc" --key-file "$key_file"
done

revision="$(docker compose exec -T postgres psql -U "$postgres_user" -d "$postgres_db" -Atc 'SELECT version_num FROM alembic_version')"
release="${APP_VERSION:-development}"
scripts/backup/run-python.sh scripts/backup/build_manifest.py build "$destination" \
  --revision "$revision" --release "$release"
chmod -R go-rwx "$destination"
printf 'backup completed: %s\n' "$destination"
