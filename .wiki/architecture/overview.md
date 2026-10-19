# Architecture overview

> Two uv-workspace packages: an authenticated OSC transport plus Live Remote Script, and the music agent built on it.

## Packages

| Package | Distribution | Role |
|---|---|---|
| `dawn_osc` | `dawn-osc` | Loopback-only authenticated OSC transport (client) **and** the `DAWN` Remote Script payload that runs inside Ableton Live |
| `dawn_core` | `dawn-core` | The agent: `MusicAgent`, six prompt sections, 27 curated tools, consent-gated session, catalog, offline `MiniLive` double |

`dawn_core` depends on `dawn_osc`. Nothing in this repo depends on the DAWN desktop app; the
app is a host that embeds the library.

## Boundaries

- The Remote Script stays dumb: receive OSC, query the Live Object Model, send replies,
  log errors. No agent/provider/planning logic there (see [[modules/remote-script]]).
- `OscSession` is the single gate between a tool and Live: catalog lookup → argument types →
  consent, in that order, before any datagram leaves (see [[modules/session-safety]]).
- The catalog is generated from the Remote Script source with `ast` only (the script cannot
  be imported outside Live) and is guarded by a freshness gate (see [[modules/catalog]]).
- The agent runtime is upstream `pydantic-ai-slim`; `MusicAgent` is a thin wrapper, not a
  framework (see [[modules/agent]]).

## Runtime facts

- Defaults: host `127.0.0.1`, Live listens on UDP **11000**, the client replies from **11001**.
- Wire format: authenticated envelope (`DAWNOSC` magic, HMAC-SHA256, replay window,
  fragmentation up to 64 fragments). There is no unauthenticated fallback.
- Credentials: owner-only `~/.dawn/runtime/osc_session.json` (override root:
  `DAWN_RUNTIME_DIR`); the client lazy-creates only when no session file exists.
- Workspace Python: `.python-version` pins 3.12; both packages declare `requires-python =
  ">=3.11"`.
- Versions: both distributions are **0.1.0** — the public baseline. The repository is
  public at `github.com/AadilMarya/dawn-core`; the release is tagged `v0.1.0`
  (2026-10-19). The open surface is a fork of the upstream OSC control surface; the
  private surface lives in the private DAWN app repo, not here.
- Remotes: `origin` is the public repository, `internal` is the private one that keeps
  the full history and the private surface. The public history shares no ancestor with
  the internal one. A local `pre-push` hook refuses to send the private surface to the
  public remote, so `git push --all origin` cannot leak it.

## Protocol numbers (three, on purpose)

- `DAWN_PROTOCOL_VERSION = "2.32.0"` — the surface protocol (request correlation, verified
  receipts); the packaged README calls this "DAWN OSC v2". The offline double reports the
  same string; `structural_creation.py` documents its subset as protocol 2.30.
- `OSC_SECURITY_PROTOCOL = 3` — the datagram envelope version, stored in the session file;
  both sides reject a mismatched file.
- `DAWN_INSTANCE_ID` — per-launch Live identity used to bind replies to the right instance.

## Related

- [[architecture/data-flow]] · [[modules/dawn-osc]] · [[modules/harness-and-gates]]
