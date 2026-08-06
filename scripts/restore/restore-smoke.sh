#!/usr/bin/env bash
set -euo pipefail
report_root="${RESTORE_REPORT_DESTINATION:-restore-reports}"
latest="$(find "$report_root" -maxdepth 1 -type f -name 'restore-drill-*.json' -print | sort | tail -1)"
test -n "$latest" || { echo "No restore drill report found" >&2; exit 2; }
.venv/bin/python - "$latest" <<'PY'
import json, sys
from pathlib import Path
report=json.loads(Path(sys.argv[1]).read_text())
assert report["status"] == "PASS"
assert report["public_table_count"] > 100
assert report["object_archive_verified"] is True
print(f"restore smoke PASS: {sys.argv[1]}")
PY
