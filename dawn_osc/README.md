# dawn_osc

Authenticated OSC transport for Ableton Live, plus the DAWN Remote Script that runs inside Live. The script is a DAWN-branded fork of the upstream OSC control surface: the `/live/*` handlers plus the DAWN HMAC envelope.

- `OscTransport` — the Python client: loopback-only UDP, an HMAC-authenticated datagram
  envelope with a replay window, protocol handshake and correlated request/reply matching.
- `remote_script/DAWN` — the Ableton control surface that answers it. `script_dir()` returns
  the folder; install it as `DAWN` in Live's Remote Scripts directory.

## Install

```bash
pip install dawn-osc
```

## Install the Remote Script

```python
import dawn_osc

print(dawn_osc.script_dir())  # copy this folder into Remote Scripts as "DAWN"
```

In Live: Settings → Link, Tempo & MIDI → Control Surface → **DAWN**.
The `dawn-core` package wraps the install in `install_script()`.

## Talk to Live

```python
import asyncio
import dawn_osc


async def main() -> None:
    transport = dawn_osc.OscTransport()  # 127.0.0.1, 11000 -> 11001
    try:
        print(await transport.ping())  # True when Live answers /live/test
    finally:
        transport.close()


asyncio.run(main())
```

Datagrams are authenticated. Unsigned, replayed or non-loopback traffic is rejected before
OSC parsing; there is no unauthenticated fallback. Both sides read the same owner-only
session file (`~/.dawn/runtime/osc_session.json`), so credentials stay launch-local.

## Develop

```bash
uv sync --all-packages --extra dev
uv run pytest
```

## License

Copyright 2026 Aadil Marya. Licensed under the Apache License, Version 2.0. See `LICENSE`;
third-party components, including the vendored OSC runtime, are listed in
`THIRD_PARTY_NOTICES.md`.
