#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
backup_root="${BACKUP_DESTINATION:-$repo_root/backups}"
key_file="${BACKUP_ENCRYPTION_KEY_FILE:-$repo_root/.dev-secrets/backup-encryption-key}"
target="${BACKUP_SET:-}"
if [[ -z "$target" ]]; then
  target="$(find "$backup_root" -mindepth 1 -maxdepth 1 -type d ! -name '.work-*' -print | sort | tail -1)"
fi
test -n "$target" && test -d "$target" || { echo "No backup set found" >&2; exit 2; }
case "$(cd "$target" && pwd)" in "$backup_root"/*) ;; *) echo "Backup set escapes destination" >&2; exit 2 ;; esac
test -f "$key_file" || { echo "Missing backup encryption key file" >&2; exit 2; }

.venv/bin/python "$repo_root/scripts/backup/build_manifest.py" verify "$target"
temporary="$(mktemp -d "${TMPDIR:-/tmp}/vav-backup-verify.XXXXXX")"
cleanup() { rm -rf -- "$temporary"; }
trap cleanup EXIT
for encrypted in "$target"/*.vavenc; do
  output="$temporary/$(basename "$encrypted" .vavenc)"
  .venv/bin/python "$repo_root/scripts/backup/backup_crypto.py" decrypt \
    "$encrypted" "$output" --key-file "$key_file"
  test -s "$output" || { echo "Decrypted artifact is empty: $encrypted" >&2; exit 1; }
done
tar -tf "$temporary/objects.tar" >/dev/null
tar -tf "$temporary/configuration.tar" >/dev/null
printf 'backup verification PASS: %s\n' "$target"
