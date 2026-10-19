"""Clip tools: create, inspect, write notes, loop, launch, stop, delete."""

from __future__ import annotations

import json
from typing import Any

from ..session import OscCallError, OscSession, UnknownAddressError
from ._helpers import (
    MAX_NOTES_PER_CALL,
    Note,
    Refused,
    ToolBase,
    check_index,
    check_range,
    error,
    read,
    refused,
    unwrap,
)


class ClipTools(ToolBase):
    """Tools that operate on one Session clip."""

    def __init__(self, session: OscSession) -> None:
        self.session = session

    async def create_clip(self, track_index: int, slot_index: int, length_beats: float) -> str:
        """Create an empty MIDI clip in a Session slot.

        ``length_beats`` is the clip length in beats (4 beats = one bar in 4/4).
        The slot must be empty.
        """
        try:
            check_index(track_index, "track_index")
            check_index(slot_index, "slot_index")
            check_range(length_beats, 0.01, 100_000.0, "clip length")
        except Refused as exc:
            return refused(str(exc))
        session = self.session
        try:
            await session.send("/live/clip_slot/create_clip", track_index, slot_index, length_beats)
            has_clip = await read(session, "/live/clip_slot/get/has_clip", track_index, slot_index)
            actual = await read(session, "/live/clip/get/length", track_index, slot_index)
        except (OscCallError, UnknownAddressError) as exc:
            return error(f"clip creation was sent but the read-back failed: {exc}")
        if not has_clip:
            return f"MISMATCH: asked for a clip at {track_index}:{slot_index}; the slot is empty."
        if abs(float(actual) - length_beats) > 0.001:
            return (
                f"MISMATCH: asked for a {length_beats:g}-beat clip at {track_index}:{slot_index}; "
                f"Live reports {float(actual):g} beats."
            )
        return f"OK: created a {float(actual):g}-beat clip at {track_index}:{slot_index}."

    async def get_clip(self, track_index: int, clip_index: int) -> str:
        """Read a Session clip: name, length, loop, playing state and every note.

        Returns JSON. Notes are objects with pitch, start, duration, velocity and mute.
        """
        try:
            check_index(track_index, "track_index")
            check_index(clip_index, "clip_index")
        except Refused as exc:
            return refused(str(exc))
        session = self.session
        errors: list[str] = []
        data: dict[str, Any] = {"track_index": track_index, "clip_index": clip_index}

        async def take(key: str, address: str, *args: int) -> Any:
            try:
                value = await read(session, address, *args)
            except (OscCallError, UnknownAddressError, TypeError, ValueError) as exc:
                errors.append(f"{key}: {exc}")
                return None
            data[key] = value
            return value

        await take("name", "/live/clip/get/name", track_index, clip_index)
        await take("length", "/live/clip/get/length", track_index, clip_index)
        await take("loop_start", "/live/clip/get/loop_start", track_index, clip_index)
        await take("loop_end", "/live/clip/get/loop_end", track_index, clip_index)
        await take("is_playing", "/live/clip/get/is_playing", track_index, clip_index)
        raw = await take("notes", "/live/clip/get/notes", track_index, clip_index)
        if isinstance(raw, (list, tuple)):
            values = list(raw)
            data["notes"] = [
                {
                    "pitch": int(values[i]),
                    "start": float(values[i + 1]),
                    "duration": float(values[i + 2]),
                    "velocity": int(values[i + 3]),
                    "mute": bool(values[i + 4]),
                }
                for i in range(0, len(values) - 4, 5)
            ]
        data["errors"] = errors
        return json.dumps(data, ensure_ascii=False)

    async def add_notes(self, track_index: int, clip_index: int, notes: list[Note]) -> str:
        """Add MIDI notes to a clip, then read the clip back and verify the note count.

        Each note has pitch (0-127), start (beats), duration (beats), velocity (1-127)
        and an optional mute flag. Add at most 512 notes per call.
        """
        try:
            check_index(track_index, "track_index")
            check_index(clip_index, "clip_index")
            if not notes:
                raise Refused("add at least one note.")
            if len(notes) > MAX_NOTES_PER_CALL:
                raise Refused(f"add at most {MAX_NOTES_PER_CALL} notes per call.")
        except Refused as exc:
            return refused(str(exc))
        session = self.session
        try:
            before = await self._note_count(track_index, clip_index)
            flat: list[Any] = []
            for note in notes:
                flat.extend((note.pitch, note.start, note.duration, note.velocity, note.mute))
            await session.send("/live/clip/add/notes", track_index, clip_index, *flat)
            after = await self._note_count(track_index, clip_index)
        except (OscCallError, UnknownAddressError) as exc:
            return error(f"notes were sent but the read-back failed: {exc}")
        expected = before + len(notes)
        if after == expected:
            return f"OK: added {len(notes)} notes; the clip now has {after}."
        return (
            f"MISMATCH: added {len(notes)} notes to {track_index}:{clip_index}; "
            f"expected {expected} total, Live reports {after}."
        )

    async def set_clip_loop(
        self, track_index: int, clip_index: int, start: float, end: float
    ) -> str:
        """Set a clip's loop start and end in beats, then read both back."""
        try:
            check_index(track_index, "track_index")
            check_index(clip_index, "clip_index")
            check_range(start, 0.0, 100_000.0, "loop start")
            check_range(end, 0.0, 100_000.0, "loop end")
            if end <= start:
                raise Refused("loop end must be greater than loop start.")
        except Refused as exc:
            return refused(str(exc))
        session = self.session
        try:
            await session.send("/live/clip/set/loop_start", track_index, clip_index, start)
            await session.send("/live/clip/set/loop_end", track_index, clip_index, end)
            actual_start = await read(session, "/live/clip/get/loop_start", track_index, clip_index)
            actual_end = await read(session, "/live/clip/get/loop_end", track_index, clip_index)
        except (OscCallError, UnknownAddressError) as exc:
            return error(f"loop was sent but the read-back failed: {exc}")
        if abs(float(actual_start) - start) <= 0.001 and abs(float(actual_end) - end) <= 0.001:
            return f"OK: clip loop is {float(actual_start):g} to {float(actual_end):g} beats."
        return (
            f"MISMATCH: asked for loop {start:g}-{end:g}; Live reports "
            f"{float(actual_start):g}-{float(actual_end):g}."
        )

    async def launch_clip(self, track_index: int, clip_index: int) -> str:
        """Fire a Session clip, then check whether it is playing."""
        try:
            check_index(track_index, "track_index")
            check_index(clip_index, "clip_index")
        except Refused as exc:
            return refused(str(exc))
        session = self.session
        try:
            await session.send("/live/clip_slot/fire", track_index, clip_index)
            playing = await read(session, "/live/clip/get/is_playing", track_index, clip_index)
        except (OscCallError, UnknownAddressError) as exc:
            return error(f"clip fire was sent but the read-back failed: {exc}")
        if playing:
            return f"OK: clip {track_index}:{clip_index} is playing."
        return (
            f"SENT, NOT VERIFIED: fired clip {track_index}:{clip_index}; it is not playing "
            "yet (launch quantization may still be pending)."
        )

    async def stop_clip(self, track_index: int, clip_index: int) -> str:
        """Stop a Session clip, then check that it is no longer playing."""
        try:
            check_index(track_index, "track_index")
            check_index(clip_index, "clip_index")
        except Refused as exc:
            return refused(str(exc))
        session = self.session
        try:
            await session.send("/live/clip_slot/stop", track_index, clip_index)
            playing = await read(session, "/live/clip/get/is_playing", track_index, clip_index)
        except (OscCallError, UnknownAddressError) as exc:
            return error(f"clip stop was sent but the read-back failed: {exc}")
        if not playing:
            return f"OK: clip {track_index}:{clip_index} is stopped."
        return f"MISMATCH: asked to stop {track_index}:{clip_index}; it is still playing."

    async def delete_clip(self, track_index: int, clip_index: int) -> str:
        """Delete a Session clip. Destructive: confirm the target with get_clip first."""
        try:
            check_index(track_index, "track_index")
            check_index(clip_index, "clip_index")
        except Refused as exc:
            return refused(str(exc))
        session = self.session
        try:
            await session.send("/live/clip_slot/delete_clip", track_index, clip_index)
            has_clip = await read(session, "/live/clip_slot/get/has_clip", track_index, clip_index)
        except (OscCallError, UnknownAddressError) as exc:
            return error(f"clip deletion was sent but the read-back failed: {exc}")
        if not has_clip:
            return f"OK: deleted clip {track_index}:{clip_index}."
        return f"MISMATCH: asked to delete {track_index}:{clip_index}; the slot still has a clip."

    async def _note_count(self, track_index: int, clip_index: int) -> int:
        reply = await self.session.call("/live/clip/get/notes", track_index, clip_index)
        value = unwrap(reply, (track_index, clip_index))
        if isinstance(value, (list, tuple)):
            return len(value) // 5
        return 0


__all__ = ["ClipTools"]
