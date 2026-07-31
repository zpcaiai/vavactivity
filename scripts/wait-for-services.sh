#!/usr/bin/env bash
set -euo pipefail

checks=(
  "API|http://localhost:8000/api/v1/health/live"
  "API readiness|http://localhost:8000/api/v1/health/ready"
  "User web|http://localhost:5173"
  "Admin web|http://localhost:5174/admin/login"
  "Mailpit|http://localhost:8025/readyz"
  "MinIO|http://localhost:9000/minio/health/live"
)

for entry in "${checks[@]}"; do
  name="${entry%%|*}"
  url="${entry#*|}"
  ready=false
  for _ in $(seq 1 60); do
    if curl --noproxy "*" --silent --show-error --fail "$url" >/dev/null 2>&1; then
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
