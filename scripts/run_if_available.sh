#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail

if [ "$#" -lt 1 ]; then
  echo "run_if_available: missing command" >&2
  exit 1
fi

command=("$@")
cmd_text="${command[*]}"

tmp_out=$(mktemp)
tmp_err=$(mktemp)
cleanup() {
  rm -f "$tmp_out" "$tmp_err"
}
trap cleanup EXIT

set +e
"${command[@]}" >"$tmp_out" 2>"$tmp_err"
rc=$?
set -e

audit=$(cat "$tmp_out")
err_out=$(cat "$tmp_err")
if [ -n "$audit" ]; then
  printf '%s\n' "$audit"
fi
if [ -n "$err_out" ]; then
  printf '%s\n' "$err_out" >&2
fi

if [ "$rc" -eq 0 ]; then
  exit 0
fi

combined="$(printf '%s\n%s' "$audit" "$err_out")"
lower=$(printf '%s' "$combined" | tr '[:upper:]' '[:lower:]')

need_not_run=0
for pattern in \
  "no such file or directory" \
  "command not found" \
  "filenotfound" \
  "filenotfound" \
  "unable to locate" \
  "cannot connect to the docker daemon" \
  "can\x27t connect to the docker daemon" \
  "docker daemon" \
  "service .* is not running" \
  "connection refused" \
  "ecconnrefused" \
  "failed to connect" \
  "unavailable" \
  "no space left on device" \
  "modulenotfounderror" \
  "filenotfounderror" \
  "cannot import name" \
  "could not find" \
  "operation timed out" \
  "connect timed out" \
  "playwright: not found" \
  "docker: not found"
  do
    if printf '%s' "$lower" | grep -E -q "$pattern"; then
      need_not_run=1
      break
    fi
  done

if [ "$need_not_run" -eq 1 ]; then
  echo "{\"status\": \"NOT_RUN\", \"command\": \"$cmd_text\", \"reason\": \"environment dependency unavailable\", \"exit_code\": $rc}"
  exit 0
fi

exit "$rc"
