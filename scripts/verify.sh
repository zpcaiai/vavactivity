#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from development-only template"
fi

./scripts/generate-dev-auth-keys.sh
python3 scripts/validate_manifest.py
docker compose config --quiet
docker compose up -d --build
./scripts/wait-for-services.sh

curl --noproxy "*" --fail --silent http://localhost:8000/api/v1/health/live >/dev/null
curl --noproxy "*" --fail --silent http://localhost:8000/api/v1/health/ready >/dev/null
curl --noproxy "*" --fail --silent http://localhost:5173 >/dev/null
curl --noproxy "*" --fail --silent http://localhost:5174/admin/login >/dev/null

docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest
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
