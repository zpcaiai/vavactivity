#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if "$repo_root/.venv/bin/python" -c 'import cryptography' >/dev/null 2>&1; then
  exec "$repo_root/.venv/bin/python" "$@"
fi
if docker image inspect vav-platform-api:latest >/dev/null 2>&1; then
  mounts=(-v "$repo_root:$repo_root")
  for argument in "$@"; do
    if [[ "$argument" == /* && "$argument" != "$repo_root"/* ]]; then
      mount_source="$argument"
      [[ -d "$mount_source" ]] || mount_source="$(dirname "$mount_source")"
      if [[ -d "$mount_source" ]]; then
        mounts+=(-v "$mount_source:$mount_source")
      fi
    fi
  done
  exec docker run --rm -i \
    "${mounts[@]}" \
    -w "$repo_root" \
    vav-platform-api:latest \
    /app/.venv/bin/python "$@"
fi
echo "No Python runtime with the locked backup cryptography dependency is available" >&2
exit 2
