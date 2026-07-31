#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

for command_name in uv node corepack; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
done

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from development-only template"
fi

corepack pnpm install
uv sync --all-packages --all-groups
./scripts/generate-openapi-client.sh
python3 scripts/validate_manifest.py

echo "Bootstrap complete. Run: make dev"

