# Module: tools

> 27 curated musical tools, bound to one `OscSession`, plus a catalog escape hatch.

## Layout

| File | Tools |
|---|---|
| `_helpers.py` | `Note`, `ToolBase`, `guard_result`, `read`, `write_and_verify`, `call_json`, validation |
| `session.py` | `get_session`, `set_tempo`, `set_metronome`, `start_playback`, `stop_playback`, `set_loop` |
| `tracks.py` | `create_track`, `rename_track`, volume, pan, mute, solo, arm, `delete_track` |
| `clips.py` | `create_clip`, `get_clip`, `add_notes`, `set_clip_loop`, launch/stop/delete |
| `scenes.py` | `create_scene`, `launch_scene`, `rename_scene` |
| `devices.py` | `list_devices`, `set_device_parameter`, `toggle_device` |
| `catalog_tool.py` | `catalog_call` |
| `__init__.py` | `build_tools`, `tool_names`, `Note` |

## The result protocol

Every tool returns a string:

| Prefix | Meaning |
|---|---|
| `OK:` | Read back and matches |
| `MISMATCH:` | Live holds another value |
| `SENT, NOT VERIFIED:` | Left but unconfirmed; read the value |
| `REFUSED:` | Consent or validation refused; nothing sent |
| `ERROR:` | Call failed |

Reads return JSON. The model is prompted to trust only `OK`.

## Invariants

- **`ToolBase.__init_subclass__` wraps every public coroutine** with `guard_result`, so a
  `ConsentDenied` or transport error becomes `REFUSED` / `ERROR` instead of escaping. Direct
  method calls in tests get the same behaviour.
- **Validate before sending.** Tempo 20–999, pitch 0–127, velocity 1–127, duration > 0,
  volume -70..+6 dB, pan -1..1, non-negative indices, ≤512 notes per call, device parameter
  inside the reported min/max.
- **Writes are read back.** `write_and_verify` sends, calls the matching getter, compares
  with bool/float tolerance, and reports honestly.
- **All tools are `sequential=True`** in `build_tools`; do not call them concurrently.
- **`add_notes` flattens to quintuples** `(pitch, start, duration, velocity, mute)`, the wire
  shape the Remote Script consumes.
- **`catalog_call`** calls getters and known-replying actions, sends the rest, and refuses
  unknown addresses. A timeout returns `SENT, NOT VERIFIED`, not `ERROR`.

## Catalog prerequisites (fixed in 0.1.0)

- Device parameter endpoints declare `parameter_index`:
  `get/parameter/name`, `get/parameter/value`, `get/parameter/value_string`,
  `set/parameter/value`; the return-device endpoints add `device_index`.
  `_EXTRA_INDEX_ARGS` in `_gen_catalog.py` holds the overrides.
- Browser `list/*` endpoints are `read`, so a read-only session can browse.

## Tests

`test_tools.py` covers every tool against `MiniLive`: success, read-back, range refusal,
read-only refusal, destructive refusal, and the device parameter wire shape.
`test_call_replies.py` covers the reply/flag analysis and `catalog_call`.

## Related

[[modules/session-safety]] · [[modules/catalog]] · [[modules/agent]] · [[modules/testing-mini-live]]
