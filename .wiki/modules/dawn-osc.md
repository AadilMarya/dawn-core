# Module: dawn_osc

> Loopback-only authenticated OSC client (`OscTransport`) plus the `DAWN` Remote Script payload the package ships.

## Files

- `transport.py` — `OscTransport`: UDP sockets, handshake, protocol gating, bounded
  in-flight admission, correlated request/reply matching. Owns nothing domain-specific.
- `security.py` — `OscSecuritySession`, the datagram envelope, session file I/O.
- `remote_script/DAWN/` — the payload ([[modules/remote-script]]).
- `tests/` — control-surface tests plus `structural_mock_surface.py`; `conftest.py` exposes
  the payload as the `control_surface.DAWN` namespace so tests import it exactly as Live does.

## `OscTransport`

```python
OscTransport(host="127.0.0.1", send_port=11000, receive_port=11001,
             timeout_seconds=1.0, *, expected_instance_id=None, security_session=None)
```

- Host is restricted to loopback (`127.0.0.1`/`localhost`) — anything else raises.
- Async API: `request(address, *args, timeout_seconds=)` → reply tuple, `send_unacknowledged`,
  `ping`; sync: `close()`. Properties: `last_error`, `surface_revision`, `surface_instance_id`.
- `REPLY_TIMEOUT_PREFIX = "Timed out waiting for reply from "` is matched by
  `dawn_core` to distinguish "sent, no reply" from other failures — change both sides
  together ([[modules/tools-agent-cli]]).
- Admission: `MAX_INFLIGHT_REQUESTS = 10`; `RESERVED_SETTLEMENT_SLOTS = 2` are held back for
  verified-mutation receipts so read waves cannot starve settlement.
- `REACHABLE_WITHOUT_PING_SECONDS = 30.0` lets callers skip a liveness ping after a recent
  authenticated reply. It is only ever used to *skip* a probe, never to report health.
- Two locks, deliberately different (see module docstring): a plain `threading.Lock` for the
  send socket (used from the receiver callback thread) and an `asyncio.Lock` for in-flight
  accounting (async-only). Do not "simplify" to one kind.
- Nested legacy-state reads share one deadline via the `osc_request_deadline` contextvar;
  controlled failure logging via `osc_quiet_failure_logging` avoids one warning per timeout.

## Security envelope

- Magic `DAWNOSC`, kinds request/response (+fragment kinds), 16-byte session id, 64-bit
  counter, HMAC-SHA256 trailer. Version constant `OSC_SECURITY_PROTOCOL = 3`.
- Fragmentation: datagrams ≤ 8192 bytes; payload fragments ≤ 64 per message, ≤ 8 concurrent
  reassembles, ≤ 512 KiB reassembled, 5 s fragment TTL.
- Replay window: 4096-entry sliding bitmap in both client and script.
- Session file: `~/.dawn/runtime/osc_session.json` (root override `DAWN_RUNTIME_DIR`),
  mode 0600, owner-only; readers reject wrong owner, non-regular files, broad permissions,
  or a mismatched protocol. `get_process_osc_session()` loads a live session or lazily
  creates one only when none exists — it never rotates another process's credentials.

## Packaging facts

- The wheel and sdist embed the entire `remote_script/DAWN` tree, including the vendored OSC
  runtime (excluded from lint/reformat/scan by path) and `DAWN/README.md`.
- Ships `py.typed`; declared `loguru` and the OSC runtime as dependencies.
- License metadata: Apache-2.0 + `THIRD_PARTY_NOTICES.md` in `dist-info/licenses/`.

## Gotchas

- The transport requires a readable session file; a bare local process gets credentials by
  creating one (lazily). Tests isolate this with `DAWN_RUNTIME_DIR`.
- `close()` is the caller's job when the transport is injected into an `OscSession`
  ([[modules/session-safety]]).
- ruff excludes `remote_script/**` from formatting and most lint rules; do not reformat the
  payload wholesale — it follows the Live-era style on purpose.

## Related

- [[modules/remote-script]] · [[modules/session-safety]] · [[architecture/data-flow]]
