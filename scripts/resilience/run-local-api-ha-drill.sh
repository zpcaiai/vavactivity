#!/usr/bin/env bash
set -euo pipefail

[[ "${HA_CONFIRM:-}" == "local-vav-compose-only" ]] || {
  echo "Set HA_CONFIRM=local-vav-compose-only to run the scoped local HA drill" >&2
  exit 2
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

primary_container="$(docker compose ps -q api)"
test -n "$primary_container" || { echo "The primary API container is not running" >&2; exit 2; }
project="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$primary_container")"
[[ "$project" == "vav-platform" ]] || { echo "Refusing non-VAV container: $primary_container" >&2; exit 2; }

primary_name="$(docker inspect -f '{{.Name}}' "$primary_container" | sed 's#^/##')"
[[ "$primary_name" == "vav-platform-api-1" ]] || {
  echo "Expected vav-platform-api-1, got $primary_name" >&2
  exit 2
}

peer_name="vav-platform-api-ha-peer"
proxy_name="vav-platform-local-ha-proxy"
proxy_port="${LOCAL_HA_PROXY_PORT:-}"
request_count="${LOCAL_HA_REQUEST_COUNT:-20}"
report_path="${RESILIENCE_HA_REPORT:-}"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ -n "$proxy_port" ]]; then
  case "$proxy_port" in *[!0-9]*) echo "LOCAL_HA_PROXY_PORT must be numeric" >&2; exit 2 ;; esac
fi
case "$request_count" in ''|*[!0-9]*) echo "LOCAL_HA_REQUEST_COUNT must be numeric" >&2; exit 2 ;; esac
(( request_count > 0 )) || { echo "LOCAL_HA_REQUEST_COUNT must be positive" >&2; exit 2; }

wait_for_primary() {
  for attempt in $(seq 1 90); do
    if curl --noproxy '*' --silent --fail --max-time 2 \
      http://127.0.0.1:8000/api/v1/health/ready >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

cleanup() {
  docker rm -f "$proxy_name" >/dev/null 2>&1 || true
  docker rm -f "$peer_name" >/dev/null 2>&1 || true
  docker start "$primary_container" >/dev/null 2>&1 || true
  wait_for_primary >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker rm -f "$proxy_name" "$peer_name" >/dev/null 2>&1 || true
docker compose run -d --no-deps --name "$peer_name" api \
  uvicorn vav.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log >/dev/null

for attempt in $(seq 1 90); do
  peer_state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$peer_name")"
  if [[ "$peer_state" == "healthy" ]]; then
    break
  fi
  if [[ "$attempt" == 90 ]]; then
    echo "The HA peer did not become ready" >&2
    exit 1
  fi
  sleep 1
done

publish_address="127.0.0.1::8080"
if [[ -n "$proxy_port" ]]; then
  publish_address="127.0.0.1:${proxy_port}:8080"
fi
docker run -d --name "$proxy_name" \
  --network vav-platform_vav-public \
  -p "$publish_address" \
  -v "$repo_root/deploy/reverse-proxy/local-api-ha.conf:/etc/nginx/nginx.conf:ro" \
  nginx:1.27.4-alpine3.21 >/dev/null
if [[ -z "$proxy_port" ]]; then
  proxy_port="$(docker port "$proxy_name" 8080/tcp | sed 's/.*://')"
fi

for attempt in $(seq 1 60); do
  if curl --noproxy '*' --silent --fail --max-time 2 \
    "http://127.0.0.1:${proxy_port}/api/v1/health/ready" >/dev/null; then
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    echo "The local HA proxy did not become ready" >&2
    exit 1
  fi
  sleep 1
done

exercise_proxy() {
  local passed=0
  local failed=0
  local attempt
  for attempt in $(seq 1 "$request_count"); do
    if curl --noproxy '*' --silent --fail --max-time 3 \
      "http://127.0.0.1:${proxy_port}/api/v1/health/ready" >/dev/null; then
      passed=$((passed + 1))
    else
      failed=$((failed + 1))
    fi
  done
  printf '%s %s\n' "$passed" "$failed"
}

docker stop "$primary_container" >/dev/null
read -r primary_passed primary_failed < <(exercise_proxy)
docker start "$primary_container" >/dev/null
wait_for_primary || { echo "The primary API did not recover" >&2; exit 1; }

docker stop "$peer_name" >/dev/null
read -r peer_passed peer_failed < <(exercise_proxy)

status="PASS"
if (( primary_failed != 0 || peer_failed != 0 )); then
  status="FAIL"
fi

payload="$(printf '{"status":"%s","scenario":"local_api_active_active_failover","evidence_scope":"local_compose","production_certification":false,"started_at":"%s","completed_at":"%s","primary_outage":{"requests":%d,"passed":%d,"failed":%d},"peer_outage":{"requests":%d,"passed":%d,"failed":%d}}' \
  "$status" "$started_at" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "$request_count" "$primary_passed" "$primary_failed" \
  "$request_count" "$peer_passed" "$peer_failed")"

if [[ -n "$report_path" ]]; then
  mkdir -p "$(dirname "$report_path")"
  printf '%s\n' "$payload" > "$report_path"
fi
printf '%s\n' "$payload"
[[ "$status" == "PASS" ]]
