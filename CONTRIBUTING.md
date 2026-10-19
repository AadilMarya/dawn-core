# Contributing

Thanks for helping build an open music agent.

## Setup

```bash
git clone https://github.com/AadilMarya/dawn-core
cd dawn-core
uv sync --all-packages --extra dev
uv run pytest
```

Ableton is not required for development. `MiniLive` stands in for Live, and a deterministic
model stands in for a provider.

## Gates

Run these before every commit:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run --with mypy mypy dawn_core/src
uv run python -m dawn_core._gen_catalog --check
```

The full human path is `./test.sh -y --no-launch`.

## Adding a tool

1. Add an async method to the right group under `dawn_core/src/dawn_core/tools/`.
2. Give it a docstring. The model reads it; write it as an instruction.
3. Annotate every parameter. The type hints become the schema.
4. Validate musical ranges before sending anything.
5. Read every write back and return one of the result prefixes.
6. Add a test against `MiniLive`, including a refusal case.
7. Update `docs/tool-reference.md`.

Keep the result protocol: `OK`, `MISMATCH`, `SENT, NOT VERIFIED`, `REFUSED`, `ERROR`.

## Changing the prompt

The six sections live in `dawn_core/src/dawn_core/prompt/`. Keep the total under the budget
test, keep the working method explicit, and update `test_prompt.py` when a load-bearing line
changes. Run the evals.

## Changing the catalog

The catalog is generated from the Remote Script. Never edit `_catalog_data.py` by hand.

```bash
uv run python -m dawn_core._gen_catalog
uv run python -m dawn_core._gen_catalog --check
```

If the generator cannot infer an argument, add an override in `_gen_catalog.py` with a
comment that explains the handler.

## Style

- Python 3.11+, `from __future__ import annotations`.
- Line length 100; `ruff` decides formatting.
- Public functions and classes have docstrings.
- No new runtime dependency without a reason and a notices update.
- One concern per commit.

## Security

Do not open a public issue for a vulnerability. See [`SECURITY.md`](SECURITY.md).
