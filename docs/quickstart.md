# Quickstart

Get a music agent talking to Ableton Live in five minutes.

## 1. Install

```bash
pip install "dawn-core[openai]"
```

Use `[anthropic]`, `[google]`, `[ollama]` or `[all]` for other providers. The base install
carries the agent, the tools and the transport; the provider SDK is an extra.

From a checkout of the repository:

```bash
pip install "dawn-core[openai] @ git+https://github.com/AadilMarya/dawn-core.git#subdirectory=dawn_core"
```

## 2. Install the Remote Script

```python
from dawn_core import default_remote_scripts_dir, install_script

for step in install_script(default_remote_scripts_dir()):
    print(step)
```

Restart Live. Open **Settings → Link, Tempo & MIDI** and set **Control Surface** to
**DAWN**.

## 3. Check the link

```python
from dawn_core import check_install

report = check_install()
print("\n".join(report.lines()))
```

Every line should say `PASS`. If Live is closed, the script and session checks still pass
and the Live check fails with an explanation.

## 4. Run the agent

```python
import asyncio

from dawn_core import Consent, MusicAgent, OscSession


async def main() -> None:
    async with OscSession(consent=Consent()) as live:
        agent = MusicAgent("openai:gpt-4o", session=live)
        result = await agent.run("make a 4-bar loop at 122 with drums and a bass")
        print(result.output)


asyncio.run(main())
```

The agent reads the Set first, makes one change at a time, and reads every write back.

## 5. Try the offline path

No Ableton, no API key:

```bash
python examples/offline_agent.py
```

`MiniLive` serves an in-memory Set over the real authenticated envelope, and a scripted model
calls one tool. The same pattern is used by `dawn_core/tests/test_evals.py`.

## Next

- [`tool-reference.md`](tool-reference.md) — what the agent can do.
- [`prompt.md`](prompt.md) — tune the producer's doctrine.
- [`embedding.md`](embedding.md) — put the agent inside your own app.
