# Shared helpers for test.sh: output, prompts, traps and cleanup.
# Sourced by test.sh, never executed directly.
# shellcheck shell=bash

if [[ -t 1 ]]; then
  IS_TTY_OUTPUT=1
else
  IS_TTY_OUTPUT=0
fi
: "${NO_COLOR:=0}"

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

step() {
  if [[ "$IS_TTY_OUTPUT" -eq 1 && "$NO_COLOR" != "1" && "${TERM:-}" != "dumb" ]]; then
    printf '\n\033[1;36m==>\033[0m \033[1m%s\033[0m\n' "$1"
  else
    printf '\n==> %s\n' "$1"
  fi
}

note() {
  printf '    %s\n' "$1"
}

require_command() {
  local name="$1" remediation="$2"
  command -v "$name" >/dev/null 2>&1 || fail "missing required command '$name' — $remediation"
}

# Returns 0 only on an explicit yes; anything else (including EOF) is a no.
ask_yes_no() {
  local prompt="$1" answer
  [[ "${IS_INTERACTIVE:-0}" == "1" ]] || return 1
  printf '%s [y/N] ' "$prompt"
  read -r answer || return 1
  case "$answer" in
    y | Y | yes | YES | Yes) return 0 ;;
    *) return 1 ;;
  esac
}

TEST_TEMP_DIRS=()
CLEANUP_DONE=0

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  [[ "$CLEANUP_DONE" == 1 ]] && exit "$status"
  CLEANUP_DONE=1
  if ((${#TEST_TEMP_DIRS[@]})); then
    rm -rf "${TEST_TEMP_DIRS[@]}"
  fi
  exit "$status"
}

# SIGINT/SIGTERM fail loudly so an aborted run never exits 0; the EXIT trap
# (not a direct call) then runs cleanup on that path too.
on_interrupt() {
  fail "interrupted"
}

setup_traps() {
  trap cleanup EXIT
  trap on_interrupt INT TERM
}

register_temp_dir() {
  TEST_TEMP_DIRS+=("$1")
}
