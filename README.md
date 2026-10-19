# DAWN Core

[![CI](https://github.com/AadilMarya/dawn-core/actions/workflows/ci.yml/badge.svg)](https://github.com/AadilMarya/dawn-core/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**An open-source AI music agent for Ableton Live.**

DAWN Core is the agent itself: a producer's taste, a curated set of Ableton tools, and a
consent-gated session that verifies every write. It is a library, not a UI. Embed it in your
own app, run it from a notebook, or use it as the base for a music agent of your own.

The DAWN desktop app is the reference host this library is built for; any Python app can
embed it the same way.

```python
import asyncio

from dawn_core import Consent, MusicAgent, OscSession


async def main() -> None:
    async with OscSession(consent=Consent()) as live:
        agent = MusicAgent("openai:gpt-4o", session=live)
        result = await agent.run("build a 4-bar deep house groove at 122")
        print(result.output)


asyncio.run(main())
```

## What it is

| Piece | What it does |
|---|---|
| `MusicAgent` | A `pydantic-ai` agent with a producer's system prompt and Ableton tools |
| `prompt/` | Six doctrine sections: persona, production, arrangement, mixing, sound design, Ableton |
| `tools/` | 27 curated musical tools, plus `catalog_call` for the long tail |
| `OscSession` | Catalog-gated, consent-checked, authenticated OSC link to Live |
| `MiniLive` | An offline Live double for tests and development |

Every write is read back. Results are one of `OK`, `MISMATCH`, `SENT, NOT VERIFIED`,
`REFUSED` or `ERROR`, so the model can tell the truth about what happened.

## Install

```bash
pip install "dawn-core[openai]"     # or [anthropic], [google], [ollama], [all]
```

Requires Python 3.11+.

### Install the Remote Script

DAWN Core talks to Live through the `DAWN` control surface. Install it once:

```python
from dawn_core import default_remote_scripts_dir, install_script

for step in install_script(default_remote_scripts_dir()):
    print(step)
```

Restart Live, then select **DAWN** under **Settings → Link, Tempo & MIDI → Control Surface**.

Check the install, the session file and Live:

```python
from dawn_core import check_install

report = check_install()
print("\n".join(report.lines()))
```

On Windows the Remote Scripts folder is `Documents/Ableton/User Library/Remote Scripts`.
Set `DAWN_CORE_REMOTE_SCRIPTS_DIR` to override the location.

## Bring your own everything

```python
# A different model
agent = MusicAgent("anthropic:claude-sonnet-4-5", session=live)
agent = MusicAgent("ollama:qwen2.5", session=live)

# A smaller prompt
agent = MusicAgent("openai:gpt-4o", session=live, expertise=["mixing", "arrangement"])

# A custom prompt
agent = MusicAgent("openai:gpt-4o", session=live, system_prompt="You are a techno producer.")

# Your own tools, alongside the curated ones
from pydantic_ai import Tool

agent = MusicAgent("openai:gpt-4o", session=live, tools=[*build_tools(live), my_tool])
```

The tools and the prompt are usable without the agent loop:

```python
from dawn_core import SYSTEM_PROMPT, build_tools

tools = build_tools(session)  # list of pydantic-ai Tool objects
prompt = SYSTEM_PROMPT  # the composed producer doctrine
```

## How a call works

```
prompt → MusicAgent → tool → OscSession
                              ├── catalog lookup (unknown addresses never leave)
                              ├── argument type check
                              └── Consent (read / write / destructive)
                                      ↓
                              authenticated OSC → DAWN Remote Script → Ableton
                                      ↓
                              reply → read-back → OK / MISMATCH / SENT, NOT VERIFIED
```

- Loopback only (`127.0.0.1`).
- HMAC-SHA256 datagram envelope with a replay window.
- Credentials live in an owner-only session file (`~/.dawn/runtime/osc_session.json`).
- Destructive calls are refused unless confirmed.

Read [`docs/security.md`](docs/security.md) before exposing anything beyond your machine.

## Packages

| Package | Role |
|---|---|
| `dawn-core` | The music agent: prompt, tools, session, safety, offline double |
| `dawn-osc` | Authenticated OSC transport and the `DAWN` Remote Script |

## Develop

```bash
uv sync --all-packages --extra dev
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run --with mypy mypy dawn_core/src
uv run python -m dawn_core._gen_catalog --check

./test.sh        # build, verify, install the Remote Script, health-check
```

The test suite is fully offline: a deterministic model and `MiniLive` stand in for the
provider and Ableton.

## Documentation

- [`docs/quickstart.md`](docs/quickstart.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/tool-reference.md`](docs/tool-reference.md)
- [`docs/prompt.md`](docs/prompt.md)
- [`docs/embedding.md`](docs/embedding.md)
- [`docs/security.md`](docs/security.md)
- [`docs/troubleshooting.md`](docs/troubleshooting.md)

## Status

Version 0.1.0. The agent, the curated tools and the offline test double are complete. The
event/listener stream and arrangement/automation tools are next.

## License

Apache-2.0. Third-party components and their licenses are listed in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
