#!/usr/bin/env bash
set -euo pipefail

service="${SERVICE:-}"
case "$service" in api|worker|scheduler|redis|minio) ;; *) echo "SERVICE must be api, worker, scheduler, redis, or minio" >&2; exit 2 ;; esac
[[ "${CHAOS_CONFIRM:-}" == "local-vav-compose-only" ]] || {
  echo "Set CHAOS_CONFIRM=local-vav-compose-only to run a scoped local drill" >&2; exit 2;
}
container="$(docker compose ps -q "$service")"
test -n "$container" || { echo "Service is not running: $service" >&2; exit 2; }
project="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$container")"
[[ "$project" == "vav-platform" ]] || { echo "Refusing non-VAV container: $container" >&2; exit 2; }

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
docker compose stop "$service"
if [[ "$service" == "api" ]]; then
  if curl --silent --fail --max-time 2 http://localhost:8000/api/v1/health/live >/dev/null; then
    echo "API remained reachable despite stopping its only local instance" >&2
    exit 1
  fi
fi
docker compose start "$service"
for attempt in $(seq 1 60); do
  state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container")"
  [[ "$state" == "healthy" || "$state" == "running" ]] && break
  if [[ "$attempt" == 60 ]]; then echo "Service did not recover: $service ($state)" >&2; exit 1; fi
  sleep 1
done
printf '{"status":"PASS","scenario":"%s_failure","started_at":"%s","recovered_at":"%s"}\n' \
  "$service" "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
