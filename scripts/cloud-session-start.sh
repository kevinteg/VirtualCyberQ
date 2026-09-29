#!/usr/bin/env bash
# cloud-session-start.sh: the SessionStart hook (.claude/settings.json) for
# Claude Code cloud sessions. A no-op anywhere CLAUDE_CODE_REMOTE is not
# "true", so it does nothing on a developer machine.
#
# In a cloud session it runs `python3 -m pip install -e ".[dev]"`. When the
# system pip refuses (externally-managed-environment, PEP 668), it installs
# into a venv at .venv instead and puts .venv/bin first on PATH for later
# Bash commands via $CLAUDE_ENV_FILE. A .venv left by an earlier run is reused.
#
# Step output goes to a log file. On success one summary line is printed to
# stdout (it lands in Claude's context); on failure the failed step and the
# log's tail go to stderr and the hook exits 1, which the user sees.
set -euo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

# Catch-all for a failure outside run_step. No `set -E`: an inherited ERR trap
# fires on a function's ordinary non-zero return inside $(...).
step="start"
trap 'printf "cloud-session-start: step \"%s\" failed (line %s)\n" "$step" "$LINENO" >&2' ERR

log_file="$(mktemp "${TMPDIR:-/tmp}/cloud-session-start.XXXXXX")"

fail() {
  {
    printf 'cloud-session-start: step "%s" failed (exit %s).\n' "$step" "$1"
    printf 'Last lines of %s:\n' "$log_file"
    tail -n 40 "$log_file"
  } >&2
  exit 1
}

# run_step NAME CMD...: run CMD with its output in the log; on failure name
# the step, show the log's tail on stderr and exit 1.
run_step() {
  local rc=0
  step="$1"
  shift
  printf '\n==> %s\n' "$step" >>"$log_file"
  "$@" >>"$log_file" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || fail "$rc"
}

# Append an export line to $CLAUDE_ENV_FILE once.
persist() {
  [ -n "${CLAUDE_ENV_FILE:-}" ] || return 0
  grep -qxF "$1" "$CLAUDE_ENV_FILE" 2>/dev/null || printf '%s\n' "$1" >>"$CLAUDE_ENV_FILE"
}

# python3 -m venv needs Ubuntu's python3-venv; uv (in the cloud image) does not.
make_venv() {
  python3 -m venv .venv && return 0
  rm -rf .venv
  command -v uv >/dev/null && uv venv --python python3 --seed .venv
}

step="cd to the project directory"
project_dir="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$project_dir"

use_venv=false
if [ -x .venv/bin/python ]; then
  use_venv=true
else
  step='python3 -m pip install -e ".[dev]"'
  printf '\n==> %s\n' "$step" >>"$log_file"
  rc=0
  python3 -m pip install -e ".[dev]" >>"$log_file" 2>&1 || rc=$?
  if [ "$rc" -ne 0 ]; then
    grep -q "externally-managed-environment" "$log_file" || fail "$rc"
    run_step "create .venv (system pip is externally managed)" make_venv
    use_venv=true
  fi
fi

if [ "$use_venv" = true ]; then
  run_step '.venv/bin/python -m pip install -e ".[dev]"' .venv/bin/python -m pip install -e ".[dev]"
  step="put .venv/bin on PATH"
  export VIRTUAL_ENV="$project_dir/.venv"
  export PATH="$VIRTUAL_ENV/bin:$PATH"
  persist "export VIRTUAL_ENV=\"$VIRTUAL_ENV\""
  persist "export PATH=\"$VIRTUAL_ENV/bin:\$PATH\""
fi

printf 'cloud-session-start: %s; virtual-cyberq installed editable with [dev] extras%s (log: %s).\n' \
  "$(python3 --version 2>&1)" "$([ "$use_venv" = true ] && printf ' in .venv' || true)" "$log_file"
