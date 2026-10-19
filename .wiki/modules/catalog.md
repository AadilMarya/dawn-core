# Module: catalog

> The committed OSC catalog, generated from the Remote Script AST, gating every call and driving the escape-hatch tool.

## What it is

- `dawn_core/_catalog_types.py` — `CatalogEntry` (address, group, verb, prop, args,
  risk, replies, source) and `ArgSpec`.
- `dawn_core/_catalog_data.py` — **generated**, committed. Do not edit by hand; run
  `python -m dawn_core._gen_catalog`.
- `dawn_core/catalog.py` — read-only index: `entries()`, `find(address)`, `groups()`,
  `by_group()`. Duplicate addresses raise at import.

## Generation (`_gen_catalog.py`)

- Reads the Remote Script source with `ast` only (the script cannot be imported: it needs
  Live). Unrolls `for` loops over statically known iterables, `%`-format, f-strings,
  `.format`, list concatenation, `range`. `add_handler` is dict-assignment semantics:
  **last registration for an address wins**.
- Unresolvable call sites fail the check; `ALLOWED_UNRESOLVED` is intentionally empty.
- Risk classes, first rule wins: reads (`/live/test`, `/dawn/version`, `/dawn/health`,
  `/dawn/security/status`, browser `list/*`; verbs `get`, `start_listen`, `stop_listen`) →
  verified-mutation endpoints under `/dawn/` are `write` (never `destructive`: payloads are
  opaque) → `delete|remove|clear|replace|crop` tokens and `set/notes` are `destructive` →
  everything else is `write`.
- `_EXTRA_INDEX_ARGS` adds indices the callback wrapper table cannot see: the device
  parameter endpoints take `parameter_index`, and the return-device endpoints take
  `device_index` and `parameter_index`. Setter overrides insert the extra indices before
  `value`.
- `replies` marks handlers whose callback provably returns a value (resolved from the AST);
  `None` means unknown.

## Freshness gate

```bash
uv run python -m dawn_core._gen_catalog --check   # exit 1 when stale or unresolved
```

- Default source root is `dawn_osc.script_dir()` — so inside a built wheel it checks the
  shipped catalog against the shipped payload (used by `./test.sh`).
- Current stats at 0.1.0: **217 call sites → 496 addresses** (read 372 / write 114 /
  destructive 10; replies True 17 / False 12 / None 467).

## Consumers

- `OscSession` refuses any address not in the catalog before sending ([[modules/session-safety]]).
- `catalog_call` in `dawn_core/tools/catalog_tool.py` reaches the long tail; it uses the
  entry's risk and reply flag ([[modules/tools]]).
- Tests: `test_catalog.py` (index invariants and the device-parameter overrides),
  `test_gen_catalog.py` (generator on synthetic sources), plus the gate above.

## Related

- [[architecture/data-flow]] · [[modules/remote-script]] · [[modules/session-safety]]
