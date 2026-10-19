# Troubleshooting

## `Live did not answer /live/test`

1. Live is running.
2. **Settings → Link, Tempo & MIDI → Control Surface** is set to **DAWN**.
3. The Remote Script is installed in the right folder:
   - macOS: `~/Music/Ableton/User Library/Remote Scripts`
   - Windows: `~/Documents/Ableton/User Library/Remote Scripts`
4. No other client owns the reply port (11001). Only one process can bind it.

Check:

```python
from dawn_core import check_install

print("\n".join(check_install().lines()))
```

## `Remote Script not installed` or `differs from the packaged copy`

```python
from dawn_core import default_remote_scripts_dir, install_script

print("\n".join(install_script(default_remote_scripts_dir(), force=True)))
```

Restart Live afterwards.

## `Please install the 'openai' package`

Provider SDKs are extras:

```bash
pip install \
  "dawn-osc @ https://github.com/AadilMarya/dawn-core/releases/download/v0.1.0/dawn_osc-0.1.0-py3-none-any.whl" \
  "dawn-core[openai] @ https://github.com/AadilMarya/dawn-core/releases/download/v0.1.0/dawn_core-0.1.0-py3-none-any.whl"
```

Swap `[openai]` for `[anthropic]`, `[google]`, `[ollama]` or `[all]`.

## `No matching distribution found for dawn-core`

The release is not on PyPI yet, so install the published wheels instead — both of them,
because the agent depends on the transport:

```bash
pip install \
  "dawn-osc @ https://github.com/AadilMarya/dawn-core/releases/download/v0.1.0/dawn_osc-0.1.0-py3-none-any.whl" \
  "dawn-core @ https://github.com/AadilMarya/dawn-core/releases/download/v0.1.0/dawn_core-0.1.0-py3-none-any.whl"
```

From a checkout of the repository:

```bash
pip install \
  "dawn-osc @ git+https://github.com/AadilMarya/dawn-core.git#subdirectory=dawn_osc" \
  "dawn-core @ git+https://github.com/AadilMarya/dawn-core.git#subdirectory=dawn_core"
```

## `address is not in the DAWN catalog`

`catalog_call` only accepts exact catalog addresses. Inspect the catalog:

```python
from dawn_core import catalog

for entry in catalog.entries():
    if "tempo" in entry.address:
        print(entry.address, entry.risk)
```

## `REFUSED: ... session is read-only`

The session was built with `Consent(read_only=True)`. Build a new one without it.

## `REFUSED: ... not confirmed`

A destructive call needs confirmation. Pass `Consent(yes=True)` or a `confirm` callback.

## `MISMATCH`

Live holds a different value than the one written. Read the value, report it, and decide
whether to retry with a different value. Do not loop.

## `SENT, NOT VERIFIED`

The message left but Live did not confirm it. Read the affected value before claiming
success. Launch quantization can delay a clip fire.

## Tests fail with a port error

Another process owns the test ports. The suite allocates free UDP ports per test; a stale
process holding 11000/11001 is the usual cause.

## Session file is unreadable

Delete `~/.dawn/runtime/osc_session.json` and reconnect. Both sides recreate it when no file
exists. Do not delete it while Live is connected and expect the old connection to survive.
