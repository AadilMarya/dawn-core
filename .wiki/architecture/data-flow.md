# Data flow

> One agent turn end to end, plus the two build-time flows (catalog, distributions).

## An agent turn

```
user prompt
  → MusicAgent.run                         (dawn_core/agent.py)
  → pydantic-ai model picks a tool         (upstream runtime)
  → tool method                            (dawn_core/tools/*)
  → OscSession.call / .send                (dawn_core/session.py)
      1. catalog.find(address)            — unknown address never leaves
      2. argument type check              — bool/int/float/str only
      3. Consent.check(catalog entry)     — risk class decides
  → OscTransport.request / send_unacknowledged  (dawn_osc/transport.py)
      envelope: DAWNOSC magic + HMAC-SHA256 + counter (replay window) + fragments
  → UDP 127.0.0.1:11000
  → Remote Script SecureOscTransport      (remote_script/DAWN/handlers/security.py)
      authenticate, de-fragment, dedupe replays
  → dispatcher → handler                  (remote_script/DAWN/handlers/*)
  → Live Object Model read/write
  → handler returns a value? then a correlated reply
  → UDP back to client receive port (11001)
  → OscTransport matches reply by request id
  → tool renders OK / MISMATCH / SENT, NOT VERIFIED / REFUSED / ERROR
  → model reads the result, answers the user
```

Notes:

- Setters and actions usually return nothing → no reply → the curated tools fall back to a
  read-back (`OK` / `MISMATCH`) or report `SENT, NOT VERIFIED` ([[modules/tools]]).
- The client binds its receive port lazily on the first call, so constructing an
  `OscSession` is free ([[modules/session-safety]]).
- The prompt is composed once per `MusicAgent` ([[modules/prompt]]).

## Catalog build (checked by a gate)

```
dawn_osc/.../remote_script/DAWN/**.py
  → ast.parse (never imported; the script needs Live)
  → unroll loops / %-format / f-strings / .format; last add_handler per address wins
  → classify address (group, verb, prop) → risk class → reply flag
  → apply the per-address index overrides (_EXTRA_INDEX_ARGS)
  → render → dawn_core/_catalog_data.py   (committed, 496 entries)
  → gate: python -m dawn_core._gen_catalog --check  (fails when stale or unresolved)
```

## Distribution build

- `uv build --all-packages` → 2 wheels + 2 sdists in `dist/`.
- `dawn_osc` wheel/sdist embed the whole `remote_script/DAWN` payload (incl. the vendored
  OSC runtime and the `README.md` inside it).
- `dawn_core` ships `py.typed`, `README.md`, `LICENSE` and the `prompt/*.md` package data.
- `./test.sh` re-proves all of this in a fresh venv ([[modules/harness-and-gates]]).

## Related

- [[modules/dawn-osc]] · [[modules/session-safety]] · [[modules/catalog]] · [[modules/harness-and-gates]]
