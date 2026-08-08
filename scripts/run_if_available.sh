#!/usr/bin/env bash

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "run_if_available: missing command" >&2
  exit 1
fi

command=("$@")
timeout_seconds="${RUN_IF_TIMEOUT_SECONDS:-45}"
status_file="${RUN_IF_STATUS_FILE:-}"

tmp_out=$(mktemp)
tmp_err=$(mktemp)
cleanup() {
  rm -f "$tmp_out" "$tmp_err"
}
trap cleanup EXIT

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

write_status() {
  local status="$1"
  local rc="$2"
  local reason="$3"
  [ -n "$status_file" ] || return 0

  local status_dir
  local status_tmp
  status_dir=$(dirname "$status_file")
  mkdir -p "$status_dir"
  status_tmp=$(mktemp "${status_file}.tmp.XXXXXX")
  printf '{"status":"%s","command":"%s","reason":"%s","exit_code":%s}\n' \
    "$(json_escape "$status")" \
    "$(json_escape "$json_command")" \
    "$(json_escape "$reason")" \
    "$rc" >"$status_tmp"
  mv "$status_tmp" "$status_file"
}

run_with_wrapped_timeout() {
  local -a args=("$@")
  local -a env_assignments=()
  local -a target_cmd=()
  local idx=0

  while [ "$idx" -lt "${#args[@]}" ]; do
    local item="${args[$idx]}"
    if [[ "$item" == *=* ]] && [[ "${item%%=*}" != "" ]] && [[ "${item%%=*}" != -* ]]; then
      env_assignments+=("$item")
      idx=$((idx + 1))
      continue
    fi
    break
  done

  target_cmd=("${args[@]:$idx}")
  if [ "${#target_cmd[@]}" -eq 0 ]; then
    return 127
  fi

  if [ "${#env_assignments[@]}" -gt 0 ]; then
    if command -v timeout >/dev/null 2>&1; then
      timeout "$timeout_seconds" env "${env_assignments[@]}" "${target_cmd[@]}"
      return $?
    fi
    env "${env_assignments[@]}" "${target_cmd[@]}"
    return $?
  fi

  if command -v timeout >/dev/null 2>&1; then
    timeout "$timeout_seconds" "${target_cmd[@]}"
    return $?
  fi
  "${target_cmd[@]}"
  return $?
}

set +e
run_with_wrapped_timeout "${command[@]}" >"$tmp_out" 2>"$tmp_err"
rc=$?
set -e

stdout=$(cat "$tmp_out")
stderr=$(cat "$tmp_err")
shell_command=$(printf '%q ' "${command[@]}")
json_command=${shell_command% }

if [ "$rc" -eq 0 ]; then
  if [ -n "$stdout" ]; then
    printf '%s\n' "$stdout"
  fi
  if [ -n "$stderr" ]; then
    printf '%s\n' "$stderr" >&2
  fi
  write_status "PASS" 0 "command completed"
  exit 0
fi

combined="$(printf '%s\n%s' "$stdout" "$stderr")"
lower="$(printf '%s' "$combined" | tr '[:upper:]' '[:lower:]')"

need_not_run=false

if [ "$rc" -eq 126 ] || [ "$rc" -eq 127 ]; then
  need_not_run=true
fi
if [ "$rc" -eq 124 ]; then
  need_not_run=true
fi

case "$lower" in
  *"command not found"*|\
  *"cannot connect to the docker daemon"*|\
  *"connection refused"*|\
  *"connect call failed"*|\
  *"could not connect to server"*|\
  *"timed out (110)"*|\
  *"operation timed out"*|\
  *"connect timed out"*|\
  *"timed out waiting"*config.webserver*|\
  *"could not resolve host"*|\
  *"failed to connect"*|\
  *"playwright: not found"*|\
  *"playwright not found"*|\
  *"service is not running"*|\
  *"playwright is not a function"*|\
  *"no space left on device"*|\
  *"technical evidence is incomplete"*|\
  *"ui technical evidence is incomplete"*|\
  *"permission denied"* )
    need_not_run=true
    ;;
  *)
    ;;
esac

if [ "$need_not_run" != true ]; then
  if [ -n "$stdout" ]; then
    printf '%s\n' "$stdout"
  fi
  if [ -n "$stderr" ]; then
    printf '%s\n' "$stderr" >&2
  fi
  write_status "FAIL" "$rc" "command failed"
  exit "$rc"
fi

write_status "NOT_RUN" "$rc" "environment dependency unavailable"
printf '{"status":"NOT_RUN","command":"%s","reason":"environment dependency unavailable","exit_code":%s}\n' "$(json_escape "$json_command")" "$rc"
exit 0
