#!/usr/bin/env bash
set -euo pipefail

backend_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
api_port="${VAV_ROLE_E2E_API_PORT:-18001}"
user_port="${VAV_ROLE_E2E_USER_PORT:-15173}"
admin_port="${VAV_ROLE_E2E_ADMIN_PORT:-15174}"
runtime_dir="$(mktemp -d "${TMPDIR:-/tmp}/vav-role-browser.XXXXXX")"
container_name="vav-role-api-$$"
child_pids=()

terminate_tree() {
  local pid="$1"
  local child
  while IFS= read -r child; do
    [[ -n "${child}" ]] && terminate_tree "${child}"
  done < <(pgrep -P "${pid}" 2>/dev/null || true)
  kill "${pid}" 2>/dev/null || true
}

cleanup() {
  local pid
  set +e
  for pid in "${child_pids[@]}"; do
    terminate_tree "${pid}"
  done
  for pid in "${child_pids[@]}"; do
    wait "${pid}" 2>/dev/null || true
  done
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  rm -rf "${runtime_dir}"
}
trap cleanup EXIT INT TERM

assert_port_free() {
  local port="$1"
  if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "role browser test port ${port} is already in use" >&2
    exit 2
  fi
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local log_file="$3"
  local attempt
  for attempt in $(seq 1 240); do
    if curl --max-time 2 --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "${label} did not become ready: ${url}" >&2
  tail -n 120 "${log_file}" >&2 || true
  return 1
}

for port in "${api_port}" "${user_port}" "${admin_port}"; do
  assert_port_free "${port}"
done

cd "${backend_root}"
docker compose run --rm --name "${container_name}" --no-deps \
  -p "127.0.0.1:${api_port}:8000" \
  api uvicorn vav.main:app --host 0.0.0.0 --port 8000 \
  >"${runtime_dir}/api.log" 2>&1 &
child_pids+=("$!")
wait_for_url \
  "isolated API" \
  "http://127.0.0.1:${api_port}/api/v1/health/ready" \
  "${runtime_dir}/api.log"

VITE_API_PROXY_TARGET="http://127.0.0.1:${api_port}" \
VITE_API_PROXY_ORIGIN="http://localhost:5173" \
  ./scripts/web-pnpm --filter @vav/user-web exec vite \
    --config vite.e2e.config.ts --host 127.0.0.1 --port "${user_port}" --strictPort \
    >"${runtime_dir}/user-web.log" 2>&1 &
child_pids+=("$!")

VITE_API_PROXY_TARGET="http://127.0.0.1:${api_port}" \
VITE_API_PROXY_ORIGIN="http://localhost:5174" \
  ./scripts/web-pnpm --filter @vav/admin-web exec vite \
    --config vite.e2e.config.ts --host 127.0.0.1 --port "${admin_port}" --strictPort \
    >"${runtime_dir}/admin-web.log" 2>&1 &
child_pids+=("$!")

wait_for_url \
  "isolated user web" \
  "http://127.0.0.1:${user_port}/zh-CN/auth/login" \
  "${runtime_dir}/user-web.log"
wait_for_url \
  "isolated admin web" \
  "http://127.0.0.1:${admin_port}/admin/login" \
  "${runtime_dir}/admin-web.log"

env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  NO_PROXY=127.0.0.1,localhost \
  E2E_USER_WEB_URL="http://127.0.0.1:${user_port}" \
  E2E_ADMIN_WEB_URL="http://127.0.0.1:${admin_port}" \
  ./scripts/web-pnpm exec playwright test \
    e2e/auth.user.spec.ts e2e/auth.admin.spec.ts --workers=1 --timeout=120000
