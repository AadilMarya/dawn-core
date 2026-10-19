"""Session and transport tools: tempo, playback, loop, metronome, overview."""

from __future__ import annotations

import json
from typing import Any

from ..session import OscCallError, OscSession, UnknownAddressError
from ._helpers import (
    MAX_TEMPO,
    MIN_TEMPO,
    Refused,
    ToolBase,
    check_range,
    error,
    read,
    refused,
    same,
    show,
    write_and_verify,
)


class SessionTools(ToolBase):
    """Tools that read or change the Live Set as a whole."""

    def __init__(self, session: OscSession) -> None:
        self.session = session

    async def get_session(self) -> str:
        """Read the current Set: tempo, transport, time signature, loop and every track.

        Use this first when the user refers to "the track", "the project" or a current
        value you have not read this turn. Returns JSON; individual read failures are
        listed under ``errors`` instead of discarding the whole picture.
        """
        session = self.session
        errors: list[str] = []
        overview: dict[str, Any] = {
            "tempo": None,
            "is_playing": None,
            "metronome": None,
            "signature": None,
            "loop": None,
            "num_tracks": None,
            "num_scenes": None,
            "tracks": [],
        }

        async def take(key: str, address: str, *args: int) -> Any:
            try:
                value = await read(session, address, *args)
            except (OscCallError, UnknownAddressError, TypeError, ValueError) as exc:
                errors.append(f"{key}: {exc}")
                return None
            overview[key] = value
            return value

        await take("tempo", "/live/song/get/tempo")
        await take("is_playing", "/live/song/get/is_playing")
        await take("metronome", "/live/song/get/metronome")
        numerator = await take("signature_numerator", "/live/song/get/signature_numerator")
        denominator = await take("signature_denominator", "/live/song/get/signature_denominator")
        if numerator is not None and denominator is not None:
            overview["signature"] = f"{int(numerator)}/{int(denominator)}"
        await take("loop", "/live/song/get/loop")
        await take("loop_start", "/live/song/get/loop_start")
        await take("loop_length", "/live/song/get/loop_length")
        count = await take("num_tracks", "/live/song/get/num_tracks")
        await take("num_scenes", "/live/song/get/num_scenes")

        tracks: list[dict[str, Any]] = []
        if isinstance(count, (int, float)):
            for index in range(int(count)):
                track: dict[str, Any] = {"index": index}
                track_errors: list[str] = []
                for key, address in (
                    ("name", "/live/track/get/name"),
                    ("mute", "/live/track/get/mute"),
                    ("solo", "/live/track/get/solo"),
                    ("arm", "/live/track/get/arm"),
                    ("volume", "/live/track/get/volume"),
                    ("panning", "/live/track/get/panning"),
                    ("num_devices", "/live/track/get/num_devices"),
                ):
                    try:
                        track[key] = await read(session, address, index)
                    except (OscCallError, UnknownAddressError, TypeError, ValueError) as exc:
                        track[key] = None
                        track_errors.append(f"{key}: {exc}")
                if track_errors:
                    track["errors"] = track_errors
                tracks.append(track)
        overview["tracks"] = tracks
        overview["errors"] = errors
        return json.dumps(overview, ensure_ascii=False)

    async def set_tempo(self, bpm: float) -> str:
        """Set the song tempo in beats per minute, then read it back.

        Refuses values outside 20-999 BPM.
        """
        try:
            check_range(bpm, MIN_TEMPO, MAX_TEMPO, "tempo")
        except Refused as exc:
            return refused(str(exc))
        return await write_and_verify(
            self.session,
            setter="/live/song/set/tempo",
            setter_args=(bpm,),
            getter="/live/song/get/tempo",
            expected=bpm,
            label="song.tempo",
        )

    async def set_metronome(self, enabled: bool) -> str:
        """Turn the metronome on or off, then read it back."""
        return await write_and_verify(
            self.session,
            setter="/live/song/set/metronome",
            setter_args=(enabled,),
            getter="/live/song/get/metronome",
            expected=enabled,
            label="song.metronome",
        )

    async def start_playback(self) -> str:
        """Start playback, then check the transport."""
        session = self.session
        try:
            await session.send("/live/song/start_playing")
        except (OscCallError, UnknownAddressError) as exc:
            return error(str(exc))
        return await self._transport_state(True)

    async def stop_playback(self) -> str:
        """Stop playback, then check the transport."""
        session = self.session
        try:
            await session.send("/live/song/stop_playing")
        except (OscCallError, UnknownAddressError) as exc:
            return error(str(exc))
        return await self._transport_state(False)

    async def set_loop(
        self, enabled: bool, start: float | None = None, length: float | None = None
    ) -> str:
        """Enable or disable the session loop, optionally moving its start and length.

        ``start`` is in beats. ``length`` is in beats and must be positive.
        """
        if start is not None:
            try:
                check_range(start, 0.0, 100_000.0, "loop start")
            except Refused as exc:
                return refused(str(exc))
        if length is not None:
            try:
                check_range(length, 0.01, 100_000.0, "loop length")
            except Refused as exc:
                return refused(str(exc))
        session = self.session
        try:
            await session.send("/live/song/set/loop", enabled)
            if start is not None:
                await session.send("/live/song/set/loop_start", start)
            if length is not None:
                await session.send("/live/song/set/loop_length", length)
            actual_enabled = await read(session, "/live/song/get/loop")
            actual_start = await read(session, "/live/song/get/loop_start")
            actual_length = await read(session, "/live/song/get/loop_length")
        except (OscCallError, UnknownAddressError) as exc:
            return error(f"loop was sent but the read-back failed: {exc}")
        ok = bool(actual_enabled) == bool(enabled)
        if start is not None:
            ok = ok and same(start, actual_start)
        if length is not None:
            ok = ok and same(length, actual_length)
        if ok:
            return (
                f"OK: song.loop is {bool(actual_enabled)}, start {show(actual_start)}, "
                f"length {show(actual_length)}."
            )
        return (
            f"MISMATCH: asked for loop={enabled} start={show(start)} length={show(length)}; "
            f"Live reports loop={bool(actual_enabled)} start={show(actual_start)} "
            f"length {show(actual_length)}."
        )

    async def _transport_state(self, expected: bool) -> str:
        try:
            actual = await read(self.session, "/live/song/get/is_playing")
        except (OscCallError, UnknownAddressError) as exc:
            return error(f"transport was sent but the read-back failed: {exc}")
        if bool(actual) == expected:
            return f"OK: song.is_playing is {bool(actual)}."
        return (
            f"SENT, NOT VERIFIED: asked for is_playing={expected}; Live reports "
            f"{bool(actual)}. Quantized launch may still be pending."
        )


__all__ = ["SessionTools"]
