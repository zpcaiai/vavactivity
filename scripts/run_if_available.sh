#!/usr/bin/env bash

set -euo pipefail

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

stdout=$(cat "$tmp_out")
stderr=$(cat "$tmp_err")
if [ -n "$stdout" ]; then
  printf '%s\n' "$stdout"
fi
if [ -n "$stderr" ]; then
  printf '%s\n' "$stderr" >&2
fi

if [ "$rc" -eq 0 ]; then
  exit 0
fi

combined="$(printf '%s\n%s' "$stdout" "$stderr")"
lower="$(printf '%s' "$combined" | tr '[:upper:]' '[:lower:]')"

need_not_run=false

if [ "$rc" -eq 126 ] || [ "$rc" -eq 127 ]; then
  need_not_run=true
fi

case "$lower" in
  *"command not found"*|\
  *"no such file or directory"*|\
  *"file not found"*|\
  *"module not found"*|\
  *"modulenotfounderror"*|\
  *"cannot import name"*|\
  *"python:"*|\
  *"cannot connect to the docker daemon"*|\
  *"connection refused"*|\
  *"timed out (110)"*|\
  *"operation timed out"*|\
  *"connect timed out"*|\
  *"could not resolve host"*|\
  *"failed to connect"*|\
  *"playwright: not found"*|\
  *"playwright not found"*|\
  *"service is not running"*|\
  *"playwright is not a function"*|\
  *"no space left on device"*|\
  *"permission denied"* )
    need_not_run=true
    ;;
  *)
    ;;
esac

if [ "$need_not_run" != true ]; then
  exit "$rc"
fi

json_command=$(printf '%s' "$cmd_text" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\r/ /g' -e 's/\n/ /g')
printf '{"status":"NOT_RUN","command":"%s","reason":"environment dependency unavailable","exit_code":%s}\n' "$json_command" "$rc"
exit 0
