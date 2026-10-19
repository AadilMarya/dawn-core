# Module: agent

> `MusicAgent`: a thin wrapper over an upstream agent runtime, bound to one `OscSession`.

## Files

| File | Role |
|---|---|
| `agent.py` | `MusicAgent`, `build_agent`, `pydantic_ai.BANNER_ENABLED = False` |
| `__init__.py` | Public surface: agent, session, consent, tools, prompt, install helpers |

## API

```python
agent = MusicAgent(
    model,  # provider:model string or a Model instance
    session=live,  # must be an OscSession
    expertise=None,  # prompt subset; mutually exclusive with system_prompt
    tools=None,  # default: build_tools(session)
    system_prompt=None,
    name="dawn_core",
    history=(),  # seed message history
)
await agent.run("...")  # -> result.output
async with agent.run_stream("...") as stream:
    ...
```

Properties: `.agent` (the underlying runtime agent), `.session`, `.tools`,
`.system_prompt`.

`build_agent(...)` is the functional form.

## Rules

- **Provider extras.** The base install has `pydantic-ai-slim` and no provider SDK. A model
  string such as `openai:gpt-4o` needs `dawn-core[openai]`; `anthropic`, `google` and
  `ollama` follow the same pattern. Tests use `FunctionModel`, never a provider.
- **One session.** The agent does not create a session; the host owns its lifecycle. Tools
  are bound to that session at construction.
- **History.** A run without `message_history` continues from the seed `history`; an explicit
  history wins. This preserves the old resume behaviour.
- **Sequential tools.** `build_tools` marks every tool `sequential=True`, so a write and its
  read-back keep the order the model issued them.
- **No banner.** `agent.py` disables the runtime's startup banner at import; a library must
  not write into its host's output.
- **Thin.** Do not add planning, memory or provider logic here. Put musical behaviour in the
  prompt and the tools.

## Public surface

`__init__.py` exports `MusicAgent`, `build_agent`, `OscSession`, `Consent`, `ConsentDenied`,
`OscCallError`, `UnknownAddressError`, `catalog`, `build_tools`, `tool_names`, `Note`,
`SYSTEM_PROMPT`, `compose_system_prompt`, `install_script`, `check_install`,
`check_install_async`, `default_remote_scripts_dir`, `__version__`.

## Tests

`test_agent.py` (scripted model, tool call, streaming, prompt selection), `test_evals.py`
(six agent-flow scenarios). Both use `MiniLive` and need no API key.

## Related

[[modules/prompt]] · [[modules/tools]] · [[modules/session-safety]] · [[modules/testing-mini-live]]
