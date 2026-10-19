# Module: Remote Script (`DAWN`)

> The open Ableton control surface that runs inside Live: a DAWN-branded fork of the upstream OSC control surface, with the DAWN HMAC envelope.

## Layout (`dawn_osc/src/dawn_osc/remote_script/DAWN/`)

- `__init__.py` — the `DAWN` surface class. It registers only `/dawn/version` and
  `/dawn/security/status` on top of the upstream `/live/*` surface. `DAWN_PROTOCOL_VERSION`
  is **2.32.0** (the HMAC wire contract is unchanged).
- `manager.py` — `Manager(ControlSurface)`, the entry point Live loads: starts the secured
  OSC server, ticks, logs to `logs/dawn_osc.log`, relays errors to `/live/error`.
- `handlers/` — the upstream domains: `song`, `track`, `clip`, `clip_slot`, `scene`,
  `device`, `application`, `view`, `midimap`, plus `handler` (base class `OscHandler`),
  `osc_server` (secured), `security` (envelope mirror), `constants`
  (`DAWN_INSTANCE_ID`), `introspection`.
- `pythonosc/` — vendored OSC runtime (excluded from lint/format/scan).

The open surface deliberately omits the private surface's arrangement writer, browser
loader, master/return handlers, rich MIDI/session note protocols, verified-mutation layer
and session snapshot. The private surface is not in this repository at all: the private
DAWN app vendors it in its own tree and overlays its protocol-2.33 files on top.

## Do-not

- Keep it dumb: receive OSC, query the LOM, reply, log. No agent/provider/planning logic.
- Do not reformat the tree wholesale — it deliberately keeps Live-era style, and ruff
  excludes `remote_script/**`.
- Do not add unauthenticated fallbacks: there is no bare `/live/*` path without the envelope.

## Runtime behaviour

- Listens on UDP 11000 by default; replies to the client's port (11001 default).
- Handshake endpoints: `/dawn/version` and `/dawn/security/status` (protocol, session id,
  surface revision, instance id). There is no `/dawn/health`, `/dawn/startup`,
  `/dawn/get/session_snapshot` or verified-mutation endpoint in the open surface.
- Setters return nothing (no reply); some actions return values; the catalog's `replies`
  flag records which ([[modules/catalog]]).
- The security layer (`handlers/security.py`) mirrors `dawn_osc.security`: same magic,
  fragment and replay handling, same session file (`DAWN_RUNTIME_DIR` override, owner-only,
  mode-checked, protocol-checked). Wrong-owner/loose-permission files are rejected.

## Install story

- Live loads it from `Remote Scripts/DAWN`; `dawn_core.remote_script` installs it
  transactionally (stage → backup `DAWN.bak-<timestamp>` → swap → verify → rollback on
  failure) and `script_matches()` compares the installed tree with the packaged one.
- The comparison covers the **deployable tree only**: `__pycache__`/`.git`/`logs` dirs,
  `dawn_instance.json`, `.DS_Store`, `Icon\r`, `.pyc`/`.pyo` and `._*` are skipped — the same
  list the script's own revision digest uses (`_REVISION_PRUNED_DIRS` /
  `_REVISION_SKIPPED_FILES` in `DAWN/__init__.py`; ADR-0476 there). Keep the two lists
  identical: Live writes logs and an instance config beside the sources, and without the
  skips a healthy, used install reports "differs" forever.
- After upgrading the installed copy, restart Live so the old script unloads.

## Related

- [[modules/dawn-osc]] · [[modules/catalog]] · [[architecture/overview]]
