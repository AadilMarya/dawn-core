# Module: prompt

> Six markdown doctrine sections, composed into the agent's system prompt.

## Files

| File | Content |
|---|---|
| `persona.md` | Producer/mix-engineer identity and the read → change → verify method |
| `production.md` | Headroom, gain staging, mono, references, signal flow |
| `arrangement.md` | Phrases, sections, energy, transitions, Session-first workflow |
| `mixing.md` | Balance, EQ, dynamics, sends, frequency ranges |
| `sound_design.md` | Subtractive, FM, wavetables, samplers, layering |
| `ableton.md` | Views, 0-based indices, clips, notes, devices, tracks, safety |

## API

- `DEFAULT_SECTIONS` — the six names in canonical order.
- `ALWAYS = ("persona", "ableton")` — included in every subset.
- `compose_system_prompt(expertise=None)` — reads package data; unknown names raise.
- `SYSTEM_PROMPT` — the default composition, computed at import.
- `available_sections()`.

## Rules

- **Budget.** The default prompt is capped at 10,000 characters (roughly 2,500 tokens) by
  `test_prompt.py`. Adding prose costs every turn; trim before you add.
- **Order.** `DEFAULT_SECTIONS` order is stable and tested.
- **Selection is case-insensitive and deduplicated.** `persona` and `ableton` are always
  present.
- **`system_prompt` and `expertise` are mutually exclusive** in `MusicAgent`.
- **Package data.** Files are loaded with `importlib.resources`; keep them inside
  `dawn_core/prompt/` so the wheel ships them.
- **Doctrine is load-bearing.** `test_prompt.py` asserts the read-before-write, `OK`,
  `MISMATCH`, `SENT, NOT VERIFIED` and 0-based rules. Update the test when a rule changes.

## Editing

1. Change the section.
2. Run `uv run pytest dawn_core/tests/test_prompt.py dawn_core/tests/test_evals.py`.
3. Check the budget test.
4. Review with a real model on three live prompts; record what improved.

## Related

[[modules/agent]] · [[modules/tools]]
