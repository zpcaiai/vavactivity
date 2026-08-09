#!/usr/bin/env bash

# Shared frontend-repository discovery for the split VAV checkout.

vav_frontend_root() {
  local backend_root="$1"
  local candidate="${VAV_WEB_ROOT:-${backend_root}/../vavactivityWeb}"
  candidate="$(cd "$(dirname "$candidate")" && pwd)/$(basename "$candidate")"
  if [[ ! -f "${candidate}/package.json" || ! -f "${candidate}/pnpm-workspace.yaml" ]]; then
    echo "VAV frontend checkout not found at ${candidate}. Set VAV_WEB_ROOT to vavactivityWeb." >&2
    return 1
  fi
  printf '%s\n' "$candidate"
}

vav_pnpm() {
  if command -v corepack >/dev/null 2>&1; then
    corepack pnpm "$@"
  elif command -v pnpm >/dev/null 2>&1; then
    pnpm "$@"
  else
    echo "pnpm is required (directly or through corepack)." >&2
    return 127
  fi
}
