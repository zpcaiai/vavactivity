#!/usr/bin/env bash
set -euo pipefail

workspace_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${VAV_E2E_PYTHON:-${workspace_root}/.venv/bin/python}"
api_host="${VAV_E2E_API_HOST:-127.0.0.1}"
api_port="${VAV_E2E_API_PORT:-8000}"

if [[ ! -x "${python_bin}" ]]; then
  echo "E2E Python is not executable: ${python_bin}" >&2
  echo "Set VAV_E2E_PYTHON to the project's Python interpreter." >&2
  exit 1
fi
if [[ ! "${api_port}" =~ ^[0-9]+$ ]] || (( api_port < 1 || api_port > 65535 )); then
  echo "VAV_E2E_API_PORT must be an integer between 1 and 65535" >&2
  exit 1
fi

export PYTHONPATH="${workspace_root}/services/api/src${PYTHONPATH:+:${PYTHONPATH}}"
cd "${workspace_root}"
exec "${python_bin}" -m uvicorn vav.main:app --host "${api_host}" --port "${api_port}"
