# DAWN

DAWN is a DAWN-branded fork of the upstream OSC control surface. It exposes the
`/live/*` surface and adds two DAWN endpoints:

- `/dawn/version` — the surface protocol version.
- `/dawn/security/status` — the authenticated handshake used by the DAWN
  transport.

All OSC traffic is protected by the DAWN authenticated envelope (HMAC-SHA256,
replay window, loopback only). There is no unauthenticated fallback.

The open surface intentionally stays close to the upstream project. It does not
include the private surface's verified-mutation layer, session snapshot, browser
loader, master/return handlers, arrangement writer, or DAWN app metadata.

## Install

Copy this folder into Live's **Remote Scripts** directory as `DAWN`, restart
Live, and select **DAWN** under **Settings → Link, Tempo & MIDI → Control
Surface**.

## Attribution

The `/live/*` handler surface is derived from the upstream project (MIT). See
`THIRD_PARTY_NOTICES.md` in the distribution.
