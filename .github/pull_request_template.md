## Scope

What changed, and why.

## Risk

- [ ] Read-only change
- [ ] New or changed write tool
- [ ] New or changed destructive tool
- [ ] Transport / Remote Script
- [ ] Packaging / release

## Verification

- [ ] `uv run pytest`
- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run --with mypy mypy dawn_core/src`
- [ ] `uv run python -m dawn_core._gen_catalog --check`
- [ ] Tested against Live (describe the Set and the prompt)
- [ ] Tested offline with `MiniLive`

## Notes

Anything a reviewer should know: prompt changes, new dependencies, migration.
