# The prompt

The agent's taste lives in six markdown files under `dawn_core/prompt/`:

| Section | Content |
|---|---|
| `persona` | Producer and mix-engineer identity; the read → change → verify method |
| `production` | Headroom, gain staging, mono checks, references, signal flow |
| `arrangement` | Phrases, sections, energy, transitions, Session-first workflow |
| `mixing` | Balance, EQ, dynamics, sends, common frequency ranges |
| `sound_design` | Subtractive synthesis, FM, wavetables, samplers, layering |
| `ableton` | The two views, 0-based indices, clips, notes, devices, tracks |

`persona` and `ableton` are always included. The default prompt is all six and stays under
the 10,000-character budget enforced by `test_prompt.py`.

## Select a subset

```python
agent = MusicAgent("openai:gpt-4o", session=live, expertise=["mixing", "arrangement"])
```

Unknown names raise `ValueError`. Section order is stable.

## Replace it

```python
agent = MusicAgent("openai:gpt-4o", session=live, system_prompt="You are a techno producer.")
```

`system_prompt` and `expertise` are mutually exclusive.

## Compose it yourself

```python
from dawn_core import compose_system_prompt

prompt = compose_system_prompt(["sound_design"])
```

## Editing the doctrine

- Keep the working method explicit: read first, one change, read back, report honestly.
- Keep musical advice actionable and short. The tools carry the detail.
- Keep the total under the budget test.
- Update `test_prompt.py` when a load-bearing line changes.
