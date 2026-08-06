#!/usr/bin/env bash
set -euo pipefail

checks=(
  "API|http://localhost:8000/api/v1/health/live|api"
  "API readiness|http://localhost:8000/api/v1/health/ready|api"
  "User web|http://localhost:5173|user-web"
  "Admin web|http://localhost:5174/admin/login|admin-web"
  "Mailpit|http://localhost:8025/readyz|mailpit"
  "MinIO|http://localhost:9000/minio/health/live|minio"
)

for entry in "${checks[@]}"; do
  name="${entry%%|*}"
  remainder="${entry#*|}"
  url="${remainder%%|*}"
  service="${remainder##*|}"
  ready=false
  for _ in $(seq 1 60); do
    if curl --noproxy "*" --silent --show-error --fail "$url" >/dev/null 2>&1; then
      ready=true
      break
    fi
    container_id="$(docker compose ps -q "$service")"
    if [[ -n "$container_id" ]] && [[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")" == "healthy" ]]; then
      ready=true
      break
    fi
    sleep 2
  done
  if [[ "$ready" != true ]]; then
    echo "$name did not become ready: $url" >&2
    exit 1
  fi
  echo "$name ready"
done
