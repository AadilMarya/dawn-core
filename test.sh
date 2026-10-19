#!/usr/bin/env bash
# Build, verify, sign, install and health-check DAWN Core in one command.
# (The machine test suite is pytest — this is the human path: it produces the two
# distributions, proves them in a fresh environment, installs the Remote Script into
# Live and checks that Live answers.)
#
# Five stages, each announced with a banner: Preflight, Build, Verify, Sign,
# Install → Open. Interactive by default; -y accepts defaults for CI (it never opens Live).
# Every prompt has an environment-variable override; see --help.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
# shellcheck source=scripts/lib/common.sh
source "$REPO_ROOT/scripts/lib/common.sh"

APP="DAWN Core"
YES="${DAWN_CORE_TEST_YES:-0}"
CLEAN="${DAWN_CORE_TEST_CLEAN:-0}"
NO_LAUNCH="${DAWN_CORE_TEST_NO_LAUNCH:-0}"
SKIP_SYNC="${DAWN_CORE_TEST_SKIP_SYNC:-0}"
PYTHON_SPEC="${DAWN_CORE_TEST_PYTHON:-}"
DEST="${DAWN_CORE_TEST_DEST:-}"
DIST_DIR="${DAWN_CORE_TEST_DIST_DIR:-$REPO_ROOT/dist}"
IS_INTERACTIVE=0
VERSION=""
VERIFY_ROOT=""
VERIFY_PY=""
SCRIPT_DEST=""
LIVE_CHECK="skipped"

print_help() {
  cat <<'EOF'
Usage: ./test.sh [options]

Builds the two distributions (dawn-osc, dawn-core), verifies them in a fresh
environment, installs the Remote Script into Live's Remote Scripts folder, and
health-checks the result.

With no arguments it is interactive where a choice exists. -y/--yes accepts the
defaults for CI: it replaces an existing install and never opens Live.

Options:
  -y, --yes           Non-interactive; accept defaults for unset options
  --clean             Remove the dist directory before building
  --no-launch         Skip opening Live and the Live health check
  --dest DIR          Remote Scripts folder to install into
  -h, --help          Show this help

Environment:
  DAWN_CORE_TEST_YES=1           Same as --yes
  DAWN_CORE_TEST_CLEAN=1         Same as --clean
  DAWN_CORE_TEST_NO_LAUNCH=1     Same as --no-launch
  DAWN_CORE_TEST_DEST            Same as --dest
  DAWN_CORE_TEST_DIST_DIR        Output directory (default: dist/)
  DAWN_CORE_TEST_PYTHON          Python for the verify environment
                                      (default: the workspace's .python-version)
  DAWN_CORE_TEST_SKIP_SYNC=1     Reuse the existing .venv instead of `uv sync`

Examples:
  ./test.sh                            # interactive: build, verify, install, open Live
  ./test.sh -y                         # non-interactive defaults (never opens Live)
  ./test.sh --clean --no-launch        # fresh build, stop after the install stage
  ./test.sh --dest /tmp/scripts-check  # install into a throwaway folder
EOF
}

parse_args() {
  local arg
  while (($# > 0)); do
    arg="$1"
    shift
    case "$arg" in
      --help | -h)
        print_help
        exit 0
        ;;
      --yes | -y | --non-interactive) YES=1 ;;
      --clean) CLEAN=1 ;;
      --no-launch) NO_LAUNCH=1 ;;
      --dest)
        [[ $# -gt 0 && "$1" != -* ]] || fail "--dest requires a directory"
        DEST="$1"
        shift
        ;;
      --dest=*) DEST="${arg#*=}" ;;
      *)
        printf 'error: unknown option %s\n' "$arg" >&2
        exit 2
        ;;
    esac
  done
}

# ---------------------------------------------------------------------------
# Stage 1 — Preflight
# ---------------------------------------------------------------------------

stage_preflight() {
  step "Preflight: toolchains and the workspace environment"
  require_command uv "install uv: https://docs.astral.sh/uv/"
  note "$(uv --version)"
  if [[ "$SKIP_SYNC" == 1 ]]; then
    note "reusing the existing environment (DAWN_CORE_TEST_SKIP_SYNC=1)"
  else
    uv sync --all-packages --extra dev
  fi
  local python_bin
  python_bin="$(uv run python -c 'import sys; print(sys.executable)')"
  note "python $("$python_bin" -c 'import sys; print(sys.version.split()[0])') ($python_bin)"
  VERSION="$(sed -n 's/^version = "\([0-9][^"]*\)"$/\1/p' "$REPO_ROOT/dawn_core/pyproject.toml" | head -n 1)"
  [[ -n "$VERSION" ]] || fail "cannot read the version from dawn_core/pyproject.toml"
  note "version $VERSION"
}

# ---------------------------------------------------------------------------
# Stage 2 — Build
# ---------------------------------------------------------------------------

stage_build() {
  step "Build: the two distributions"
  if [[ "$CLEAN" == 1 ]]; then
    rm -rf "$DIST_DIR"
    note "removed $DIST_DIR"
  fi
  uv build --all-packages --out-dir "$DIST_DIR"
  local project
  for project in dawn_osc dawn_core; do
    compgen -G "$DIST_DIR/$project-*.whl" >/dev/null ||
      fail "build did not produce a $project wheel in $DIST_DIR"
    compgen -G "$DIST_DIR/$project-*.tar.gz" >/dev/null ||
      fail "build did not produce a $project sdist in $DIST_DIR"
  done
  note "wheels and sdists are in $DIST_DIR"
}

# Newest artifact matching a glob, so a stale dist never reaches Verify.
newest() {
  local newest_file=""
  newest_file="$(ls -t "$@" 2>/dev/null | head -n 1)" || true
  [[ -n "$newest_file" ]] || fail "no artifact matches $*"
  printf '%s' "$newest_file"
}

# ---------------------------------------------------------------------------
# Stage 3 — Verify
# ---------------------------------------------------------------------------

stage_verify() {
  step "Verify: install the built artifacts into a fresh environment"
  local tmp_root="${TMPDIR:-/tmp}"
  VERIFY_ROOT="$(mktemp -d "${tmp_root%/}/dawn-core-verify.XXXXXX")"
  register_temp_dir "$VERIFY_ROOT"
  if [[ -n "$PYTHON_SPEC" ]]; then
    uv venv --python "$PYTHON_SPEC" "$VERIFY_ROOT/venv"
  else
    uv venv "$VERIFY_ROOT/venv"
  fi
  VERIFY_PY="$VERIFY_ROOT/venv/bin/python"

  local wheel_sdk wheel_core
  wheel_sdk="$(newest "$DIST_DIR"/dawn_osc-*.whl)"
  wheel_core="$(newest "$DIST_DIR"/dawn_core-*.whl)"
  uv pip install --quiet --python "$VERIFY_PY" "$wheel_sdk" "$wheel_core"
  note "installed $(basename "$wheel_sdk"), $(basename "$wheel_core")"

  "$VERIFY_PY" - <<'PY'
import importlib.metadata as metadata
import pathlib

import dawn_core
import dawn_osc

assert dawn_core.__version__ == metadata.version("dawn-core"), "version mismatch"
script = dawn_osc.script_dir()
for rel in ("manager.py", "handlers/track.py", "pythonosc/osc_message.py", "README.md"):
    assert (script / rel).is_file(), f"Remote Script payload is missing {rel}"
for package in (dawn_osc, dawn_core):
    assert (pathlib.Path(package.__file__).parent / "py.typed").is_file(), f"{package.__name__}/py.typed missing"

prompt_dir = pathlib.Path(dawn_core.__file__).parent / "prompt"
for section in ("persona", "production", "arrangement", "mixing", "sound_design", "ableton"):
    assert (prompt_dir / f"{section}.md").is_file(), f"prompt/{section}.md missing from the wheel"

installed = {dist.metadata["Name"].lower() for dist in metadata.distributions()}
assert "dawn-c" not in installed, "dawn-c must not be installed"
assert "mcp" not in installed, "mcp must not be installed"
entries = metadata.entry_points(group="console_scripts")
assert not [e for e in entries if e.name == "dawn-core"], "the CLI must not ship"
print(f"imports, versions, payload and absence of CLI/MCP verified (dawn_core {dawn_core.__version__})")
PY

  # The shipped catalog is checked against the shipped Remote Script payload.
  "$VERIFY_PY" -m dawn_core._gen_catalog --check | tail -n 1

  local sdist
  for sdist in "$DIST_DIR"/dawn_osc-*.tar.gz "$DIST_DIR"/dawn_core-*.tar.gz; do
    tar -tzf "$sdist" | grep -q '/pyproject.toml$' ||
      fail "sdist has no pyproject.toml: $sdist"
  done
  note "sdists carry their pyproject.toml"

  step "Verify: SHA-256 digests of the artifacts"
  if command -v shasum >/dev/null 2>&1; then
    (cd "$DIST_DIR" && shasum -a 256 ./*.whl ./*.tar.gz)
  else
    (cd "$DIST_DIR" && sha256sum ./*.whl ./*.tar.gz)
  fi
}

# ---------------------------------------------------------------------------
# Stage 4 — Sign
# ---------------------------------------------------------------------------

stage_sign() {
  step "Sign: platform signing"
  note "skipped: these are pure-Python distributions, not signed platform binaries."
  note "pip verifies the wheel hashes; the SHA-256 digests above are the release record."
}

# ---------------------------------------------------------------------------
# Stage 5 — Install → Open
# ---------------------------------------------------------------------------

script_matches_dest() {
  "$VERIFY_PY" - "$SCRIPT_DEST" <<'PY'
import sys
from pathlib import Path

from dawn_core.remote_script import script_matches

sys.exit(0 if script_matches(Path(sys.argv[1])) else 1)
PY
}

install_remote_script() {
  local force="$1"
  DAWN_FORCE="$force" "$VERIFY_PY" - "$DEST" <<'PY'
import os
import sys
from pathlib import Path

from dawn_core.remote_script import install_script

for step in install_script(Path(sys.argv[1]), force=os.environ.get("DAWN_FORCE") == "1"):
    print(step)
PY
}

run_doctor() {
  local status=0
  "$VERIFY_PY" - "$DEST" <<'PY' || status=$?
import sys
from pathlib import Path

from dawn_core.remote_script import check_install

report = check_install(Path(sys.argv[1]))
for line in report.lines():
    print(line)
sys.exit(0 if report.ok else 1)
PY
  return "$status"
}

open_live() {
  open -b com.ableton.live >/dev/null 2>&1 ||
    open -a "Ableton Live" >/dev/null 2>&1
}

stage_install_open() {
  step "Install: the Remote Script into Live's Remote Scripts folder"
  if [[ -z "$DEST" ]]; then
    DEST="$("$VERIFY_PY" -c 'from dawn_core.remote_script import default_remote_scripts_dir; print(default_remote_scripts_dir())')"
  fi
  SCRIPT_DEST="$DEST/DAWN"
  note "target: $SCRIPT_DEST"

  if script_matches_dest; then
    note "already installed and matches the packaged copy"
  elif [[ -e "$SCRIPT_DEST" ]]; then
    if [[ "$YES" == 1 ]]; then
      note "replacing the existing install (the old copy is kept as DAWN.bak-<timestamp>)"
      install_remote_script 1
    elif ask_yes_no "An install exists at $SCRIPT_DEST and differs. Replace it (a backup is kept)?"; then
      install_remote_script 1
    else
      note "kept the existing install; nothing was written"
      LIVE_CHECK="not checked (install kept)"
    fi
  else
    install_remote_script 0
  fi
  if script_matches_dest; then
    note "the installed copy matches the packaged Remote Script"
  fi

  step "Open: health-check the control surface"
  if [[ "$LIVE_CHECK" == "not checked (install kept)" ]]; then
    LIVE_CHECK="skipped (install kept)"
    note "skipped: the existing install was kept, so it was not re-checked"
    return 0
  fi
  if [[ "$NO_LAUNCH" == 1 ]]; then
    LIVE_CHECK="skipped (--no-launch)"
    note "skipped (--no-launch)"
    return 0
  fi
  if run_doctor; then
    LIVE_CHECK="PASS"
    note "Live answered: the DAWN control surface is live"
    return 0
  fi
  if [[ "$YES" == 1 || "$IS_INTERACTIVE" != 1 ]]; then
    LIVE_CHECK="not running"
    note "Live did not answer; skipped opening it (non-interactive)"
    note "start Live and select DAWN under Settings > Link, Tempo & MIDI > Control Surface,"
    note "then re-run: ./test.sh --dest \"$DEST\""
    return 0
  fi
  if ask_yes_no "Live is not answering. Open Ableton Live now?"; then
    open_live || note "could not open Live automatically; open it manually"
    local attempt
    for attempt in $(seq 1 30); do
      sleep 2
      if run_doctor; then
        LIVE_CHECK="PASS"
        note "Live answered: the DAWN control surface is live"
        return 0
      fi
    done
    LIVE_CHECK="did not answer"
    note "Live did not answer yet."
    note "If this is the first run, select DAWN under Settings > Link, Tempo & MIDI > Control Surface."
  else
    LIVE_CHECK="skipped (Live not opened)"
    note "skipped opening Live"
  fi
}

# ---------------------------------------------------------------------------

main() {
  local started=$SECONDS
  parse_args "$@"
  if [[ "$YES" != 1 && -t 0 && -t 1 ]]; then
    IS_INTERACTIVE=1
  fi
  setup_traps

  stage_preflight
  stage_build
  stage_verify
  stage_sign
  stage_install_open

  printf '\n%s %s ready in %ds.\n' "$APP" "$VERSION" "$((SECONDS - started))"
  printf '  distributions: %s\n' "$DIST_DIR"
  printf '  Remote Script: %s\n' "$SCRIPT_DEST"
  printf '  Live check:    %s\n' "$LIVE_CHECK"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
