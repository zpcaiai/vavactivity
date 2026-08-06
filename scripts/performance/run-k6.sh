#!/usr/bin/env bash
set -euo pipefail
script="${1:?provide a k6 script}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
test -f "$script" || { echo "Missing performance scenario: $script" >&2; exit 2; }
mkdir -p performance-results
summary="performance-results/$(basename "$script" .js)-$(date -u +%Y%m%dT%H%M%SZ).json"
if command -v k6 >/dev/null 2>&1; then
  BASE_URL="${BASE_URL:-http://localhost:8000}" k6 run --summary-export "$summary" "$script"
else
  docker run --rm -i -e BASE_URL="${BASE_URL:-http://host.docker.internal:8000}" \
    -v "$repo_root:/workspace:ro" -v "$repo_root/performance-results:/results" \
    grafana/k6:0.57.0 run --summary-export "/results/$(basename "$summary")" "/workspace/$script"
fi
printf 'performance evidence: %s\n' "$summary"
