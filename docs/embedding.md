# Embedding the agent

DAWN Core is a library. There are three ways to use it.

## 1. The agent, in-process

```python
from dawn_core import Consent, MusicAgent, OscSession

async with OscSession(consent=Consent()) as live:
    agent = MusicAgent("openai:gpt-4o", session=live)
    result = await agent.run("arrange the loop into a 32-bar section")
```

This is the DAWN app's path. It owns the model, the prompt and the session.

## 2. Share a transport you already own

If your app already holds the authenticated Live connection, hand it to the session. The
session never closes a borrowed transport, and there is no second receive port to fight over.

```python
from dawn_core import Consent, OscSession

session = OscSession(transport=my_client, consent=Consent(confirm=ask_user))
```

`my_client` must be an `OscTransport` (or a subclass). DAWN's own OSC client is one.

The confirmation callback is synchronous and fails closed:

```python
def ask_user(entry, args) -> bool:
    return my_ui.confirm_blocking(entry.address, args)
```

If your UI is async, bridge it with a `threading.Event` or a queue. Returning a coroutine is
a refusal.

## 3. Your own loop

Use the tuned tools and prompt without adopting the agent class:

```python
from dawn_core import SYSTEM_PROMPT, build_tools

tools = build_tools(session)  # pydantic-ai Tool objects
prompt = SYSTEM_PROMPT  # producer doctrine
```

Each `Tool` exposes:

- `name`
- `description`
- `function_schema.json_schema` — JSON Schema for the model
- `function` — the bound async method

Call `await tool.function(**arguments)` and feed the result string back to your model.

## Model selection

Any model string `pydantic-ai` understands works:

```python
MusicAgent("openai:gpt-4o", session=live)
MusicAgent("anthropic:claude-sonnet-4-5", session=live)
MusicAgent("google-gla:gemini-2.5-flash", session=live)
MusicAgent("ollama:qwen2.5", session=live)
```

Install the matching extra: `dawn-core[openai]`, `[anthropic]`, `[google]`, `[ollama]`.

## Extending the tool list

```python
from pydantic_ai import Tool


async def set_reverb_size(track_index: int, size: float) -> str:
    """Set the reverb return size from 0 to 1."""
    ...


agent = MusicAgent("openai:gpt-4o", session=live, tools=[*build_tools(live), Tool(set_reverb_size)])
```

Keep the result protocol (`OK`, `REFUSED`, …) so the model can reason about outcomes.
