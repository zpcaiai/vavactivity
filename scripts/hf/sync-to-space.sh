#!/usr/bin/env bash

set -euo pipefail

HF_SYNC_DRY_RUN="${HF_SYNC_DRY_RUN:-0}"

if [ "${HF_SYNC_DRY_RUN}" != "1" ] && [ -z "${HF_TOKEN:-}" ]; then
  echo "HF_TOKEN is required in environment." >&2
  exit 1
fi

HF_SPACE_REPO="${HF_SPACE_REPO:-StephenZao/vavactivity}"
HF_TARGET_BRANCH="${HF_TARGET_BRANCH:-main}"
SOURCE_BRANCH="${1:-${GITHUB_REF_NAME:-main}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SYNC_DIR="$(mktemp -d)"
trap 'rm -rf "${SYNC_DIR}"' EXIT

echo "Preparing clean snapshot for ${HF_SPACE_REPO} (${HF_TARGET_BRANCH}) from ${SOURCE_BRANCH}"
if ! git -C "${REPO_ROOT}" rev-parse --verify "${SOURCE_BRANCH}^{commit}" >/dev/null 2>&1; then
  echo "Source branch or commit does not exist: ${SOURCE_BRANCH}" >&2
  exit 1
fi
SOURCE_COMMIT="$(git -C "${REPO_ROOT}" rev-parse "${SOURCE_BRANCH}^{commit}")"

# Build the deployment from the requested committed revision. This prevents local
# build products, transfer archives and other untracked files from leaking into
# the Space snapshot.
git -C "${REPO_ROOT}" archive --format=tar "${SOURCE_BRANCH}" | tar -xf - -C "${SYNC_DIR}"

rm -rf "${SYNC_DIR}/.github" "${SYNC_DIR}/_to_delete" "${SYNC_DIR}/_transfer" \
  "${SYNC_DIR}/artifacts" "${SYNC_DIR}/apps/design-system/storybook-static"

rm -f \
  "${SYNC_DIR}/apps/user-web/src/assets/images/vav-hero-couple.png" \
  "${SYNC_DIR}/tests/ui/visual.spec.ts-snapshots/desktop-light-chromium-darwin.png" \
  "${SYNC_DIR}/tests/ui/visual.spec.ts-snapshots/mobile-light-chromium-darwin.png" \
  "${SYNC_DIR}/tests/ui/visual.spec.ts-snapshots/tablet-dark-chromium-darwin.png" \
  "${SYNC_DIR}/tests/ui/visual.spec.ts-snapshots/wide-high-contrast-chromium-darwin.png" \
  "${SYNC_DIR}/_to_delete/_vav-batch13.tgz" \
  "${SYNC_DIR}/_to_delete/_vav-src.tgz"

if [ -f "${SYNC_DIR}/apps/user-web/src/assets/main.css" ]; then
  python3 - <<PY
from pathlib import Path

css_path = Path("${SYNC_DIR}") / "apps/user-web/src/assets/main.css"
content = css_path.read_text(encoding="utf-8")
content = content.replace('url("./images/vav-hero-couple.png")', 'none')
content = content.replace("url('./images/vav-hero-couple.png')", 'none')
css_path.write_text(content, encoding="utf-8")
PY
fi

for file in \
  "${SYNC_DIR}/apps/user-web/src/assets/images/vav-hero-couple.png" \
  "${SYNC_DIR}/tests/ui/visual.spec.ts-snapshots/desktop-light-chromium-darwin.png" \
  "${SYNC_DIR}/tests/ui/visual.spec.ts-snapshots/mobile-light-chromium-darwin.png" \
  "${SYNC_DIR}/tests/ui/visual.spec.ts-snapshots/tablet-dark-chromium-darwin.png" \
  "${SYNC_DIR}/tests/ui/visual.spec.ts-snapshots/wide-high-contrast-chromium-darwin.png" \
  "${SYNC_DIR}/_to_delete/_vav-batch13.tgz" \
  "${SYNC_DIR}/_to_delete/_vav-src.tgz"; do
  if [ -f "${file}" ]; then
    echo "Forbidden artifact still present: ${file}" >&2
    exit 1
  fi
done

git -C "${SYNC_DIR}" init -b "${HF_TARGET_BRANCH}" >/dev/null

git -C "${SYNC_DIR}" config user.name "github-actions[bot]"
git -C "${SYNC_DIR}" config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git -C "${SYNC_DIR}" add .

BINARY_FILES="$(git -C "${SYNC_DIR}" diff --cached --numstat | awk '$1 == "-" || $2 == "-" {print $3}')"
if [ -n "${BINARY_FILES}" ]; then
  echo "Refusing to push binary files without Xet storage:" >&2
  printf '%s\n' "${BINARY_FILES}" >&2
  exit 1
fi

if [ "${HF_SYNC_DRY_RUN}" = "1" ]; then
  echo "HF sync dry run passed for ${SOURCE_BRANCH}: $(git -C "${SYNC_DIR}" diff --cached --name-only | wc -l | tr -d ' ') files"
  exit 0
fi

git -C "${SYNC_DIR}" commit \
  -m "Deploy ${SOURCE_BRANCH} (${SOURCE_COMMIT}) to Hugging Face Space" \
  --allow-empty

git -C "${SYNC_DIR}" remote add hf "https://huggingface.co/spaces/${HF_SPACE_REPO}.git"

# Hugging Face's REST API accepts a Bearer token, while Git smart HTTP uses
# HTTP Basic authentication (account name + access token as the password).
# Resolve the account name from the token so the workflow never needs a second
# secret and keep both credentials out of the remote URL and command output.
HF_USERNAME="$(curl --fail --silent --show-error \
  --header "Authorization: Bearer ${HF_TOKEN}" \
  https://huggingface.co/api/whoami-v2 | \
  python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
if [ -z "${HF_USERNAME}" ]; then
  echo "HF_TOKEN is valid but its account name could not be resolved." >&2
  exit 1
fi
export HF_USERNAME HF_TOKEN
HF_CREDENTIAL_HELPER='!f() { if [ "$1" = get ]; then printf "%s\n" "username=$HF_USERNAME" "password=$HF_TOKEN"; fi; }; f'

GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
git -C "${SYNC_DIR}" \
  -c "credential.helper=${HF_CREDENTIAL_HELPER}" \
  -c "credential.interactive=0" \
  -c "http.version=HTTP/1.1" \
  push hf "HEAD:refs/heads/${HF_TARGET_BRANCH}" --force

REMOTE_HEAD="$(GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
  git -C "${SYNC_DIR}" \
  -c "credential.helper=${HF_CREDENTIAL_HELPER}" \
  -c "credential.interactive=0" \
  -c "http.version=HTTP/1.1" \
  ls-remote hf "refs/heads/${HF_TARGET_BRANCH}" | awk '{print $1}')"
if [ -z "${REMOTE_HEAD}" ]; then
  echo "HF push completed but the remote branch could not be verified." >&2
  exit 1
fi

# A Space previously configured for ZeroGPU cannot start after migrating to the
# Docker SDK because Hugging Face only supports ZeroGPU for Gradio. Repair only
# that exact invalid state; never overwrite a valid user-selected hardware tier.
SPACE_STATE="$(curl --fail --silent --show-error \
  --header "Authorization: Bearer ${HF_TOKEN}" \
  "https://huggingface.co/api/spaces/${HF_SPACE_REPO}")"
if printf '%s' "${SPACE_STATE}" | python3 -c '
import json
import sys

runtime = (json.load(sys.stdin).get("runtime") or {})
is_invalid_zero_gpu = (
    (runtime.get("hardware") or {}).get("requested") == "zero-a10g"
    and runtime.get("errorMessage") == "ZeroGPU is only available on Gradio SDK"
)
raise SystemExit(0 if is_invalid_zero_gpu else 1)
'; then
  echo "Repairing incompatible ZeroGPU + Docker configuration with cpu-basic hardware"
  curl --fail --silent --show-error \
    --request POST \
    --header "Authorization: Bearer ${HF_TOKEN}" \
    --header "Content-Type: application/json" \
    --data '{"flavor":"cpu-basic"}' \
    "https://huggingface.co/api/spaces/${HF_SPACE_REPO}/hardware" >/dev/null
fi

echo "HF sync complete to ${HF_SPACE_REPO}@${HF_TARGET_BRANCH} (${REMOTE_HEAD})"
