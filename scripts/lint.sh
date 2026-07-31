#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

uv run ruff check services
uv run ruff format --check services
uv run mypy services/api/src services/worker/src
corepack pnpm lint
corepack pnpm typecheck

