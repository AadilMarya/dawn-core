"""The curated music tools, exercised against the offline Live double."""

from __future__ import annotations

import json
from typing import Any

import pytest

from dawn_core import Consent, OscSession, catalog
from dawn_core.testing import MiniLive, MiniTrack
from dawn_core.tools import (
    CatalogTools,
    ClipTools,
    DeviceTools,
    Note,
    SceneTools,
    SessionTools,
    TrackTools,
    build_tools,
    tool_names,
)

EXPECTED_TOOL_NAMES = (
    "add_notes",
    "catalog_call",
    "create_clip",
    "create_scene",
    "create_track",
    "delete_clip",
    "delete_track",
    "get_clip",
    "get_session",
    "launch_clip",
    "launch_scene",
    "list_devices",
    "rename_scene",
    "rename_track",
    "set_clip_loop",
    "set_device_parameter",
    "set_loop",
    "set_metronome",
    "set_tempo",
    "set_track_arm",
    "set_track_mute",
    "set_track_pan",
    "set_track_solo",
    "start_playback",
    "stop_clip",
    "stop_playback",
    "toggle_device",
)


def test_tool_names_are_stable() -> None:
    assert tool_names() == EXPECTED_TOOL_NAMES


def test_every_tool_is_a_described_object_schema() -> None:
    tools = build_tools(OscSession())
    assert [tool.name for tool in tools] == list(EXPECTED_TOOL_NAMES)
    for tool in tools:
        assert tool.description and tool.description.strip()
        schema = tool.function_schema.json_schema
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)


def test_notes_are_validated_by_the_model() -> None:
    with pytest.raises(ValueError):
        Note(pitch=128, start=0, duration=1)
    with pytest.raises(ValueError):
        Note(pitch=60, start=-1, duration=1)
    with pytest.raises(ValueError):
        Note(pitch=60, start=0, duration=0)


def _received(live: MiniLive, address: str) -> list[tuple[Any, ...]]:
    return [request.args for request in live.requests if request.address == address]


@pytest.mark.asyncio
async def test_set_tempo_writes_and_reads_back(live: MiniLive, ports: tuple[int, int]) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await SessionTools(session).set_tempo(128)
    assert result.startswith("OK: song.tempo is 128")
    assert live.tempo == 128.0


@pytest.mark.asyncio
async def test_set_tempo_refuses_out_of_range(live: MiniLive, ports: tuple[int, int]) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await SessionTools(session).set_tempo(5)
    assert result.startswith("REFUSED:")
    assert _received(live, "/live/song/set/tempo") == []


@pytest.mark.asyncio
async def test_set_tempo_reports_a_mismatch(live: MiniLive, ports: tuple[int, int]) -> None:
    live.serve("/live/song/set/tempo", lambda _params: None)  # silently ignore the write
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await SessionTools(session).set_tempo(128)
    assert result.startswith("MISMATCH:")


@pytest.mark.asyncio
async def test_rename_and_mute_a_track(live: MiniLive, ports: tuple[int, int]) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        tracks = TrackTools(session)
        renamed = await tracks.rename_track(0, "Kick")
        muted = await tracks.set_track_mute(0, True)
    assert renamed.startswith("OK:")
    assert muted.startswith("OK:")
    assert live.tracks[0].name == "Kick"
    assert live.tracks[0].mute is True


@pytest.mark.asyncio
async def test_set_track_pan_reads_back(live: MiniLive, ports: tuple[int, int]) -> None:
    pans: dict[int, float] = {0: 0.0}
    live.serve("/live/track/set/panning", lambda p: pans.__setitem__(int(p[0]), float(p[1])))
    live.serve("/live/track/get/panning", lambda p: (int(p[0]), pans[int(p[0])]))
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        pan = await TrackTools(session).set_track_pan(0, 0.25)
    assert pan.startswith("OK:")
    assert pans[0] == 0.25


@pytest.mark.asyncio
async def test_create_track_appends_and_names_it(live: MiniLive, ports: tuple[int, int]) -> None:
    live.serve(
        "/live/song/create_midi_track",
        lambda _params: live.tracks.append(MiniTrack("MIDI", False, 0.7)),
    )
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await TrackTools(session).create_track("midi", name="Bass")
    assert result.startswith("OK: created midi track at index 3")
    assert live.tracks[3].name == "Bass"


@pytest.mark.asyncio
async def test_delete_track_requires_confirmation(live: MiniLive, ports: tuple[int, int]) -> None:
    def delete(params: tuple[Any, ...]) -> None:
        live.tracks.pop(int(params[0]))

    live.serve("/live/song/delete_track", delete)
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        refused = await TrackTools(session).delete_track(0)
    assert refused.startswith("REFUSED:")
    assert _received(live, "/live/song/delete_track") == []
    async with OscSession(
        send_port=ports[0], receive_port=ports[1], consent=Consent(yes=True)
    ) as session:
        deleted = await TrackTools(session).delete_track(0)
    assert deleted.startswith("OK:")
    assert len(live.tracks) == 2


@pytest.mark.asyncio
async def test_create_clip_add_notes_and_read_them_back(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    clips: dict[tuple[int, int], dict[str, Any]] = {}
    notes: dict[tuple[int, int], list[Any]] = {}

    def create(params: tuple[Any, ...]) -> None:
        clips[(int(params[0]), int(params[1]))] = {"length": float(params[2])}

    def add(params: tuple[Any, ...]) -> None:
        key = (int(params[0]), int(params[1]))
        values = list(params[2:])
        notes[key] = values

    live.serve("/live/clip_slot/create_clip", create)
    live.serve(
        "/live/clip_slot/get/has_clip",
        lambda p: (int(p[0]), int(p[1]), (int(p[0]), int(p[1])) in clips),
    )
    live.serve(
        "/live/clip/get/length",
        lambda p: (int(p[0]), int(p[1]), clips[(int(p[0]), int(p[1]))]["length"]),
    )
    live.serve("/live/clip/add/notes", add)
    live.serve(
        "/live/clip/get/notes",
        lambda p: (int(p[0]), int(p[1]), *notes.get((int(p[0]), int(p[1])), [])),
    )
    live.serve("/live/clip/get/name", lambda p: (int(p[0]), int(p[1]), "Clip"))
    live.serve("/live/clip/get/loop_start", lambda p: (int(p[0]), int(p[1]), 0.0))
    live.serve("/live/clip/get/loop_end", lambda p: (int(p[0]), int(p[1]), 16.0))
    live.serve("/live/clip/get/is_playing", lambda p: (int(p[0]), int(p[1]), False))

    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        clips_tools = ClipTools(session)
        created = await clips_tools.create_clip(0, 0, 16)
        added = await clips_tools.add_notes(
            0,
            0,
            [
                Note(pitch=60, start=0, duration=1),
                Note(pitch=63, start=0, duration=1),
                Note(pitch=67, start=0, duration=1),
            ],
        )
        fetched = json.loads(await clips_tools.get_clip(0, 0))
    assert created.startswith("OK:")
    assert added.startswith("OK: added 3 notes")
    assert len(fetched["notes"]) == 3
    assert fetched["notes"][0] == {
        "pitch": 60,
        "start": 0.0,
        "duration": 1.0,
        "velocity": 100,
        "mute": False,
    }


@pytest.mark.asyncio
async def test_add_notes_refuses_an_empty_list(live: MiniLive, ports: tuple[int, int]) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await ClipTools(session).add_notes(0, 0, [])
    assert result.startswith("REFUSED:")
    assert _received(live, "/live/clip/add/notes") == []


@pytest.mark.asyncio
async def test_set_device_parameter_uses_the_catalog_parameter_index(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    names = ("Device On", "Frequency", "Resonance")
    state = {("parameter", 0): 0.0}
    writes: list[tuple[Any, ...]] = []
    live.serve("/live/device/get/parameters/name", lambda p: (int(p[0]), int(p[1]), *names))
    live.serve("/live/device/get/parameters/min", lambda p: (int(p[0]), int(p[1]), 0.0, 0.0, 0.0))
    live.serve("/live/device/get/parameters/max", lambda p: (int(p[0]), int(p[1]), 1.0, 1.0, 1.0))
    live.serve(
        "/live/device/set/parameter/value",
        lambda p: (
            writes.append(tuple(p)) or state.__setitem__(("parameter", int(p[2])), float(p[3]))
        ),
    )
    live.serve(
        "/live/device/get/parameter/value",
        lambda p: (int(p[0]), int(p[1]), int(p[2]), state[("parameter", int(p[2]))]),
    )
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await DeviceTools(session).set_device_parameter(0, 0, "Frequency", 0.5)
    assert result.startswith("OK:")
    # track, device, parameter_index, value -- the index the catalog used to omit.
    assert writes == [(0, 0, 1, 0.5)]


@pytest.mark.asyncio
async def test_set_device_parameter_refuses_out_of_range(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    live.serve("/live/device/get/parameters/name", lambda p: (int(p[0]), int(p[1]), "Frequency"))
    live.serve("/live/device/get/parameters/min", lambda p: (int(p[0]), int(p[1]), 0.0))
    live.serve("/live/device/get/parameters/max", lambda p: (int(p[0]), int(p[1]), 1.0))
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await DeviceTools(session).set_device_parameter(0, 0, "Frequency", 4.0)
    assert result.startswith("REFUSED:")
    assert _received(live, "/live/device/set/parameter/value") == []


@pytest.mark.asyncio
async def test_list_devices_returns_names_and_classes(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    live.serve("/live/track/get/devices/name", lambda p: (int(p[0]), "Operator", "Reverb"))
    live.serve("/live/track/get/devices/class_name", lambda p: (int(p[0]), "Operator", "Reverb"))
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = json.loads(await DeviceTools(session).list_devices(0))
    assert result == [
        {"index": 0, "name": "Operator", "class_name": "Operator"},
        {"index": 1, "name": "Reverb", "class_name": "Reverb"},
    ]


@pytest.mark.asyncio
async def test_catalog_call_returns_a_replying_address(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    live.serve("/live/song/get/tempo", lambda _p: (121.0,))
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = json.loads(await CatalogTools(session).catalog_call("/live/song/get/tempo"))
    assert result == {"address": "/live/song/get/tempo", "reply": 121.0}


@pytest.mark.asyncio
async def test_catalog_call_sends_a_silent_address_without_waiting(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    live.serve("/live/clips/unfilter", lambda _p: None)
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await CatalogTools(session).catalog_call("/live/clips/unfilter")
    assert result.startswith("SENT, NOT VERIFIED: /live/clips/unfilter")


@pytest.mark.asyncio
async def test_catalog_call_refuses_an_unknown_address(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await CatalogTools(session).catalog_call("/live/not/a/real/address")
    assert result.startswith("REFUSED:")


@pytest.mark.asyncio
async def test_read_only_consent_refuses_a_write(live: MiniLive, ports: tuple[int, int]) -> None:
    async with OscSession(
        send_port=ports[0], receive_port=ports[1], consent=Consent(read_only=True)
    ) as session:
        refused = await SessionTools(session).set_tempo(128)
        read = await SessionTools(session).get_session()
    assert refused.startswith("REFUSED:")
    assert json.loads(read)["tempo"] == 120.0
    assert _received(live, "/live/song/set/tempo") == []


@pytest.mark.asyncio
async def test_get_session_keeps_working_when_some_reads_fail(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        payload = json.loads(await SessionTools(session).get_session())
    assert payload["tempo"] == 120.0
    assert payload["num_tracks"] == 3
    assert len(payload["tracks"]) == 3
    # MiniLive does not serve every property; the failures are reported, not raised.
    assert payload["errors"]


@pytest.mark.asyncio
async def test_create_and_launch_a_scene(live: MiniLive, ports: tuple[int, int]) -> None:
    scenes: list[str] = []
    live.serve("/live/song/get/num_scenes", lambda _p: (len(scenes),))
    live.serve("/live/song/create_scene", lambda p: scenes.append(f"Scene {len(scenes) + 1}"))
    live.serve("/live/scene/fire", lambda p: None)
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        scenes_tools = SceneTools(session)
        created = await scenes_tools.create_scene()
        launched = await scenes_tools.launch_scene(0)
    assert created.startswith("OK:")
    assert launched.startswith("SENT, NOT VERIFIED:")


@pytest.mark.asyncio
async def test_set_loop_reads_back(live: MiniLive, ports: tuple[int, int]) -> None:
    state = {"loop": False, "start": 0.0, "length": 4.0}
    live.serve("/live/song/set/loop", lambda p: state.__setitem__("loop", bool(p[0])))
    live.serve("/live/song/set/loop_start", lambda p: state.__setitem__("start", float(p[0])))
    live.serve("/live/song/set/loop_length", lambda p: state.__setitem__("length", float(p[0])))
    live.serve("/live/song/get/loop", lambda _p: (state["loop"],))
    live.serve("/live/song/get/loop_start", lambda _p: (state["start"],))
    live.serve("/live/song/get/loop_length", lambda _p: (state["length"],))
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await SessionTools(session).set_loop(True, 8.0, 16.0)
    assert result.startswith("OK:")
    assert state == {"loop": True, "start": 8.0, "length": 16.0}


def test_catalog_is_the_single_gate() -> None:
    entry = catalog.find("/live/song/set/tempo")
    assert entry is not None and entry.risk == "write"
    assert catalog.find("/live/song/delete_track") is not None
