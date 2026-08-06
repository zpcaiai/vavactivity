#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
mode="${PRODUCTION_READINESS_MODE:-architecture}"
[[ "$mode" == "architecture" || "$mode" == "production" ]] || { echo "Invalid PRODUCTION_READINESS_MODE" >&2; exit 2; }

PYTHONPATH=services/api/src .venv/bin/python scripts/diagnostics/validate_project_manifest.py >/dev/null
PYTHONPATH=services/api/src .venv/bin/python scripts/diagnostics/validate_environment_config.py >/dev/null
placeholder='sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
BACKEND_IMAGE="vav/api@$placeholder" USER_WEB_IMAGE="vav/user@$placeholder" \
ADMIN_WEB_IMAGE="vav/admin@$placeholder" REVERSE_PROXY_IMAGE="nginx@$placeholder" \
DATABASE_URL="postgresql+asyncpg://architecture:placeholder@database.invalid/vav?sslmode=require" \
REDIS_URL="rediss://redis.invalid/0" AUTH_REFRESH_TOKEN_PEPPER="architecture-placeholder-pepper" \
BACKUP_ENCRYPTION_KEY="architecture-placeholder-backup-key" \
PRIVACY_SEARCH_HMAC_PEPPER="architecture-placeholder-privacy-pepper" \
MEDIA_S3_ACCESS_KEY="architecture-placeholder-access" MEDIA_S3_SECRET_KEY="architecture-placeholder-secret" \
STRIPE_SECRET_KEY="architecture-placeholder-stripe" STRIPE_WEBHOOK_SECRET="architecture-placeholder-stripe-hook" \
PAYPAL_CLIENT_ID="architecture-placeholder-paypal" PAYPAL_CLIENT_SECRET="architecture-placeholder-paypal-secret" \
PAYPAL_WEBHOOK_ID="architecture-placeholder-paypal-hook" \
NOTIFICATION_EMAIL_PROVIDER_WEBHOOK_SECRET="architecture-placeholder-email-hook" \
  docker compose -f deploy/compose/docker-compose.prod.yml config --quiet
if rg -n 'image:\s*[^#\n]*:latest|privileged:\s*true' deploy infra/docker; then
  echo "Mutable or privileged production image configuration found" >&2
  exit 1
fi
rg -q 'read_only: true' deploy/compose/docker-compose.prod.yml
rg -q 'cap_drop: \[ALL\]' deploy/compose/docker-compose.prod.yml
rg -q 'no-new-privileges:true' deploy/compose/docker-compose.prod.yml
rg -q '^USER 10001:10001' infra/docker/backend.Dockerfile
kubectl kustomize deploy/kubernetes/overlays/production >/dev/null

if [[ "$mode" == "architecture" ]]; then
  printf '%s\n' '{"technical_status":"PASS","production_certification":"NOT_CERTIFIED","reason":"external staging, scan, signature, backup, restore, red-team and human approval evidence not evaluated"}'
  exit 0
fi

evidence_dir="${READINESS_EVIDENCE_DIR:-}"
test -n "$evidence_dir" && test -d "$evidence_dir" || { echo "READINESS_EVIDENCE_DIR is required" >&2; exit 2; }
release_version="${PRODUCTION_RELEASE_VERSION:-}"
release_commit="${PRODUCTION_RELEASE_COMMIT:-}"
test -n "$release_version" || { echo "PRODUCTION_RELEASE_VERSION is required" >&2; exit 2; }
test -n "$release_commit" || { echo "PRODUCTION_RELEASE_COMMIT is required" >&2; exit 2; }
required=(staging-smoke complete-e2e migration-dry-run backup restore-drill vulnerability-scan image-signature red-team privacy-e2e payment-e2e block-propagation production-approval production-smoke)
for evidence in "${required[@]}"; do
  file="$evidence_dir/$evidence.json"
  test -f "$file" || { echo "Missing readiness evidence: $file" >&2; exit 1; }
  .venv/bin/python - "$file" "$release_version" "$release_commit" <<'PY'
import json, sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text())
if value.get("status") != "PASS": raise SystemExit(f"evidence is not PASS: {sys.argv[1]}")
if not value.get("artifact_sha256") or not value.get("completed_at"): raise SystemExit(f"evidence identity incomplete: {sys.argv[1]}")
if value.get("release_version") != sys.argv[2]: raise SystemExit(f"evidence release mismatch: {sys.argv[1]}")
if value.get("git_commit") != sys.argv[3]: raise SystemExit(f"evidence commit mismatch: {sys.argv[1]}")
PY
done
printf '%s\n' '{"technical_status":"PASS","production_certification":"APPROVED_EVIDENCE_PRESENT"}'
