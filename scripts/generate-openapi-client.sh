#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

uv run --package vav-platform-api python scripts/export_openapi.py
corepack pnpm --filter @vav/api-client generate

echo "OpenAPI contract and TypeScript types are current"

