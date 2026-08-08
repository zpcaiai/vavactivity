#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from development-only template"
fi

./scripts/generate-dev-auth-keys.sh
uv run python scripts/validate_manifest.py
docker compose config --quiet
compose=(docker compose --profile workers)
if [[ "${VAV_VERIFY_REUSE_BUILT_IMAGES:-false}" == "true" ]]; then
  echo "Reusing locally built images for verification"
  "${compose[@]}" up -d
else
  "${compose[@]}" up -d --build
fi
./scripts/wait-for-services.sh

for worker_service in worker-ai worker-media worker-notifications worker-privacy worker-safety; do
  container_id="$("${compose[@]}" ps -q "$worker_service")"
  if [[ -z "$container_id" ]] || [[ "$(docker inspect --format '{{.State.Status}}' "$container_id")" != "running" ]]; then
    echo "$worker_service did not start" >&2
    exit 1
  fi
  echo "$worker_service running"
done

curl --noproxy "*" --fail --silent http://localhost:8000/api/v1/health/live >/dev/null
curl --noproxy "*" --fail --silent http://localhost:8000/api/v1/health/ready >/dev/null
curl --noproxy "*" --fail --silent http://localhost:5173 >/dev/null
curl --noproxy "*" --fail --silent http://localhost:5174/admin/login >/dev/null

docker compose exec -T api alembic upgrade head
E2E_EXTERNAL_WEBSERVERS=1 corepack pnpm exec playwright test e2e/auth.admin.spec.ts e2e/auth.user.spec.ts
docker compose run --rm --no-deps api pytest
corepack pnpm --recursive --if-present test
corepack pnpm --recursive --if-present build

contract_hash_before="$(
  shasum -a 256 packages/contracts/openapi.json packages/api-client/src/schema.ts
)"
./scripts/generate-openapi-client.sh

contract_hash_after="$(
  shasum -a 256 packages/contracts/openapi.json packages/api-client/src/schema.ts
)"
if [[ "$contract_hash_before" != "$contract_hash_after" ]]; then
  echo "Generated API contract was stale; review and rerun verification" >&2
  exit 1
fi

echo "Platform acceptance passed"
