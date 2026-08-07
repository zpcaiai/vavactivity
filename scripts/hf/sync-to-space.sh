#!/usr/bin/env bash

set -euo pipefail

if [ -z "${HF_TOKEN:-}" ]; then
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
rsync -a \
  --delete \
  --exclude=".git" \
  --exclude=".github" \
  --exclude=".venv" \
  --exclude="node_modules" \
  --exclude="tests/ui/visual.spec.ts-snapshots" \
  --exclude="apps/user-web/src/assets/images/vav-hero-couple.png" \
  --exclude="_to_delete" \
  "${REPO_ROOT}/" "${SYNC_DIR}/"

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
git -C "${SYNC_DIR}" commit -m "Deploy ${SOURCE_BRANCH} to Hugging Face Space" --allow-empty

git -C "${SYNC_DIR}" remote add hf "https://huggingface.co/spaces/${HF_SPACE_REPO}.git"

GIT_TERMINAL_PROMPT=0 git -C "${SYNC_DIR}" \
  -c "credential.helper=" \
  -c "credential.interactive=0" \
  -c "http.https://huggingface.co/.extraheader=Authorization: Bearer ${HF_TOKEN}" \
  push hf "HEAD:refs/heads/${HF_TARGET_BRANCH}" --force

echo "HF sync complete to ${HF_SPACE_REPO}@${HF_TARGET_BRANCH}"
