#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
scope="${EVIDENCE_SCOPE:-local_compose}"
profile="${K6_PROFILE:-local}"
run_id="$(date -u +%Y%m%dT%H%M%SZ)"
result_dir="${PERFORMANCE_RESULT_DIR:-$repo_root/performance-results/external-$run_id}"
mkdir -p "$result_dir"

restore_development_api=false
restore_api() {
  if [[ "$restore_development_api" != "true" ]]; then
    return
  fi
  docker compose up -d --no-deps --force-recreate api >/dev/null
  for attempt in $(seq 1 60); do
    if curl --noproxy '*' --silent --fail --max-time 2 \
      http://127.0.0.1:8000/api/v1/health/ready >/dev/null; then
      return
    fi
    if [[ "$attempt" == "60" ]]; then
      echo "Development API did not recover after the performance suite" >&2
      return 1
    fi
    sleep 1
  done
}
trap restore_api EXIT

if [[ "$scope" == "local_compose" && "$profile" == "local" && \
  "${PERFORMANCE_LOCAL_PRODUCTION_SHAPE:-true}" == "true" ]]; then
  restore_development_api=true
  docker compose \
    -f docker-compose.yml \
    -f deploy/compose/docker-compose.performance.yml \
    up -d --no-deps --force-recreate api >/dev/null
  for attempt in $(seq 1 60); do
    if curl --noproxy '*' --silent --fail --max-time 2 \
      http://127.0.0.1:8000/api/v1/health/ready >/dev/null; then
      break
    fi
    if [[ "$attempt" == "60" ]]; then
      echo "Production-shaped local API did not become ready" >&2
      exit 1
    fi
    sleep 1
  done
fi

scenario_failures=0
for scenario in baseline load spike stress soak; do
  if ! PERFORMANCE_RESULT_DIR="$result_dir" K6_PROFILE="$profile" \
    scripts/performance/run-k6.sh "tests/performance/$scenario.js"; then
    scenario_failures=$((scenario_failures + 1))
  fi
done

.venv/bin/python - "$result_dir" "$scope" "$profile" <<'PY'
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path(sys.argv[1])
scope = sys.argv[2]
profile = sys.argv[3]
artifacts = []
for path in sorted(root.glob("*.json")):
    if path.name == "suite-summary.json":
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    failed = [
        name
        for name, metric in data.get("metrics", {}).items()
        if metric.get("thresholds") and any(metric["thresholds"].values())
    ]
    artifacts.append({
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "failed_threshold_metrics": failed,
    })
clean = not subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip()
summary = {
    "status": "LOCAL_PASS" if artifacts and not any(item["failed_threshold_metrics"] for item in artifacts) else "FAIL",
    "evidence_scope": scope,
    "profile": profile,
    "production_certification": False,
    "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "worktree_clean": clean,
    "completed_at": datetime.now(UTC).isoformat(),
    "artifacts": artifacts,
    "note": "LOCAL_PASS is executable local evidence only and is not accepted as production performance certification.",
}
(root / "suite-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, sort_keys=True))
if summary["status"] == "FAIL":
    raise SystemExit(1)
PY
test "$scenario_failures" -eq 0
