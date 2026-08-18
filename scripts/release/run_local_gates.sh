#!/usr/bin/env bash
#
# Execute the release gates that can actually be executed, and refuse to
# claim the ones that cannot.
#
# The ledger has carried UAT, deployment and certification as NOT_RUN /
# NOT_CERTIFIED for a while. Some of that is genuine — nobody can automate a
# live merchant certification — but part of it was simply that no single
# command ran the automatable gates and captured evidence. This is that
# command.
#
#   G1  build and static quality      — automated here
#   G2  integration on real backing services — automated here
#   G3  full local runtime            — partially; see the note it emits
#   G4  external UAT                  — NOT here: needs a deployed URL, run
#                                        playwright.external-uat.config.ts
#   G5  production certification      — NOT automatable, by definition
#
# Usage:
#   scripts/release/run_local_gates.sh [evidence_dir]
#
# Requires PostgreSQL 16 (with the pgvector, citext and pgcrypto extensions),
# Redis and an S3-compatible endpoint to already be reachable through the
# environment variables the API reads. `docker compose up` provides all three;
# so does a native install.

set -uo pipefail

EVIDENCE_DIR="${1:-evidence/local-gates}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

mkdir -p "$EVIDENCE_DIR"
SUMMARY="$EVIDENCE_DIR/gate-summary.json"
: > "$EVIDENCE_DIR/commands.log"

pass_count=0
fail_count=0
declare -a results=()

record() {
  local gate="$1" name="$2" status="$3" detail="$4"
  results+=("{\"gate\":\"$gate\",\"check\":\"$name\",\"status\":\"$status\",\"detail\":\"${detail//\"/\\\"}\"}")
  if [ "$status" = "PASS" ]; then pass_count=$((pass_count + 1)); else fail_count=$((fail_count + 1)); fi
  printf '%-4s %-42s %s\n' "$gate" "$name" "$status"
}

run() {
  # $1 gate, $2 name, rest: command
  local gate="$1" name="$2"; shift 2
  echo "\$ $*" >> "$EVIDENCE_DIR/commands.log"
  if "$@" >> "$EVIDENCE_DIR/commands.log" 2>&1; then
    record "$gate" "$name" "PASS" ""
  else
    record "$gate" "$name" "FAIL" "see commands.log"
  fi
}

echo "=== Gate G1 — build and static quality ==="
run G1 "ruff check" uv run ruff check services
run G1 "ruff format --check" uv run ruff format --check services
run G1 "mypy" uv run mypy services/api/src services/worker/src
run G1 "single migration head" uv run --package vav-platform-api python scripts/check_migration_heads.py

echo
echo "=== Gate G2 — integration on real backing services ==="

# Rate-limit counters survive a run. A second run against a warm Redis fails
# registration tests with 429 and looks like a code defect; CI never sees it
# because each job gets a fresh container. Flushing makes a local re-run mean
# the same thing as a CI run.
if command -v redis-cli >/dev/null 2>&1; then
  redis-cli -u "${REDIS_URL:-redis://127.0.0.1:6379/0}" flushdb >/dev/null 2>&1 \
    && record G2 "redis flushed before run" "PASS" "" \
    || record G2 "redis flushed before run" "FAIL" "redis-cli could not reach REDIS_URL"
else
  record G2 "redis flushed before run" "FAIL" "redis-cli not installed; re-runs may 429"
fi

run G2 "alembic upgrade head" \
  uv run --package vav-platform-api alembic -c services/api/alembic.ini upgrade head

if uv run --package vav-platform-api alembic -c services/api/alembic.ini current 2>&1 \
    | tee -a "$EVIDENCE_DIR/commands.log" | grep -Fq '(head)'; then
  record G2 "database is at head" "PASS" ""
else
  record G2 "database is at head" "FAIL" "alembic current did not report (head)"
fi

SEEDS=(seed_permissions seed_cms seed_catalog seed_courses seed_counseling seed_knowledge
       seed_ai_assistant seed_notification_templates seed_notifications seed_privacy
       seed_privacy_inventory seed_quality seed_experience seed_process_governance
       seed_data_governance seed_admin_platform seed_memberships seed_trust_safety)

seed_failures=0
for seed in "${SEEDS[@]}"; do
  uv run --package vav-platform-api python -m "vav.cli.$seed" \
    >> "$EVIDENCE_DIR/commands.log" 2>&1 || seed_failures=$((seed_failures + 1))
done
[ "$seed_failures" -eq 0 ] \
  && record G2 "seeds apply" "PASS" "" \
  || record G2 "seeds apply" "FAIL" "$seed_failures seed(s) failed"

# DATA-002 asks for *idempotent* seeds, which only a second run can show.
before="$(uv run --package vav-platform-api python -c "
import asyncio, os, asyncpg, re
url = re.sub(r'^postgresql\+asyncpg', 'postgresql', os.environ['DATABASE_URL'])
async def main():
    conn = await asyncpg.connect(url)
    print(await conn.fetchval('select count(*) from permissions'))
    await conn.close()
asyncio.run(main())" 2>/dev/null | tail -1)"
for seed in "${SEEDS[@]}"; do
  uv run --package vav-platform-api python -m "vav.cli.$seed" \
    >> "$EVIDENCE_DIR/commands.log" 2>&1 || seed_failures=$((seed_failures + 1))
done
after="$(uv run --package vav-platform-api python -c "
import asyncio, os, asyncpg, re
url = re.sub(r'^postgresql\+asyncpg', 'postgresql', os.environ['DATABASE_URL'])
async def main():
    conn = await asyncpg.connect(url)
    print(await conn.fetchval('select count(*) from permissions'))
    await conn.close()
asyncio.run(main())" 2>/dev/null | tail -1)"
if [ -n "$before" ] && [ "$before" = "$after" ]; then
  record G2 "seeds are idempotent (DATA-002)" "PASS" "permissions stayed at $after"
else
  record G2 "seeds are idempotent (DATA-002)" "FAIL" "permissions $before -> $after"
fi

# GATE_PYTEST_TARGET exists so this script can be smoke-tested without a
# seven-minute wait. It defaults to the whole suite; narrowing it produces
# evidence that says so, because the junit XML records what actually ran.
run G2 "pytest ${GATE_PYTEST_TARGET:-services/api/tests}" \
  uv run --package vav-platform-api pytest "${GATE_PYTEST_TARGET:-services/api/tests}" \
  -q -p no:cacheprovider --junitxml="$EVIDENCE_DIR/pytest-junit.xml"

echo
echo "=== Gates this script deliberately does not claim ==="
# Stated as data, not as silence: a gate that is merely unmentioned tends to
# get read as passing.
for entry in \
  "G3|full local runtime|partially covered — pytest exercises the API against real \
PostgreSQL/Redis/S3, but browser login, admin publish and My Events need the \
frontends running; run playwright.complete.config.ts" \
  "G4|external UAT|needs a deployed URL and a human tester; run \
playwright.external-uat.config.ts with E2E_USER_WEB_URL / E2E_ADMIN_WEB_URL set to \
the deployment" \
  "G5|production certification|not automatable — live merchant certification, \
privacy/compliance approval, content licences, on-call and real-user acceptance are \
attested by accountable people, see scripts/certification/external_gate_intake.py"
do
  IFS='|' read -r gate name detail <<< "$entry"
  results+=("{\"gate\":\"$gate\",\"check\":\"$name\",\"status\":\"NOT_RUN\",\"detail\":\"${detail//\"/\\\"}\"}")
  printf '%-4s %-42s %s\n' "$gate" "$name" "NOT_RUN"
done

printf '{\n  "generated_by": "scripts/release/run_local_gates.sh",\n' > "$SUMMARY"
printf '  "passed": %d,\n  "failed": %d,\n' "$pass_count" "$fail_count" >> "$SUMMARY"
printf '  "highest_supportable_status": "%s",\n' \
  "$([ "$fail_count" -eq 0 ] && echo "E2" || echo "FAILED")" >> "$SUMMARY"
printf '  "note": "E2 is the ceiling for this script. E3+ needs a browser run, E4 a deployment, E5 accountable humans.",\n' >> "$SUMMARY"
printf '  "results": [\n    %s\n  ]\n}\n' "$(IFS=$',\n    '; echo "${results[*]}")" >> "$SUMMARY"

echo
echo "evidence: $EVIDENCE_DIR"
echo "passed=$pass_count failed=$fail_count"
[ "$fail_count" -eq 0 ] || exit 1
