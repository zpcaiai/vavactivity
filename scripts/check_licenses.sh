#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

mkdir -p tmp
uv run pip-licenses --format=json --output-file=tmp/python-licenses.json
./scripts/web-pnpm licenses list --json > tmp/node-licenses.json
echo "Dependency license inventories written under tmp/"
