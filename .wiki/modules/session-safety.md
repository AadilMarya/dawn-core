# Module: session & safety

> `OscSession` is the one gate to Live; `Consent` is the fail-closed policy it enforces.

## `OscSession` (`dawn_core/session.py`)

Every call is authorized **before any datagram leaves**, in this order:

1. `catalog.find(address)` — unknown address → `UnknownAddressError`;
2. argument types must be `bool | int | float | str` → `TypeError`;
3. `Consent.check(entry, args)` → `ConsentDenied` ([[#consent]]).

Send paths:

- `call(address, *args, timeout=)` — correlated request, returns the reply tuple; no reply →
  `OscCallError` (even if Live applied the write). Use for reads, `test`/`other` endpoints
  and the few writes that reply.
- `send(address, *args)` — fire-and-forget; `OscCallError` only when the send itself failed.
  Use for setters/actions, then confirm with a read.
- `ping(timeout=)` — `True` when Live answers `/live/test`; never raises because Live is
  silent, only when the session is closed.

Lifecycle:

- Binds no socket until the first call (`OscTransport` created lazily) — abandoning a
  session leaks nothing.
- `close()` is terminal and idempotent; a closed session refuses calls, sends and pings
  instead of silently reconnecting. Port properties stay readable after close.
- A `transport=` injected at construction is used as-is and **never closed** by the session
  (the owner closes it); it is exclusive with ports/timeout/security-session arguments.

Defaults & env: ports 11000/11001, `DAWN_CORE_OSC_SEND_PORT` /
`DAWN_CORE_OSC_RECEIVE_PORT`; ports validated to 1–65535. Default request timeout 1 s
(`dawn_osc.transport.DEFAULT_TIMEOUT_SECONDS`); tools override to
`REPLY_WAIT_SECONDS = 3.0` where Live may be slow ([[modules/tools-agent-cli]]).

## Consent (`dawn_core/safety.py`)

| risk | allowed when |
|---|---|
| `read` | always |
| `write` | `read_only` is False |
| `destructive` | not `read_only`, and `yes` is set **or** `confirm(entry, args)` returns exactly `True` |

Fail-closed details:

- `yes` takes precedence and skips the callback entirely.
- Any unknown risk class → denied. Any exception in `confirm` → denied. Any non-`True`
  answer (including a coroutine, which is truthy but not `True`) → denied.
- Default callback is `deny_all`, so a bare `Consent()` never permits a destructive call.

Coupling: `build_agent` requires the *same* `Consent` instance the session was built with —
two different policies would silently let one be ignored ([[modules/tools-agent-cli]]).

## Related

- [[modules/catalog]] · [[modules/dawn-osc]] · [[modules/tools-agent-cli]]
