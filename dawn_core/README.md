# dawn-core

An open-source AI music agent for Ableton Live.

```python
import asyncio

from dawn_core import Consent, MusicAgent, OscSession


async def main() -> None:
    async with OscSession(consent=Consent()) as live:
        agent = MusicAgent("openai:gpt-4o", session=live)
        print((await agent.run("set the tempo to 124")).output)


asyncio.run(main())
```

Install the Remote Script once, then select **DAWN** under **Settings → Link, Tempo & MIDI →
Control Surface**:

```python
from dawn_core import default_remote_scripts_dir, install_script

install_script(default_remote_scripts_dir())
```

`build_tools(session)` and `SYSTEM_PROMPT` are public too, for hosts that bring their own
agent loop.

See the repository README for the full guide, the tool reference and the security model.
