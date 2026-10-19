# Module: test.sh harness & release gates

> `./test.sh` is the human path (build → verify → sign → install → open); pytest is the machine path. This page lists both plus the scan constraints that break builds.

## `./test.sh`

- Layout: `test.sh` (entry, five stages) + `scripts/lib/common.sh` (fail/step/note, prompts,
  traps, cleanup). `set -euo pipefail`; cleanup on EXIT, interrupt trap on INT/TERM; artifact
  and install locations plus elapsed time on the last lines.
- Stages:
  1. **Preflight** — requires `uv`, syncs the workspace (`uv sync --all-packages --extra dev`,
     skip with `DAWN_CORE_TEST_SKIP_SYNC=1`), reports interpreter and version.
  2. **Build** — `uv build --all-packages --out-dir dist`; hard-fails when any of the four
     artifacts is missing. `--clean` wipes `dist/` first.
  3. **Verify** — fresh `uv venv`; installs the two built wheels; asserts metadata version
     equals `dawn_core.__version__`, Remote Script payload files and `py.typed` present,
     **no `dawn-core` console script**, **no `dawn-c` or `mcp` distribution**, catalog
     `--check` against the *installed* payload, sdists carry `pyproject.toml`; prints
     SHA-256 digests.
  4. **Sign** — skip note (pure-Python; pip hash verification is the integrity story).
  5. **Install → Open** — `install_script()` (transactional; replaces only with `force`,
     backup `DAWN.bak-<timestamp>`); re-verifies the installed tree; runs
     `check_install()` and, interactively, offers to open Live and polls up to 60 s.
- Options: `-y/--yes`, `--clean`, `--no-launch`, `--dest DIR`, `-h/--help`; unknown option →
  exit 2. Exit code 2 also for bad `--dest` usage. Env overrides:
  `DAWN_CORE_TEST_{YES,CLEAN,NO_LAUNCH,DEST,DIST_DIR,PYTHON,SKIP_SYNC}`.
- `-y` never opens Live; when Live is not running the harness reports
  `Live check: not running` and exits 0 (Live is an external app, not part of the build).

## The gates (all must be green)

```bash
uv sync --all-packages --extra dev
uv run pytest                                      # ~264 tests
uv run ruff check .
uv run ruff format --check .
uv run mypy dawn_core/src
uv run mypy dawn_osc/src/dawn_osc/transport.py \
    dawn_osc/src/dawn_osc/security.py dawn_osc/src/dawn_osc/__init__.py
uv run python -m dawn_core._gen_catalog --check
uv build --all-packages
./test.sh -y --no-launch --dest <throwaway>
```

- The toolchain lives in the root `dev` dependency group (`pytest`, `ruff`, `mypy`), so
  CI and a fresh checkout lint with the same pinned versions instead of whatever is on
  the machine's PATH. A dependency group is not a runtime dependency: neither
  distribution ships it.
- mypy scope: hand-written packages only. `remote_script/DAWN` imports `Live` (exists only
  inside Live) and is excluded from mypy.
- ruff excludes `remote_script/**` (formatting) and the vendored OSC runtime (everything).
- CI runs the pytest/ruff/mypy/catalog/build/wheel gates on 3.11–3.13, plus the macOS
  harness with `--no-launch`.

## Releasing

- Tagging `v*` runs `release.yml`: it builds the distributions, extracts the matching
  changelog section and creates the GitHub release with the artifacts attached.
- PyPI is **not** published by a tag. `publish.yml` is manually triggered and takes the
  tag as an input, so a release cannot reach PyPI before the trusted publisher exists.
- **PyPI is deferred.** The `pypi` environment exists on the repository with the owner as
  its required reviewer, and `publish.yml` is ready, but no trusted publisher is
  registered on PyPI, so the upload would be rejected. `dawn-core` and `dawn-osc` are
  both unclaimed on PyPI.
- Until then, the install path is the release wheels:

  ```bash
  pip install \
    "dawn-osc @ https://github.com/AadilMarya/dawn-core/releases/download/v0.1.0/dawn_osc-0.1.0-py3-none-any.whl" \
    "dawn-core[openai] @ https://github.com/AadilMarya/dawn-core/releases/download/v0.1.0/dawn_core-0.1.0-py3-none-any.whl"
  ```

  Both distributions are named because the agent depends on the transport. Installing
  `dawn-core` alone fails: pip cannot resolve `dawn-osc` from an index that has not
  published it.
- The public baseline is 0.1.0; the internal repository is not a publish target.

## Scan constraints that break the suite (learned the hard way)

`dawn_core/tests/test_licensing.py` walks **every text file in the repo**, tracked or
not (`dist/` binaries are skipped by a NUL-byte check, not by path):

- upstream project names and author names may appear **only** in `THIRD_PARTY_NOTICES.md`
  files — never in READMEs, changelogs, the wiki, commit scratch files or scripts;
- the legacy private identifier and the macOS home-directory path prefix in
  `PRIVATE_PATTERNS` are forbidden everywhere — describe them, never spell them;
- the capitalized whole word `Pro` is forbidden inside `dawn_osc/`, `dawn_core/`,
  `README.md` and the root notices;
- the root notices must contain the package notices' fenced license blocks verbatim.

## Related

- [[architecture/overview]] · [[modules/dawn-osc]] · [[index]]
