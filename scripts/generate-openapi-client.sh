#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source "$project_root/scripts/lib/frontend-workspace.sh"
web_root="$(vav_frontend_root "$project_root")"

uv run --package vav-platform-api python scripts/export_openapi.py
cp packages/contracts/openapi.json "$web_root/packages/contracts/openapi.json"
(cd "$web_root" && vav_pnpm --filter @vav/api-client generate)

echo "OpenAPI contract and TypeScript types are current"
