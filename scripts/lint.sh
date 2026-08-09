#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source "$project_root/scripts/lib/frontend-workspace.sh"
web_root="$(vav_frontend_root "$project_root")"

uv run ruff check services
uv run ruff format --check services
uv run mypy services/api/src services/worker/src
(cd "$web_root" && vav_pnpm lint)
(cd "$web_root" && vav_pnpm typecheck)
