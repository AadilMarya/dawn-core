# Tool reference

`build_tools(session)` returns 27 `pydantic-ai` tools. The docstring is what the model sees;
the type hints become the JSON schema.

## Result protocol

Every tool returns a short string:

| Prefix | Meaning |
|---|---|
| `OK:` | The write was read back and matches. |
| `MISMATCH:` | Live holds another value. Report it; do not retry blindly. |
| `SENT, NOT VERIFIED:` | The message left but Live did not confirm it. Read the value. |
| `REFUSED:` | Consent or a musical range check refused it. Nothing was sent. |
| `ERROR:` | The call failed. Report the error briefly. |

Reads return JSON, not a prefix.

## Session and transport

| Tool | Risk | What it does |
|---|---|---|
| `get_session()` | read | Tempo, transport, signature, loop, scenes and every track |
| `set_tempo(bpm)` | write | 20–999 BPM, read back |
| `set_metronome(enabled)` | write | On/off, read back |
| `start_playback()` | write | Start, then check the transport |
| `stop_playback()` | write | Stop, then check the transport |
| `set_loop(enabled, start=None, length=None)` | write | Loop and range, read back |

## Tracks

| Tool | Risk | What it does |
|---|---|---|
| `create_track(kind="midi", index=None, name=None)` | write | Append or insert; returns the new index |
| `rename_track(track_index, name)` | write | Read back |
| `set_track_pan(track_index, pan)` | write | -1.0 to 1.0, read back |
| `set_track_mute(track_index, muted)` | write | Read back |
| `set_track_solo(track_index, soloed)` | write | Read back |
| `set_track_arm(track_index, armed)` | write | Read back |
| `delete_track(track_index)` | destructive | Confirm the target first |

## Clips

| Tool | Risk | What it does |
|---|---|---|
| `create_clip(track_index, slot_index, length_beats)` | write | Empty MIDI clip, verified |
| `get_clip(track_index, clip_index)` | read | Name, length, loop, playing state, notes |
| `add_notes(track_index, clip_index, notes)` | write | Up to 512 notes, count verified |
| `set_clip_loop(track_index, clip_index, start, end)` | write | Read back |
| `launch_clip(track_index, clip_index)` | write | Fire, then check playing |
| `stop_clip(track_index, clip_index)` | write | Stop, then check |
| `delete_clip(track_index, clip_index)` | destructive | Confirm the target first |

`add_notes` takes a list of `Note` objects: `pitch` 0–127, `start` in beats, `duration` in
beats, `velocity` 1–127, `mute`.

## Scenes

| Tool | Risk | What it does |
|---|---|---|
| `create_scene(index=None)` | write | Append or insert; count verified |
| `launch_scene(scene_index)` | write | Fire the scene |
| `rename_scene(scene_index, name)` | write | Read back |

## Devices

| Tool | Risk | What it does |
|---|---|---|
| `list_devices(track_index)` | read | Names and class names in chain order |
| `set_device_parameter(track_index, device_index, parameter, value)` | write | By name or index, range-checked, read back |
| `toggle_device(track_index, device_index, enabled)` | write | Device On (parameter 0), read back |

## Escape hatch

| Tool | Risk | What it does |
|---|---|---|
| `catalog_call(address, args=None)` | entry risk | Any address in the 496-entry catalog |

`catalog_call` uses the catalog's risk class and reply flag. A getter is called; an action is
sent unless the catalog proves it replies. An unknown address is refused.

## Musical validation

Rejected before anything is sent:

- tempo 20–999 BPM
- pitch 0–127, velocity 1–127, duration > 0, start >= 0
- volume -70 to +6 dB, pan -1.0 to 1.0
- non-negative indices
- clip length > 0
- at most 512 notes per call
- device parameter values inside the device's reported min/max
