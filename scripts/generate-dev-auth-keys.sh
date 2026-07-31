#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
secret_dir="$project_root/.dev-secrets"
private_key="$secret_dir/auth-private.pem"
public_key="$secret_dir/auth-public.pem"

mkdir -p "$secret_dir"
chmod 700 "$secret_dir"

if [[ ! -s "$private_key" ]]; then
  openssl genpkey -algorithm ED25519 -out "$private_key"
  chmod 600 "$private_key"
fi

if [[ ! -s "$public_key" ]]; then
  openssl pkey -in "$private_key" -pubout -out "$public_key"
  chmod 644 "$public_key"
fi

echo "Development Ed25519 key pair is ready in .dev-secrets"
