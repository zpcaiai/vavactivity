#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source "$project_root/scripts/lib/frontend-workspace.sh"
web_root="$(vav_frontend_root "$project_root")"

uv run --package vav-platform-api pytest services/api/tests
(cd "$web_root" && vav_pnpm test)
