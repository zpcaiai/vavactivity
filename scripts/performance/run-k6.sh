#!/usr/bin/env bash
set -euo pipefail
script="${1:?provide a k6 script}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
test -f "$script" || { echo "Missing performance scenario: $script" >&2; exit 2; }
result_dir="${PERFORMANCE_RESULT_DIR:-performance-results}"
mkdir -p "$result_dir"
summary="$result_dir/$(basename "$script" .js)-$(date -u +%Y%m%dT%H%M%SZ).json"
if command -v k6 >/dev/null 2>&1; then
  BASE_URL="${BASE_URL:-http://localhost:8000}" K6_PROFILE="${K6_PROFILE:-certification}" \
    k6 run --summary-export "$summary" "$script"
else
  result_dir_absolute="$(cd "$result_dir" && pwd)"
  docker run --rm -i -e BASE_URL="${BASE_URL:-http://host.docker.internal:8000}" \
    -e K6_PROFILE="${K6_PROFILE:-certification}" -e SOAK_DURATION="${SOAK_DURATION:-}" \
    -v "$repo_root:/workspace:ro" -v "$result_dir_absolute:/results" \
    grafana/k6:0.57.0 run --summary-export "/results/$(basename "$summary")" "/workspace/$script"
fi
printf 'performance evidence: %s\n' "$summary"
