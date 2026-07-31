#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from development-only template"
fi

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
./scripts/generate-openapi-client.sh

if ! git diff --exit-code -- packages/contracts/openapi.json packages/api-client/src/schema.ts; then
  echo "Generated API contract has uncommitted changes" >&2
  exit 1
fi

echo "Batch 1 acceptance passed"
