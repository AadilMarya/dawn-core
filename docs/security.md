# Security

DAWN Core controls a DAW. Treat it accordingly.

## Threat model

- The transport is **loopback only**. There is no network listener and no remote mode.
- Every datagram is authenticated with HMAC-SHA256 and a replay window. Unsigned, replayed
  or non-loopback traffic is rejected before OSC parsing.
- The shared secret lives in an owner-only session file:
  `~/.dawn/runtime/osc_session.json` (override the directory with `DAWN_RUNTIME_DIR`).
- The Remote Script runs inside Live with the full Live Object Model. It is code you install;
  review it before installing, as you would any Remote Script.
- The agent has whatever Live has: it can delete tracks and clips. Consent is the guard.

## Consent

| Risk | Default |
|---|---|
| `read` | allowed |
| `write` | allowed unless the session is read-only |
| `destructive` | refused unless confirmed |

The policy fails closed: an unknown risk class, a confirmation callback that raises, and any
answer other than exactly `True` all refuse. Nothing is sent on a refusal.

```python
Consent()  # reads and writes; destructive refused
Consent(read_only=True)  # reads only
Consent(yes=True)  # destructive allowed
Consent(confirm=ask_user)  # destructive asks; everything else allowed
```

`confirm` is synchronous. Returning a coroutine is a refusal.

## What to review before running

- The Remote Script under `dawn_osc/src/dawn_osc/remote_script/DAWN/`.
- The tool surface in `dawn_core/tools/` — especially the destructive tools.
- The model provider and its data-retention policy. The prompt includes your Set's state.

## Reporting

Open a private security advisory on the repository rather than a public issue.

## Not in scope

- Multi-user or remote access.
- Sandboxing the model provider.
- Protecting a machine from a local user who can already run code.
