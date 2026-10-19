# Architecture

DAWN Core is two packages and one agent.

```
┌──────────────────────────────────────────────────────────┐
│ Hosts                                                    │
│   DAWN app (in-process)   scripts   notebooks   evals    │
└──────────────────────────┬───────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────┐
│ dawn_core                                                │
│   MusicAgent(model, session=...)                         │
│     ├── prompt/    six doctrine sections                 │
│     ├── tools/     27 curated tools + catalog_call       │
│     ├── session    OscSession (catalog + consent)        │
│     └── safety     Consent                               │
└──────────────────────────┬───────────────────────────────┘
                           │ authenticated OSC
┌──────────────────────────▼───────────────────────────────┐
│ dawn_osc                                                 │
│   OscTransport + the DAWN Remote Script                  │
└──────────────────────────┬───────────────────────────────┘
                           │ UDP 127.0.0.1:11000/11001
┌──────────────────────────▼───────────────────────────────┐
│ Ableton Live — DAWN control surface                      │
└──────────────────────────────────────────────────────────┘
```

## Packages

| Package | Responsibility |
|---|---|
| `dawn-core` | The agent: prompt, tools, session, consent, offline double |
| `dawn-osc` | HMAC-authenticated OSC, request/reply correlation, the Remote Script |

`dawn-core` depends on `dawn-osc`; nothing depends on the DAWN app.

## One tool call

```
user prompt
  → MusicAgent (pydantic-ai)
  → model chooses a tool and arguments
  → tool method (dawn_core/tools/*)
  → OscSession.call / .send
      1. catalog lookup        — unknown addresses never leave
      2. argument type check   — bool / int / float / str only
      3. Consent.check         — read / write / destructive
  → OscTransport.request
      HMAC envelope, replay window, correlated reply
  → UDP 127.0.0.1:11000
  → Remote Script: authenticate, dispatch, Live Object Model
  → reply (only when the handler returns a value)
  → tool renders OK / MISMATCH / SENT, NOT VERIFIED / REFUSED / ERROR
  → model reports
```

Most setters return nothing. The curated tools therefore read the value back through the
matching getter and compare it.

## The catalog

The Remote Script is parsed with `ast` at build time (it cannot be imported outside Live).
The result is `_catalog_data.py`: 496 addresses with group, verb, argument specs, risk class
and a reply flag. `python -m dawn_core._gen_catalog --check` fails when the committed
catalog is stale.

## The prompt

The system prompt is composed from six markdown files under `dawn_core/prompt/`. The default
is all six; `expertise=[...]` selects a subset, always keeping `persona` and `ableton`.

## The offline double

`dawn_core.testing.MiniLive` speaks the same authenticated envelope as the Remote Script and
serves an in-memory Set. It is what makes the test suite offline and deterministic.

## Boundaries

- The Remote Script stays dumb: receive OSC, query the Live Object Model, reply, log.
- No agent, provider or planning logic runs inside Live.
- `OscSession` is the only gate between a tool and Live.
- The DAWN app is a host, not a dependency.
