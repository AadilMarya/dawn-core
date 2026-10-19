# DAWN Core wiki

> Compounding knowledge base for the DAWN Core workspace: the music agent, its tools, and the Ableton control surface.

Read [[architecture/overview]] first, then the module page for the area you touch.
Decisions and their rationale live in [[decisions/log]].

## Pages

| Page | Summary |
|---|---|
| [[architecture/overview]] | Two packages, their boundaries, versions and release status |
| [[architecture/data-flow]] | Prompt → agent → tool → session → envelope → Live → read-back; plus the catalog build |
| [[modules/agent]] | `MusicAgent`, `build_agent`, model/provider extras and the public surface |
| [[modules/prompt]] | The six doctrine sections, `expertise`, the token budget and snapshot rules |
| [[modules/tools]] | 27 curated tools, result protocol, validation, `catalog_call` |
| [[modules/dawn-osc]] | Client transport and security envelope: API, locks, timeouts, session file |
| [[modules/remote-script]] | The `DAWN` control surface that runs inside Ableton Live |
| [[modules/catalog]] | The generated OSC catalog: rules, freshness gate, stats |
| [[modules/session-safety]] | `OscSession` call order and the fail-closed `Consent` policy |
| [[modules/testing-mini-live]] | Offline `MiniLive` double, the test layout and the evals |
| [[modules/harness-and-gates]] | `./test.sh` stages and every release gate |
| [[decisions/log]] | ADRs, newest first |

## Ground rules for wiki edits

- Attribution names for upstream projects may appear **only** in `THIRD_PARTY_NOTICES.md`
  files; the repo-wide scan (`dawn_core/tests/test_licensing.py`) fails on any other
  file that names them. Write around them here too.
- Never write an absolute path into a macOS user home directory (the scanner bans the literal
  prefix; use `~` or relative paths), and avoid the legacy private identifier defined by
  `PRIVATE_PATTERNS` in `dawn_core/tests/test_licensing.py` — refer to it, never spell it.
- Avoid the capitalized whole word `Pro` inside `dawn_osc/`, `dawn_core/`, `README.md`
  and `THIRD_PARTY_NOTICES.md` (the scan checks it there).

## Related

- [[modules/harness-and-gates]] — where the enforcement lives
